"""The HTTP surface matches the OpenAPI contract the agent reads, and behaves.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from fastapi.testclient import TestClient

from app import main, tickets

CONTRACT = Path(__file__).resolve().parents[3] / "agent" / "tools" / "brightwater_api.yaml"
ET = ZoneInfo("America/New_York")


@pytest.fixture()
def client_at():  # type: ignore[no-untyped-def]
    sent = tickets.LogPublisher()

    def make(moment: str) -> TestClient:
        main.app.dependency_overrides[main.now] = lambda: datetime.fromisoformat(moment).replace(tzinfo=ET)
        main.app.dependency_overrides[main.publisher] = lambda: sent
        return TestClient(main.app)

    make.sent = sent  # type: ignore[attr-defined]
    yield make
    main.app.dependency_overrides.clear()


def test_every_contract_operation_is_served() -> None:
    contract = yaml.safe_load(CONTRACT.read_text())
    wanted = {op["operationId"] for path in contract["paths"].values() for op in path.values()}
    served = {r.operation_id for r in main.app.routes if getattr(r, "operation_id", None)}
    assert wanted <= served, f"contract operations missing from the API: {wanted - served}"


def test_hours_after_close(client_at) -> None:  # type: ignore[no-untyped-def]
    body = client_at("2026-10-14 22:40").get("/v1/hours/status").json()
    assert body["open"] is False and body["reason"] == "after_hours"
    assert body["transfer_number"].startswith("+1")


def test_after_hours_ticket_is_published_and_due_next_opening(client_at) -> None:  # type: ignore[no-untyped-def]
    client = client_at("2026-10-14 22:40")
    payload = {
        "caller_name": "Sam Rivera",
        "callback_number": "(202) 555-0147",
        "service_address": "20016",
        "problem": "Water heater pilot keeps going out",
        "urgency": "routine",
        "session_id": "abc",
    }
    first = client.post("/v1/tickets", json=payload).json()
    second = client.post("/v1/tickets", json=payload).json()
    assert first["ticket_id"] == second["ticket_id"], "a retried call must not create a second ticket"
    assert first["office_review_by"] == "Thursday, October 15 at 7:00 AM"
    event = client_at.sent.sent[0]
    assert event["type"] == "ticket.created" and event["callback_number"] == "+12025550147"


def test_bad_callback_number_is_rejected(client_at) -> None:  # type: ignore[no-untyped-def]
    payload = {
        "caller_name": "Sam",
        "callback_number": "555-0147",
        "service_address": "20016",
        "problem": "Leak",
        "urgency": "urgent",
    }
    assert client_at("2026-10-14 22:40").post("/v1/tickets", json=payload).status_code == 422
