"""Send the buyer the link to review and pay for a UCP checkout.

The commerce agent creates the checkout; it never sees a card. This module
reads the checkout from Brightwater's UCP server, and emails its continue_url
from the office's business email, with the items and total from the checkout
itself. The link only works for a checkout in requires_escalation, which is
the state an agent-created checkout waits in until the buyer acts.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import os
from email.message import EmailMessage
from typing import Any

import httpx
from pydantic import BaseModel

UCP_SERVER_URL = os.environ.get("UCP_SERVER_URL", "http://localhost:8081")


class PaymentLinkRequest(BaseModel):
    checkout_id: str
    email: str


class PaymentLinkResult(BaseModel):
    status: str
    total: str
    message: str


class CheckoutNotPayable(Exception):
    pass


def fetch_checkout(checkout_id: str, client: httpx.Client | None = None) -> dict[str, Any]:
    c = client or httpx.Client(base_url=UCP_SERVER_URL, timeout=10, headers={"UCP-Agent": "brightwater-tools-api/1.0"})
    r = c.get(f"/checkout-sessions/{checkout_id}")
    if r.status_code == 404:
        raise CheckoutNotPayable("No checkout with that ID.")
    return dict(r.raise_for_status().json())


def render(checkout: dict[str, Any], to: str, sender: str) -> EmailMessage:
    if checkout.get("status") != "requires_escalation" or not checkout.get("continue_url"):
        raise CheckoutNotPayable(f"Checkout is {checkout.get('status')}; there is nothing to pay yet.")
    if checkout.get("buyer", {}).get("email", "").lower() != to.lower():
        raise CheckoutNotPayable("That email doesn't match the one on the order.")
    lines = "\n".join(
        f"  {li['quantity']} x {li['item']['title']}: ${li['totals'][0]['amount'] / 100:,.2f}"
        for li in checkout["line_items"]
    )
    total = checkout["totals"][-1]["amount"] / 100
    msg = EmailMessage()
    msg["From"] = f"Brightwater Home Services <{sender}>"
    msg["To"] = to
    msg["Subject"] = "Review and pay for your Brightwater order"
    msg.set_content(
        f"Here's the order you placed by phone:\n\n{lines}\n\n  Total: ${total:,.2f}\n\n"
        f"Review it and pay here: {checkout['continue_url']}\n\n"
        "Nothing is charged until you pay on that page. If anything looks wrong, reply to this email.\n\n"
        "Brightwater Home Services (a fictional company)\n"
    )
    return msg


def total_spoken(checkout: dict[str, Any]) -> str:
    return f"${checkout['totals'][-1]['amount'] / 100:,.2f}"
