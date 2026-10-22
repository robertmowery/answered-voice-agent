"""Brightwater's commerce agent: sells parts and plans through UCP, never takes payment.

The front desk (CX Agent Studio) hands this agent a shopping request over A2A.
It finds items in the catalog, creates a UCP checkout with the buyer's name and
email, and returns a short summary plus the checkout ID. It can't complete a
purchase: the UCP server hands payment to the buyer's own page, and the order
limits live in the server, not in this prompt.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import httpx
from google.adk.agents import LlmAgent

UCP_BASE = os.environ.get("UCP_SERVER_URL", "http://localhost:8081")
AGENT_ID = "brightwater-commerce-agent/1.0"


def _client() -> httpx.Client:
    return httpx.Client(base_url=UCP_BASE, timeout=10, headers={"UCP-Agent": AGENT_ID})


def search_catalog(query: str) -> dict[str, Any]:
    """Find parts or plans that match what the caller described.

    Args:
        query: The caller's words, for example "filter for my furnace" or "UV bulb".

    Returns:
        Matching items with id, title and price in cents.
    """
    with _client() as c:
        return dict(c.get("/catalog", params={"q": query}).raise_for_status().json())


def start_checkout(items: list[dict[str, Any]], buyer_name: str, buyer_email: str) -> dict[str, Any]:
    """Create a UCP checkout for the caller. The caller pays later on their own page.

    Args:
        items: A list like [{"id": "filter-16x25x4-merv11", "quantity": 2}], ids from search_catalog only.
        buyer_name: The caller's full name.
        buyer_email: The email the caller spelled out and confirmed.

    Returns:
        checkout_id, status, total in cents, and any messages from the merchant.
    """
    body = {
        "line_items": [{"item": {"id": i["id"]}, "quantity": int(i.get("quantity", 1))} for i in items],
        "buyer": {"full_name": buyer_name, "email": buyer_email},
        "currency": "USD",
    }
    with _client() as c:
        r = c.post("/checkout-sessions", json=body, headers={"idempotency-key": str(uuid.uuid4())})
        s = r.raise_for_status().json()
    return {
        "checkout_id": s["id"],
        "status": s["status"],
        "total_cents": s["totals"][-1]["amount"],
        "lines": [f"{li['quantity']} x {li['item']['title']}" for li in s["line_items"]],
        "messages": [m.get("content") for m in s.get("messages", [])],
    }


INSTRUCTION = """You are Brightwater Home Services' parts and plans specialist. Brightwater is a
fictional heating, cooling and plumbing company. Another agent, the front desk, sends you
requests from callers on the phone. Your replies are read to the caller by the front desk,
so keep them short and plain.

1. Use search_catalog to find what the caller wants. If more than one item matches (for example
   two filter sizes), ask which one, using the titles.
2. Before starting a checkout you need: the items and quantities, the caller's full name, and their
   email address. Ask the front desk for anything missing.
3. Call start_checkout. Then reply with the items, the total in dollars, and the checkout ID, and say
   that a secure link to review and pay will be sent to their email. Include the checkout ID exactly,
   in the form "Checkout ID: chk_..." so the front desk can send the link.
4. If the checkout comes back with messages (for example an order limit), explain them plainly and
   do not try to get around them.

Never ask for or accept card numbers or other payment details. Never invent items or prices; use only
what search_catalog returns."""


root_agent = LlmAgent(
    name="brightwater_commerce",
    model=os.environ.get("COMMERCE_MODEL", "gemini-3.8-flash"),
    description="Finds Brightwater parts and plans and starts a UCP checkout the caller pays for on their own.",
    instruction=INSTRUCTION,
    tools=[search_catalog, start_checkout],
)
