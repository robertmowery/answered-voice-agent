"""Follow-up email after a booking, sent from the office's Google Workspace business email.

The agent never writes the email. It asks for one by booking ID, and this
module renders it from the calendar event, so the email can't say anything
the booking doesn't. Sending uses the Gmail API as the office mailbox through
domain-wide delegation, which a Workspace admin grants to one scope
(gmail.send) for this service account. Until that grant exists, emails go to
a Firestore outbox for a person to review and send, and the tool says so.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import base64
import os
import re
from email.message import EmailMessage
from typing import Any, Protocol

from pydantic import BaseModel, Field

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")


class FollowUpRequest(BaseModel):
    booking_id: str
    email: str = Field(description="The address the caller spelled out and confirmed")


class FollowUpResult(BaseModel):
    status: str  # "sent" or "queued_for_review"
    message: str


class Mailer(Protocol):
    def send(self, message: EmailMessage) -> str: ...


class GmailMailer:
    """Sends as SENDER through domain-wide delegation, scope gmail.send only."""

    def __init__(self, sender: str) -> None:
        self.sender = sender

    def send(self, message: EmailMessage) -> str:
        import google.auth
        from google.auth import iam
        from google.auth.transport import requests
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        source, _ = google.auth.default()
        email = getattr(source, "service_account_email", None)
        signer = iam.Signer(requests.Request(), source, email)
        creds = service_account.Credentials(
            signer,
            email,
            "https://oauth2.googleapis.com/token",
            scopes=["https://www.googleapis.com/auth/gmail.send"],
            subject=self.sender,
        )
        api = build("gmail", "v1", credentials=creds, cache_discovery=False)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        api.users().messages().send(userId="me", body={"raw": raw}).execute()
        return "sent"


class OutboxMailer:
    """No delegation yet: store the rendered email for a person to send."""

    def __init__(self) -> None:
        from google.cloud import firestore

        self._col = firestore.Client().collection("outbox")

    def send(self, message: EmailMessage) -> str:
        self._col.add({"to": message["To"], "subject": message["Subject"], "body": message.get_content()})
        return "queued_for_review"


class MemoryMailer:
    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> str:
        self.messages.append(message)
        return "queued_for_review"


def make_mailer() -> Mailer:
    sender = os.environ.get("FOLLOWUP_SENDER")
    if sender and os.environ.get("GMAIL_DELEGATION") == "on":
        return GmailMailer(sender)
    if os.environ.get("GOOGLE_CLOUD_PROJECT"):
        return OutboxMailer()
    return MemoryMailer()


def render(event: dict[str, Any], to: str, sender: str) -> EmailMessage:
    private = event.get("extendedProperties", {}).get("private", {})
    msg = EmailMessage()
    msg["From"] = f"Brightwater Home Services <{sender}>"
    msg["To"] = to
    msg["Subject"] = "Your Brightwater appointment"
    name = private.get("caller_name", "there").split()[0]
    msg.set_content(
        f"Hi {name},\n\n"
        f"You're booked for {event.get('_window', 'the window we discussed')} at {event.get('location', '')}.\n"
        f"Reason for the visit: {private.get('problem', '')}\n\n"
        "The technician calls about 30 minutes before arriving. To change or cancel, reply to this email "
        "or call us during office hours.\n\n"
        f"Booking reference: {event['id']}\n\n"
        "Brightwater Home Services (a fictional company)\n"
    )
    return msg
