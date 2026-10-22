"""Booking against the dispatch calendar: windows, capacity, idempotency, follow-up email.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import booking, followup, hours, main, prices

ET = ZoneInfo("America/New_York")


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=ET)


@pytest.fixture()
def api():  # type: ignore[no-untyped-def]
    cal, mail = booking.MemoryCalendar(), followup.MemoryMailer()

    def make(moment: str) -> TestClient:
        main.app.dependency_overrides[main.now] = lambda: at(moment)
        main.app.dependency_overrides[main.calendar] = lambda: cal
        main.app.dependency_overrides[main.mailer] = lambda: mail
        return TestClient(main.app)

    make.cal, make.mail = cal, mail  # type: ignore[attr-defined]
    yield make
    main.app.dependency_overrides.clear()


CALLER = {
    "caller_name": "Sam Rivera",
    "callback_number": "202-555-0147",
    "service_address": "4410 Elm Street, 20016",
    "problem": "Water heater pilot keeps going out",
    "urgency": "routine",
    "session_id": "s1",
}


def test_windows_respect_saturday_hours_and_lead_time() -> None:
    sched, rules = hours.load_schedule(), booking.load_rules()
    windows = booking.candidate_windows(sched, rules, at("2026-10-16 15:30"))  # Friday afternoon
    starts = [w.slot_id for w in windows]
    assert "2026-10-16T15:00" not in starts  # inside the two-hour lead
    assert "2026-10-17T13:00" not in starts  # Saturday closes at 2 p.m.
    assert starts[0] == "2026-10-17T08:00"
    assert windows[0].spoken() == "Saturday, October 17, between 8 AM and 10 AM"


def test_two_bookings_fill_a_window(api) -> None:  # type: ignore[no-untyped-def]
    client = api("2026-10-14 22:40")
    first_slot = client.get("/v1/appointments/slots").json()["slots"][0]["slot_id"]
    for n in range(2):
        r = client.post("/v1/appointments", json={**CALLER, "session_id": f"s{n}", "slot_id": first_slot})
        assert r.status_code == 200, r.text
    slots = [s["slot_id"] for s in client.get("/v1/appointments/slots").json()["slots"]]
    assert first_slot not in slots
    third = client.post("/v1/appointments", json={**CALLER, "session_id": "s9", "slot_id": first_slot})
    assert third.status_code == 409


def test_a_retried_booking_returns_the_same_booking(api) -> None:  # type: ignore[no-untyped-def]
    client = api("2026-10-14 22:40")
    slot = client.get("/v1/appointments/slots").json()["slots"][0]["slot_id"]
    a = client.post("/v1/appointments", json={**CALLER, "slot_id": slot}).json()
    b = client.post("/v1/appointments", json={**CALLER, "slot_id": slot}).json()
    assert a["booking_id"] == b["booking_id"] and len(api.cal.items) == 1


def test_follow_up_email_says_only_what_the_booking_says(api) -> None:  # type: ignore[no-untyped-def]
    client = api("2026-10-14 22:40")
    slot = client.get("/v1/appointments/slots").json()["slots"][0]["slot_id"]
    booked = client.post("/v1/appointments", json={**CALLER, "slot_id": slot}).json()
    result = client.post("/v1/followups", json={"booking_id": booked["booking_id"], "email": "sam@example.com"})
    assert result.json()["status"] == "queued_for_review"
    body = api.mail.messages[0].get_content()
    assert booked["window"] in body and "Water heater pilot" in body
    bad = client.post("/v1/followups", json={"booking_id": booked["booking_id"], "email": "sam at example"})
    assert bad.status_code == 422


def test_price_list_is_spoken_as_ranges() -> None:
    rows = {r["service_id"]: r for r in prices.price_list(now=0.0)}
    assert rows["diagnostic"]["say"] == "$129 flat"
    assert rows["water-heater-tank"]["say"] == "usually between $1,800 and $3,200"


def test_booking_ids_are_valid_calendar_event_ids() -> None:
    """The first live booking failed: the old 'bw' prefix has a 'w', outside base32hex."""
    import re

    request = booking.BookingRequest(**CALLER, slot_id="2026-10-15T08:00")
    assert re.fullmatch(r"[a-v0-9]{5,1024}", booking.booking_id(request))
