"""Ticket worker: idempotent delivery, sheet rows, chat text.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import main

TICKET = {
    "type": "ticket.created",
    "ticket_id": "BW-20261014-ABC123",
    "created_at": "2026-10-15T02:40:00+00:00",
    "office_review_by": "Thursday, October 15 at 7:00 AM",
    "caller_name": "Sam Rivera",
    "callback_number": "+12025550147",
    "service_address": "20016",
    "problem": "Water heater pilot keeps going out",
    "urgency": "routine",
}


class MemoryStore:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    def claim(self, ticket_id: str, ticket: dict[str, Any]) -> bool:
        if ticket_id in self.docs:
            return not self.docs[ticket_id]["delivered"]
        self.docs[ticket_id] = {**ticket, "delivered": False}
        return True

    def mark_delivered(self, ticket_id: str) -> None:
        self.docs[ticket_id]["delivered"] = True


def envelope(payload: dict[str, Any]) -> dict[str, Any]:
    return {"message": {"data": base64.b64encode(json.dumps(payload).encode()).decode()}}


@pytest.fixture()
def worker(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    mem = MemoryStore()
    rows: list[list[str]] = []
    monkeypatch.setattr(main, "_store", mem)
    monkeypatch.setenv("TICKETS_SHEET_ID", "sheet-123")
    monkeypatch.setattr(main, "append_to_sheet", lambda sid, t: rows.append(main.sheet_row(t)))
    return TestClient(main.app), mem, rows


def test_redelivery_writes_one_row(worker) -> None:  # type: ignore[no-untyped-def]
    client, mem, rows = worker
    assert client.post("/pubsub", json=envelope(TICKET)).status_code == 204
    assert client.post("/pubsub", json=envelope(TICKET)).status_code == 204
    assert len(rows) == 1 and rows[0][0] == TICKET["ticket_id"]
    assert mem.docs[TICKET["ticket_id"]]["delivered"] is True


def test_failed_sheet_write_is_retried_not_lost(worker, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    client, mem, rows = worker

    def boom(sid: str, t: dict[str, Any]) -> None:
        raise RuntimeError("Sheets unavailable")

    monkeypatch.setattr(main, "append_to_sheet", boom)
    with pytest.raises(RuntimeError):
        client.post("/pubsub", json=envelope(TICKET))
    monkeypatch.setattr(main, "append_to_sheet", lambda sid, t: rows.append(main.sheet_row(t)))
    assert client.post("/pubsub", json=envelope(TICKET)).status_code == 204
    assert len(rows) == 1


def test_chat_text_flags_emergencies() -> None:
    assert main.chat_text({**TICKET, "urgency": "emergency"}).startswith("EMERGENCY ")
    assert "Review by Thursday" in main.chat_text(TICKET)
