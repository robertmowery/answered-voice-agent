"""Ticket worker: turns ticket.created events into records the office reads.

Pub/Sub pushes each event here. The worker writes the ticket to Firestore
first, with the ticket ID as the document ID, so a redelivered event is
detected. Then, if configured, it appends a row to the office's Google Sheet and
posts an alert to a Google Chat space, and marks the ticket delivered. If
either of those fails, the handler returns an error and Pub/Sub redelivers;
a ticket already marked delivered is skipped, so the office never sees it twice.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Protocol

from fastapi import FastAPI, Request, Response

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ticket-worker")

app = FastAPI(title="Brightwater ticket worker")

SHEET_COLUMNS = [
    "ticket_id",
    "created_at",
    "office_review_by",
    "urgency",
    "caller_name",
    "callback_number",
    "service_address",
    "problem",
]


class Store(Protocol):
    def claim(self, ticket_id: str, ticket: dict[str, Any]) -> bool:
        """Record the ticket; False if it was already fully delivered."""
        ...

    def mark_delivered(self, ticket_id: str) -> None: ...


class FirestoreStore:
    def __init__(self) -> None:
        from google.cloud import firestore

        self._col = firestore.Client().collection("tickets")

    def claim(self, ticket_id: str, ticket: dict[str, Any]) -> bool:
        from google.api_core.exceptions import AlreadyExists

        doc = self._col.document(ticket_id)
        try:
            doc.create({**ticket, "delivered": False})
            return True
        except AlreadyExists:
            snapshot = doc.get()
            return not bool(snapshot.get("delivered"))

    def mark_delivered(self, ticket_id: str) -> None:
        self._col.document(ticket_id).update({"delivered": True})


def sheet_row(ticket: dict[str, Any]) -> list[str]:
    return [str(ticket.get(c, "")) for c in SHEET_COLUMNS]


def append_to_sheet(sheet_id: str, ticket: dict[str, Any]) -> None:
    """The office's existing spreadsheet, shared with this service's account as an editor."""
    import google.auth
    from googleapiclient.discovery import build

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheets.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=os.environ.get("TICKETS_SHEET_RANGE", "A:H"),  # first tab by default
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [sheet_row(ticket)]},
    ).execute()


def chat_text(ticket: dict[str, Any]) -> str:
    flag = "EMERGENCY " if ticket.get("urgency") == "emergency" else ""
    return (
        f"{flag}New after-hours ticket {ticket['ticket_id']} ({ticket.get('urgency')}): "
        f"{ticket.get('problem')} at {ticket.get('service_address')}. "
        f"Review by {ticket.get('office_review_by')}."
    )


def post_to_chat(webhook_url: str, ticket: dict[str, Any]) -> None:
    import httpx

    httpx.post(webhook_url, json={"text": chat_text(ticket)}, timeout=10).raise_for_status()


_store: Store | None = None


def store() -> Store:
    global _store
    if _store is None:
        _store = FirestoreStore()
    return _store


def decode(envelope: dict[str, Any]) -> dict[str, Any]:
    data = envelope["message"]["data"]
    return dict(json.loads(base64.b64decode(data).decode("utf-8")))


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/pubsub")
async def on_event(request: Request) -> Response:
    ticket = decode(await request.json())
    if ticket.get("type") != "ticket.created":
        return Response(status_code=204)
    if not store().claim(ticket["ticket_id"], ticket):
        log.info("Duplicate delivery for %s ignored", ticket["ticket_id"])
        return Response(status_code=204)
    if sheet_id := os.environ.get("TICKETS_SHEET_ID"):
        append_to_sheet(sheet_id, ticket)
    if webhook := os.environ.get("CHAT_WEBHOOK_URL"):
        post_to_chat(webhook, ticket)
    store().mark_delivered(ticket["ticket_id"])
    log.info(json.dumps({"severity": "INFO", "message": "ticket recorded", "ticket_id": ticket["ticket_id"]}))
    return Response(status_code=204)
