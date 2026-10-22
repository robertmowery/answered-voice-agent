"""Business hours, holidays and the on-call rotation, computed in code.

The agent asks; this module answers. Every rule lives in policy/schedule.yaml,
and every decision is a pure function of that file and a timestamp, so the
tests can pin any moment (a holiday, a daylight-saving change, a minute before
closing) without a clock or a network.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

POLICY_FILE = Path(__file__).resolve().parent.parent / "policy" / "schedule.yaml"
_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass(frozen=True)
class Technician:
    name: str
    phone: str


@dataclass(frozen=True)
class Schedule:
    tz: ZoneInfo
    hours: dict[str, tuple[time, time]]
    holidays: dict[date, str]
    rotation_start: date
    technicians: list[Technician]
    emergencies: list[str]


@dataclass(frozen=True)
class HoursStatus:
    open: bool
    reason: str  # "open", "after_hours", "weekend", "holiday"
    local_time: str
    today: str
    holiday: str | None
    next_open: str
    on_call_name: str
    transfer_number: str
    emergencies: list[str]

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _phone_overrides() -> dict[str, str]:
    """ON_CALL_NUMBERS=Dana=+1555...,Luis=+1555... replaces the placeholder numbers at run time."""
    raw = os.environ.get("ON_CALL_NUMBERS", "")
    pairs = (item.split("=", 1) for item in raw.split(",") if "=" in item)
    return {name.strip(): number.strip() for name, number in pairs}


def load_schedule(path: Path = POLICY_FILE) -> Schedule:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    overrides = _phone_overrides()
    hours = {}
    for day, span in raw.get("hours", {}).items():
        if day not in _DAYS:
            raise ValueError(f"Unknown weekday {day!r} in {path.name}")
        start, end = _hhmm(span[0]), _hhmm(span[1])
        if not start < end:
            raise ValueError(f"{day}: opening {span[0]} must be before closing {span[1]}")
        hours[day] = (start, end)
    techs = [Technician(t["name"], overrides.get(t["name"], t["phone"])) for t in raw["on_call"]["technicians"]]
    if not techs:
        raise ValueError("on_call.technicians must list at least one technician")
    for t in techs:
        if not (t.phone.startswith("+") and t.phone[1:].isdigit()):
            raise ValueError(f"{t.name}'s number must be E.164, like +12025550101")
    return Schedule(
        tz=ZoneInfo(raw["time_zone"]),
        hours=hours,
        holidays={date.fromisoformat(str(d)): name for d, name in (raw.get("holidays") or {}).items()},
        rotation_start=date.fromisoformat(str(raw["on_call"]["rotation_start"])),
        technicians=techs,
        emergencies=list(raw.get("emergencies", [])),
    )


def on_call(schedule: Schedule, at: datetime) -> Technician:
    """Weekly rotation; the handover is Monday at the opening hour (07:00 by default)."""
    local = at.astimezone(schedule.tz)
    handover = schedule.hours.get("mon", (time(7, 0), time(18, 0)))[0]
    monday = local.date() - timedelta(days=local.weekday())
    if local.weekday() == 0 and local.time() < handover:
        monday -= timedelta(days=7)
    weeks = (monday - schedule.rotation_start).days // 7
    return schedule.technicians[weeks % len(schedule.technicians)]


def _is_open_at(schedule: Schedule, local: datetime) -> tuple[bool, str]:
    if local.date() in schedule.holidays:
        return False, "holiday"
    span = schedule.hours.get(_DAYS[local.weekday()])
    if span is None:
        return False, "weekend"
    start, end = span
    return (start <= local.time() < end), ("open" if start <= local.time() < end else "after_hours")


def next_opening(schedule: Schedule, at: datetime) -> datetime:
    """The next moment the office opens, strictly after `at` if it is closed now."""
    local = at.astimezone(schedule.tz)
    for offset in range(0, 15):
        day = local.date() + timedelta(days=offset)
        span = schedule.hours.get(_DAYS[day.weekday()])
        if span is None or day in schedule.holidays:
            continue
        opening = datetime.combine(day, span[0], tzinfo=schedule.tz)
        if opening > local:
            return opening
    raise ValueError("No opening in the next two weeks; check the schedule")


def status(schedule: Schedule, at: datetime) -> HoursStatus:
    local = at.astimezone(schedule.tz)
    is_open, reason = _is_open_at(schedule, local)
    tech = on_call(schedule, at)
    opens = local if is_open else next_opening(schedule, at)
    return HoursStatus(
        open=is_open,
        reason=reason,
        local_time=local.strftime("%A %I:%M %p %Z").replace(" 0", " "),
        today=local.date().isoformat(),
        holiday=schedule.holidays.get(local.date()),
        next_open=opens.strftime("%A, %B %d at %I:%M %p").replace(" 0", " "),
        on_call_name=tech.name,
        transfer_number=tech.phone,
        emergencies=schedule.emergencies,
    )
