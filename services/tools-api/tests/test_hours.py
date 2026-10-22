"""Hours policy: pinned moments, no clock, no network.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import hours

ET = ZoneInfo("America/New_York")


@pytest.fixture(scope="module")
def sched() -> hours.Schedule:
    return hours.load_schedule()


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=ET)


@pytest.mark.parametrize(
    ("moment", "is_open", "reason"),
    [
        ("2026-10-14 06:59", False, "after_hours"),  # Wednesday, a minute before opening
        ("2026-10-14 07:00", True, "open"),
        ("2026-10-14 17:59", True, "open"),
        ("2026-10-14 18:00", False, "after_hours"),  # closing is exclusive
        ("2026-10-17 13:30", True, "open"),  # Saturday short hours
        ("2026-10-17 14:00", False, "after_hours"),
        ("2026-10-18 10:00", False, "weekend"),  # Sunday
        ("2026-11-26 10:00", False, "holiday"),  # Thanksgiving, a Thursday
    ],
)
def test_open_and_closed(sched: hours.Schedule, moment: str, is_open: bool, reason: str) -> None:
    result = hours.status(sched, at(moment))
    assert (result.open, result.reason) == (is_open, reason)


def test_next_opening_skips_sunday_and_holidays(sched: hours.Schedule) -> None:
    assert hours.next_opening(sched, at("2026-10-17 15:00")) == at("2026-10-19 07:00")  # Sat after close -> Mon
    assert hours.next_opening(sched, at("2026-11-25 19:00")) == at("2026-11-28 08:00")  # Thanksgiving weekend


def test_next_open_is_said_aloud_without_leading_zeros(sched: hours.Schedule) -> None:
    assert hours.status(sched, at("2026-10-14 22:40")).next_open == "Thursday, October 15 at 7:00 AM"


def test_daylight_saving_change_keeps_local_hours(sched: hours.Schedule) -> None:
    # Clocks fall back on Sunday Nov 1, 2026; Monday still opens at 7:00 local time.
    assert hours.next_opening(sched, at("2026-10-31 15:00")) == at("2026-11-02 07:00")


def test_rotation_hands_over_monday_at_opening(sched: hours.Schedule) -> None:
    sunday_night = hours.on_call(sched, at("2026-10-11 23:00"))
    monday_early = hours.on_call(sched, at("2026-10-12 06:59"))
    monday_open = hours.on_call(sched, at("2026-10-12 07:00"))
    assert sunday_night == monday_early
    assert monday_open != monday_early
    assert hours.on_call(sched, at("2026-10-05 07:00")).name == "Dana"  # rotation_start


def test_real_numbers_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ON_CALL_NUMBERS", "Dana=+15555550199")
    sched = hours.load_schedule()
    assert sched.technicians[0].phone == "+15555550199"


def test_numbers_must_be_e164(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ON_CALL_NUMBERS", "Dana=555-0101")
    with pytest.raises(ValueError, match="E.164"):
        hours.load_schedule()
