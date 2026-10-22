"""Warm hand-offs: queue and location routing, SIP header hygiene, no card numbers forwarded.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app import handoff

AT = datetime(2026, 10, 15, 10, 0, tzinfo=ZoneInfo("America/New_York"))


def request(**kw: object) -> handoff.HandoffRequest:
    base = {
        "queue": "billing",
        "intent": "dispute invoice",
        "summary": "Caller says she was billed twice for the October 3 visit, invoice 4471.",
        "caller_name": "Maria Lopez",
        "callback_number": "410-555-0188",
        "zip_code": "21201",
        "session_id": "s1",
    }
    return handoff.HandoffRequest(**{**base, **kw})  # type: ignore[arg-type]


def test_routes_to_the_queue_and_the_acquired_location() -> None:
    store = handoff.MemoryHandoffs()
    out = handoff.prepare(handoff.load_policy(), store, request(), AT)
    assert out.location == "Brightwater East (formerly Harbor Plumbing)"
    params = out.end_session_params
    assert params["telephonyTransferCall"]["phoneNumber"] == "+12025550111"
    assert params["liveAgentHandoff"]["sipRefer"] is True
    assert params["liveAgentHandoff"]["xHeaders"]["handoff-id"] == out.handoff_id
    assert store.get(out.handoff_id)["summary"].startswith("Caller says")


def test_card_numbers_never_reach_the_desk_or_the_headers() -> None:
    store = handoff.MemoryHandoffs()
    out = handoff.prepare(
        handoff.load_policy(),
        store,
        request(
            summary="Wants to pay now, read out 4111 1111 1111 1111 before I stopped her.",
            intent="pay 4111111111111111",
        ),
        AT,
    )
    assert "4111" not in str(store.get(out.handoff_id))
    assert "4111" not in str(out.end_session_params)


def test_header_values_are_short_and_plain() -> None:
    value = handoff.header_value("refund: <script>alert(1)</script> " + "x" * 300, 128)
    assert len(value) <= 128 and "<" not in value


def test_queue_numbers_come_from_the_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("QUEUE_NUMBERS", "billing=+15555550100")
    assert handoff.load_policy()["queues"]["billing"]["number"] == "+15555550100"


def test_a_handoff_needs_the_callers_name_number_and_zip() -> None:
    import pytest
    from pydantic import ValidationError

    for missing in ("caller_name", "callback_number", "zip_code"):
        fields = request().model_dump()
        fields.pop(missing)
        with pytest.raises(ValidationError):
            handoff.HandoffRequest(**fields)
    assert request(zip_code="declined", callback_number="declined").zip_code == "declined"
