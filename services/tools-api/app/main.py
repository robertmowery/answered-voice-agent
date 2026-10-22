"""Brightwater tools API: the only way the agent touches the business.

Every route here is an operation in agent/tools/brightwater_api.yaml, the
OpenAPI contract CX Agent Studio reads. The agent never sees a database, a
calendar or a spreadsheet directly; it calls these operations, and each one
does a single, bounded thing.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException

from app import booking, followup, handoff, hours, payments, prices, tickets

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Brightwater tools API", version="5.0.0")


@lru_cache
def schedule() -> hours.Schedule:
    return hours.load_schedule()


@lru_cache
def publisher() -> tickets.Publisher:
    return tickets.make_publisher()


@lru_cache
def rules() -> booking.AppointmentRules:
    return booking.load_rules()


@lru_cache
def calendar() -> booking.Calendar:
    return booking.make_calendar()


@lru_cache
def mailer() -> followup.Mailer:
    return followup.make_mailer()


def now() -> datetime:
    return datetime.now(UTC)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/hours/status", operation_id="getHoursStatus")
def get_hours_status(at: datetime = Depends(now), sched: hours.Schedule = Depends(schedule)) -> dict[str, object]:
    """Is the office open right now, and if not, who is on call and when does it open?"""
    return hours.status(sched, at).as_dict()


@app.post("/v1/tickets", operation_id="createTicket", response_model=tickets.TicketCreated)
def create_ticket(
    body: tickets.TicketRequest,
    at: datetime = Depends(now),
    sched: hours.Schedule = Depends(schedule),
    pub: tickets.Publisher = Depends(publisher),
) -> tickets.TicketCreated:
    """Record a callback request as a ticket the office reviews at its next opening."""
    current = hours.status(sched, at)
    review_by = "today, during office hours" if current.open else current.next_open
    return tickets.create(body, at, review_by, pub)


@app.get("/v1/prices", operation_id="getPriceList")
def get_price_list() -> dict[str, object]:
    """The office's published prices: flat fees and typical ranges, with the office's notes."""
    return {"prices": prices.price_list()}


@app.get("/v1/appointments/slots", operation_id="findAppointmentSlots")
def find_slots(
    at: datetime = Depends(now),
    sched: hours.Schedule = Depends(schedule),
    appt: booking.AppointmentRules = Depends(rules),
    cal: booking.Calendar = Depends(calendar),
) -> dict[str, object]:
    """The next three open arrival windows on the dispatch calendar."""
    windows = booking.open_windows(sched, appt, cal, at)
    return {"slots": [{"slot_id": w.slot_id, "say": w.spoken()} for w in windows]}


@app.post("/v1/appointments", operation_id="bookAppointment", response_model=booking.BookingConfirmed)
def book_appointment(
    body: booking.BookingRequest,
    at: datetime = Depends(now),
    sched: hours.Schedule = Depends(schedule),
    appt: booking.AppointmentRules = Depends(rules),
    cal: booking.Calendar = Depends(calendar),
) -> booking.BookingConfirmed:
    """Book one of the offered windows. Fails with 409 if it was taken in the meantime."""
    try:
        return booking.book(sched, appt, cal, body, at)
    except booking.SlotUnavailable as err:
        raise HTTPException(409, "That window was just taken. Call findAppointmentSlots and offer another.") from err


@app.post("/v1/followups", operation_id="sendFollowUpEmail", response_model=followup.FollowUpResult)
def send_follow_up(
    body: followup.FollowUpRequest,
    cal: booking.Calendar = Depends(calendar),
    mail: followup.Mailer = Depends(mailer),
    sched: hours.Schedule = Depends(schedule),
) -> followup.FollowUpResult:
    """Email the booking confirmation from the office's Workspace business email."""
    if not followup.EMAIL.match(body.email):
        raise HTTPException(422, "That doesn't look like an email address. Ask the caller to spell it again.")
    event = cal.get(body.booking_id)
    if event is None:
        raise HTTPException(404, "No booking with that ID.")
    start = datetime.fromisoformat(event["start"]["dateTime"]).astimezone(sched.tz)
    end = datetime.fromisoformat(event["end"]["dateTime"]).astimezone(sched.tz)
    event = {**event, "_window": booking.Window(start, end).spoken()}
    sender = os.environ.get("FOLLOWUP_SENDER", "office@example.com")
    status = mail.send(followup.render(event, body.email, sender))
    said = "sent" if status == "sent" else "will be sent by the office shortly"
    return followup.FollowUpResult(status=status, message=f"The confirmation email {said}.")


@app.post("/v1/payment-links", operation_id="sendPaymentLink", response_model=payments.PaymentLinkResult)
def send_payment_link(
    body: payments.PaymentLinkRequest,
    mail: followup.Mailer = Depends(mailer),
) -> payments.PaymentLinkResult:
    """Email the caller the secure page to review and pay for an order the commerce agent started."""
    try:
        checkout = payments.fetch_checkout(body.checkout_id)
        message = payments.render(checkout, body.email, os.environ.get("FOLLOWUP_SENDER", "office@example.com"))
    except payments.CheckoutNotPayable as err:
        raise HTTPException(409, str(err)) from err
    status = mail.send(message)
    said = "is on its way" if status == "sent" else "will be sent by the office shortly"
    total = payments.total_spoken(checkout)
    return payments.PaymentLinkResult(status=status, total=total, message=f"The link to review and pay {total} {said}.")


@lru_cache
def routing() -> dict[str, object]:
    return handoff.load_policy()


@lru_cache
def handoffs() -> handoff.HandoffStore:
    return handoff.make_store()


@app.post("/v1/handoffs", operation_id="prepareHandoff", response_model=handoff.HandoffPrepared)
def prepare_handoff(
    body: handoff.HandoffRequest,
    at: datetime = Depends(now),
    policy: dict[str, object] = Depends(routing),
    store: handoff.HandoffStore = Depends(handoffs),
) -> handoff.HandoffPrepared:
    """Store the context for a person on the call desk, and return the transfer to make."""
    return handoff.prepare(policy, store, body, at)


@app.get("/v1/handoffs/{handoff_id}", operation_id="getHandoff")
def get_handoff(handoff_id: str, store: handoff.HandoffStore = Depends(handoffs)) -> dict[str, object]:
    """The call desk's screen pop: everything the agent learned, by handoff ID. Not granted to the agent."""
    record = store.get(handoff_id)
    if record is None:
        raise HTTPException(404, "No handoff with that ID.")
    return record
