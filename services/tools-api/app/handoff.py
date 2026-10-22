"""Warm hand-offs: give the person who picks up the context, not just the call.

The agent calls prepareHandoff with why the caller needs a person and a short
summary. This module picks the queue and the location, stores the full context
under a handoff ID, and returns the end_session parameters that transfer the
call with SIP headers the call desk can read: the handoff ID, the queue, the
location and the intent. The person on the desk opens the handoff by ID and
sees the summary before they say hello.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

import yaml
from pydantic import BaseModel, Field

POLICY = Path(__file__).resolve().parent.parent / "policy" / "routing.yaml"
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")

Queue = Literal["billing", "scheduling", "service"]


class HandoffRequest(BaseModel):
    queue: Queue = Field(description="billing, scheduling or service")
    intent: str = Field(min_length=3, max_length=60, description="A few words, like 'dispute invoice'")
    summary: str = Field(min_length=10, max_length=600, description="What the caller needs and what you already did")
    # Required: a hand-off without these makes the person on the desk ask again, which is
    # the failure a warm hand-off exists to prevent. "declined" is allowed when the caller won't say.
    caller_name: str = Field(min_length=2, max_length=80, description="Ask the caller; 'declined' if they won't say")
    callback_number: str = Field(min_length=7, max_length=20, description="Ask the caller; 'declined' if they won't say")
    zip_code: str = Field(pattern=r"^(\d{5}|declined)$", description="Five digits; 'declined' if they won't say")
    booking_or_ticket: str | None = None
    session_id: str | None = None


class HandoffPrepared(BaseModel):
    handoff_id: str
    queue: str
    location: str
    end_session_params: dict[str, Any]
    say: str


class HandoffStore(Protocol):
    def put(self, handoff_id: str, record: dict[str, Any]) -> None: ...

    def get(self, handoff_id: str) -> dict[str, Any] | None: ...


class FirestoreHandoffs:
    def __init__(self) -> None:
        from google.cloud import firestore

        self._col = firestore.Client().collection("handoffs")

    def put(self, handoff_id: str, record: dict[str, Any]) -> None:
        self._col.document(handoff_id).set(record)

    def get(self, handoff_id: str) -> dict[str, Any] | None:
        snap = self._col.document(handoff_id).get()
        return snap.to_dict() if snap.exists else None


class MemoryHandoffs:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def put(self, handoff_id: str, record: dict[str, Any]) -> None:
        self.items[handoff_id] = record

    def get(self, handoff_id: str) -> dict[str, Any] | None:
        return self.items.get(handoff_id)


def make_store() -> HandoffStore:
    return FirestoreHandoffs() if os.environ.get("GOOGLE_CLOUD_PROJECT") else MemoryHandoffs()


def load_policy(path: Path = POLICY) -> dict[str, Any]:
    policy = dict(yaml.safe_load(path.read_text(encoding="utf-8")))
    overrides = dict(item.split("=", 1) for item in os.environ.get("QUEUE_NUMBERS", "").split(",") if "=" in item)
    for name, queue in policy["queues"].items():
        queue["number"] = overrides.get(name, queue["number"])
    return policy


def location_for(policy: dict[str, Any], zip_code: str | None) -> dict[str, Any]:
    digits = re.sub(r"\D", "", zip_code or "")
    for loc in policy["locations"]:
        if any(digits.startswith(p) for p in loc["zip_prefixes"]):
            return dict(loc)
    return dict(policy["locations"][0])


def scrub(text: str) -> str:
    """Never forward a card number to a person or a header, even if the caller said one."""
    return CARD.sub("[card number removed]", text)


def header_value(text: str, limit: int) -> str:
    clean = re.sub(r"[^A-Za-z0-9 ._-]", "", text).strip().replace(" ", "-")
    return clean[:limit]


def prepare(policy: dict[str, Any], store: HandoffStore, request: HandoffRequest, at: datetime) -> HandoffPrepared:
    location = location_for(policy, request.zip_code)
    queue = policy["queues"][request.queue]
    basis = "|".join([request.session_id or at.isoformat(), request.queue, request.intent])
    handoff_id = "HO-" + hashlib.sha256(basis.encode()).hexdigest()[:10].upper()
    record = {
        **{k: scrub(v) if isinstance(v, str) else v for k, v in request.model_dump().items()},
        "handoff_id": handoff_id,
        "location": location["id"],
        "location_name": location["name"],
        "created_at": at.isoformat(),
    }
    store.put(handoff_id, record)
    limit = int(policy["headers"]["max_value_length"])
    params = {
        "telephonyTransferCall": {"phoneNumber": queue["number"]},
        "liveAgentHandoff": {
            "sipRefer": True,
            "xHeaders": {
                "handoff-id": handoff_id,
                "queue": request.queue,
                "location": location["id"],
                "intent": header_value(scrub(request.intent), limit),
            },
        },
    }
    return HandoffPrepared(
        handoff_id=handoff_id,
        queue=request.queue,
        location=location["name"],
        end_session_params=params,
        say=(
            f"I'm connecting you with our {request.queue} team now. "
            "They'll have the details, so you won't need to repeat yourself."
        ),
    )
