"""After-hours tickets: validate, number, and publish as an event.

The tools API never writes to a spreadsheet or a CRM. It publishes a
ticket.created event to Pub/Sub and returns; the ticket worker owns the
writes. That keeps a slow or failing downstream system from ever holding a
caller on the line.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field, field_validator

log = logging.getLogger(__name__)

Urgency = Literal["emergency", "urgent", "routine"]


class TicketRequest(BaseModel):
    caller_name: str = Field(min_length=1, max_length=80)
    callback_number: str = Field(description="Digits as the caller confirmed them")
    service_address: str = Field(min_length=3, max_length=200, description="Street address or ZIP code")
    problem: str = Field(min_length=3, max_length=500)
    urgency: Urgency
    session_id: str | None = Field(default=None, description="Conversation ID, used to make retries idempotent")

    @field_validator("callback_number")
    @classmethod
    def _ten_digits(cls, value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) != 10:
            raise ValueError("callback_number must be a 10-digit US number")
        return f"+1{digits}"


class TicketCreated(BaseModel):
    ticket_id: str
    office_review_by: str
    message: str


class Publisher(Protocol):
    def publish(self, payload: dict[str, object]) -> None: ...


class PubSubPublisher:
    """Publishes to the tickets topic; ordering by ticket ID is not needed, retries are."""

    def __init__(self, project: str, topic: str) -> None:
        from google.cloud import pubsub_v1

        self._client = pubsub_v1.PublisherClient()
        self._topic = self._client.topic_path(project, topic)

    def publish(self, payload: dict[str, object]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self._client.publish(self._topic, data, event_type="ticket.created").result(timeout=10)


class LogPublisher:
    """Local runs and tests: the event goes to the log instead of Pub/Sub."""

    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    def publish(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)
        log.info("ticket.created %s", json.dumps(payload))


def make_publisher() -> Publisher:
    project, topic = os.environ.get("GOOGLE_CLOUD_PROJECT"), os.environ.get("TICKETS_TOPIC")
    return PubSubPublisher(project, topic) if project and topic else LogPublisher()


def ticket_id(request: TicketRequest, at: datetime) -> str:
    """Same caller, same problem, same conversation: same ID, so a retried tool call can't duplicate a ticket."""
    basis = "|".join([request.session_id or at.isoformat(), request.callback_number, request.problem.lower()])
    return f"BW-{at:%Y%m%d}-{hashlib.sha256(basis.encode()).hexdigest()[:6].upper()}"


def create(request: TicketRequest, at: datetime, office_review_by: str, publisher: Publisher) -> TicketCreated:
    tid = ticket_id(request, at)
    publisher.publish(
        {
            "type": "ticket.created",
            "ticket_id": tid,
            "created_at": at.isoformat(),
            "office_review_by": office_review_by,
            **request.model_dump(),
        }
    )
    return TicketCreated(
        ticket_id=tid,
        office_review_by=office_review_by,
        message=f"Ticket {tid} is in the office queue for {office_review_by}.",
    )
