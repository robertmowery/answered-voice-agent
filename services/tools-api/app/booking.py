"""Appointment windows and bookings on the dispatch calendar.

The dispatcher already runs the day from a Google Calendar. The agent books
into that same calendar through two operations: find open windows, then book
one. Capacity is counted from the calendar itself, so a job the dispatcher
adds by hand closes a window for the agent too. There is no second schedule
to keep in sync.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, Field

from app import hours
from app.tickets import TicketRequest

POLICY_FILE = Path(__file__).resolve().parent.parent / "policy" / "schedule.yaml"


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    @property
    def slot_id(self) -> str:
        return self.start.strftime("%Y-%m-%dT%H:%M")

    def spoken(self) -> str:
        def hour(t: datetime) -> str:
            return t.strftime("%I %p").lstrip("0") if t.minute == 0 else t.strftime("%I:%M %p").lstrip("0")

        return f"{self.start:%A, %B} {self.start.day}, between {hour(self.start)} and {hour(self.end)}"


@dataclass(frozen=True)
class AppointmentRules:
    windows: list[tuple[time, time]]
    per_window: int
    days_ahead: int
    lead: timedelta


def load_rules(path: Path = POLICY_FILE) -> AppointmentRules:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["appointments"]
    windows = []
    for span in raw["windows"]:
        start, end = span.split("-")
        windows.append((hours._hhmm(start), hours._hhmm(end)))
    return AppointmentRules(
        windows=windows,
        per_window=int(raw["technicians_per_window"]),
        days_ahead=int(raw["days_ahead"]),
        lead=timedelta(hours=float(raw["earliest_hours_from_now"])),
    )


class Calendar(Protocol):
    def events(self, start: datetime, end: datetime) -> list[dict[str, Any]]: ...

    def insert(self, event_id: str, body: dict[str, Any]) -> dict[str, Any]: ...

    def get(self, event_id: str) -> dict[str, Any] | None: ...


class GoogleCalendar:
    """The dispatch calendar, owned by the tools API's service account and shared with the office."""

    def __init__(self, calendar_id: str) -> None:
        import google.auth
        from googleapiclient.discovery import build

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/calendar"])
        self._api = build("calendar", "v3", credentials=creds, cache_discovery=False)
        self._id = calendar_id

    def events(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        result = (
            self._api.events()
            .list(calendarId=self._id, timeMin=start.isoformat(), timeMax=end.isoformat(), singleEvents=True)
            .execute()
        )
        return [e for e in result.get("items", []) if e.get("status") != "cancelled"]

    def insert(self, event_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from googleapiclient.errors import HttpError

        try:
            return dict(self._api.events().insert(calendarId=self._id, body={**body, "id": event_id}).execute())
        except HttpError as err:
            if err.resp.status == 409:  # same booking retried: return the one that exists
                return dict(self._api.events().get(calendarId=self._id, eventId=event_id).execute())
            raise

    def get(self, event_id: str) -> dict[str, Any] | None:
        from googleapiclient.errors import HttpError

        try:
            return dict(self._api.events().get(calendarId=self._id, eventId=event_id).execute())
        except HttpError as err:
            if err.resp.status == 404:
                return None
            raise


class MemoryCalendar:
    """Readers without Google Workspace, and the tests."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def events(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        def overlaps(e: dict[str, Any]) -> bool:
            s = datetime.fromisoformat(e["start"]["dateTime"])
            f = datetime.fromisoformat(e["end"]["dateTime"])
            return s < end and f > start

        return [e for e in self.items.values() if overlaps(e)]

    def insert(self, event_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.items.setdefault(event_id, {**body, "id": event_id})

    def get(self, event_id: str) -> dict[str, Any] | None:
        return self.items.get(event_id)


def make_calendar() -> Calendar:
    calendar_id = os.environ.get("DISPATCH_CALENDAR_ID")
    return GoogleCalendar(calendar_id) if calendar_id else MemoryCalendar()


def candidate_windows(sched: hours.Schedule, rules: AppointmentRules, at: datetime) -> list[Window]:
    """Every window inside office hours, from `lead` after now through `days_ahead` business days."""
    local = at.astimezone(sched.tz)
    earliest = local + rules.lead
    out: list[Window] = []
    day: date = local.date()
    business_days = 0
    while business_days < rules.days_ahead and (day - local.date()).days < 14:
        span = sched.hours.get(hours._DAYS[day.weekday()])
        if span is not None and day not in sched.holidays:
            business_days += 1
            for start, end in rules.windows:
                if start >= span[0] and end <= span[1]:
                    w = Window(datetime.combine(day, start, sched.tz), datetime.combine(day, end, sched.tz))
                    if w.start >= earliest:
                        out.append(w)
        day += timedelta(days=1)
    return out


def open_windows(
    sched: hours.Schedule, rules: AppointmentRules, cal: Calendar, at: datetime, limit: int = 3
) -> list[Window]:
    windows = candidate_windows(sched, rules, at)
    if not windows:
        return []
    booked = cal.events(windows[0].start, windows[-1].end)
    free = []
    for w in windows:
        taken = sum(1 for e in booked if e.get("extendedProperties", {}).get("private", {}).get("slot_id") == w.slot_id)
        if taken < rules.per_window:
            free.append(w)
        if len(free) == limit:
            break
    return free


class BookingRequest(TicketRequest):
    slot_id: str = Field(description="One of the slot_id values from findAppointmentSlots, exactly")
    service_id: str | None = Field(default=None, description="From getPriceList, if known")
    email: str | None = Field(default=None, description="For the confirmation email, if the caller wants one")


class BookingConfirmed(BaseModel):
    booking_id: str
    window: str
    message: str


class SlotUnavailable(Exception):
    pass


def booking_id(request: BookingRequest) -> str:
    """Calendar event IDs allow only 0-9 and a-v (base32hex). A hex digest fits; the prefix must too.

    Same caller, slot and problem: same ID, so a retried booking returns the existing event.
    """
    basis = "|".join([request.slot_id, request.callback_number, request.problem.lower(), request.session_id or ""])
    return "bk" + hashlib.sha256(basis.encode()).hexdigest()[:24]


def book(
    sched: hours.Schedule, rules: AppointmentRules, cal: Calendar, request: BookingRequest, at: datetime
) -> BookingConfirmed:
    wanted = next((w for w in open_windows(sched, rules, cal, at, limit=100) if w.slot_id == request.slot_id), None)
    event_id = booking_id(request)
    if wanted is None:
        existing = cal.get(event_id)
        if existing is None:
            raise SlotUnavailable(request.slot_id)
        start = datetime.fromisoformat(existing["start"]["dateTime"])
        end = datetime.fromisoformat(existing["end"]["dateTime"])
        wanted = Window(start, end)  # a retry of a booking that already took the last place
    details = request.model_dump(exclude_none=True)
    body = {
        "summary": f"{request.problem[:60]} ({request.caller_name})",
        "location": request.service_address,
        "description": "\n".join(f"{k}: {v}" for k, v in details.items() if k != "session_id")
        + "\nBooked by the Brightwater front desk agent.",
        "start": {"dateTime": wanted.start.isoformat(), "timeZone": str(sched.tz)},
        "end": {"dateTime": wanted.end.isoformat(), "timeZone": str(sched.tz)},
        "extendedProperties": {"private": {"slot_id": wanted.slot_id, **{k: str(v) for k, v in details.items()}}},
    }
    cal.insert(event_id, body)
    return BookingConfirmed(
        booking_id=event_id,
        window=wanted.spoken(),
        message=f"Booked for {wanted.spoken()}. The technician calls about 30 minutes before arriving.",
    )
