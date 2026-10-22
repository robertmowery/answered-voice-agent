"""Brightwater's Universal Commerce Protocol (UCP) business server.

Implements the parts of UCP 2026-01-11 an agent needs to sell parts and plans
over the phone:

- discovery at /.well-known/ucp (services, the checkout capability, payment handlers);
- checkout sessions: create, get, update, complete, cancel;
- a buyer handoff: the agent never collects payment. A checkout created by an
  agent moves to requires_escalation with a continue_url, a page where the
  buyer reviews the order and pays. Completion happens there, with the buyer's
  own action as the consent.

Catalog search (/catalog) is a Brightwater extension, not part of UCP.
Payment uses a mock handler: no money moves. Swap in a real handler (Google
Pay, a PSP) by adding it to the manifest and to complete().

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import os
import uuid
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.store import MemoryStore, Store, make_store

UCP_VERSION = "2026-01-11"
SPEC = "https://ucp.dev/specs/shopping"
POLICY = Path(__file__).resolve().parent.parent / "policy" / "catalog.yaml"

app = FastAPI(title="Brightwater UCP server", version=UCP_VERSION)


@lru_cache
def catalog() -> dict[str, Any]:
    return dict(yaml.safe_load(POLICY.read_text(encoding="utf-8")))


@lru_cache
def store() -> Store:
    return make_store()


def base_url(request: Request) -> str:
    return os.environ.get("PUBLIC_BASE_URL") or str(request.base_url).rstrip("/")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/.well-known/ucp")
def manifest(request: Request) -> dict[str, Any]:
    base = base_url(request)
    return {
        "ucp": {
            "version": UCP_VERSION,
            "services": {
                "dev.ucp.shopping": {
                    "version": UCP_VERSION,
                    "spec": SPEC,
                    "rest": {"schema": "https://ucp.dev/services/shopping/openapi.json", "endpoint": base},
                }
            },
            "capabilities": [
                {
                    "name": "dev.ucp.shopping.checkout",
                    "version": UCP_VERSION,
                    "spec": f"{SPEC}/checkout",
                    "schema": "https://ucp.dev/schemas/shopping/checkout.json",
                }
            ],
        },
        "payment": {
            "handlers": [
                {
                    "id": "mock_payment_handler",
                    "name": "dev.brightwater.mock_payment",
                    "version": UCP_VERSION,
                    "spec": f"{base}/docs",
                    "config_schema": {},
                    "instrument_schemas": [],
                    "config": {"test_mode": True},
                }
            ]
        },
    }


@app.get("/catalog")
def search_catalog(q: str = "") -> dict[str, Any]:
    """Brightwater extension: find items by plain words, the way a caller describes them."""
    words = {w.strip(".,?!") for w in q.lower().split() if len(w) > 3}
    items = catalog()["items"]

    def score(item: dict[str, Any]) -> int:
        text = " ".join([item["title"].lower(), *item["keywords"]])
        return sum(1 for w in words if w in text)

    if not words:
        hits = items
    else:
        best = max((score(i) for i in items), default=0)
        hits = [i for i in items if best and score(i) == best]
    return {"items": [{"id": i["id"], "title": i["title"], "price": i["price"]} for i in hits]}


def _totals(line_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    subtotal = sum(li["totals"][0]["amount"] for li in line_items)
    return [{"type": "subtotal", "amount": subtotal}, {"type": "total", "amount": subtotal}]


def _build_lines(requested: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Price every line from the catalog (never from the request) and enforce the agent limits."""
    by_id = {i["id"]: i for i in catalog()["items"]}
    limits = catalog()["limits"]
    lines, messages = [], []
    for n, li in enumerate(requested):
        item_id = li.get("item", {}).get("id")
        qty = int(li.get("quantity", 1))
        if item_id not in by_id:
            messages.append(_error("unknown_item", f"$.line_items[{n}].item.id", f"No item {item_id!r}."))
            continue
        if not 1 <= qty <= limits["max_quantity_per_item"]:
            messages.append(
                _error(
                    "limit_exceeded",
                    f"$.line_items[{n}].quantity",
                    f"Quantity must be 1 to {limits['max_quantity_per_item']}.",
                )
            )
            continue
        item = by_id[item_id]
        lines.append(
            {
                "id": li.get("id") or f"li_{n + 1}",
                "item": {"id": item["id"], "title": item["title"], "price": item["price"]},
                "quantity": qty,
                "totals": [{"type": "subtotal", "amount": item["price"] * qty}],
            }
        )
    if lines and _totals(lines)[-1]["amount"] > limits["max_order_total"]:
        messages.append(
            _error(
                "limit_exceeded", "$.line_items", f"Orders over ${limits['max_order_total'] / 100:,.2f} need a person."
            )
        )
    return lines, messages


def _error(code: str, path: str, content: str) -> dict[str, Any]:
    return {
        "type": "error",
        "code": code,
        "path": path,
        "content_type": "plain",
        "content": content,
        "severity": "recoverable",
    }


def _status(lines: list[dict[str, Any]], messages: list[dict[str, Any]], buyer: dict[str, Any] | None) -> str:
    if messages or not lines or not (buyer and buyer.get("email")):
        return "incomplete"
    # An agent can't hold the buyer's consent to pay; the buyer finishes on the merchant page.
    return "requires_escalation"


def _session(
    checkout_id: str,
    lines: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    buyer: dict[str, Any] | None,
    base: str,
) -> dict[str, Any]:
    status = _status(lines, messages, buyer)
    session: dict[str, Any] = {
        "ucp": {
            "version": UCP_VERSION,
            "capabilities": [{"name": "dev.ucp.shopping.checkout", "version": UCP_VERSION}],
        },
        "id": checkout_id,
        "status": status,
        "currency": catalog()["currency"],
        "line_items": lines,
        "buyer": buyer or {},
        "totals": _totals(lines) if lines else [{"type": "total", "amount": 0}],
        "links": [{"type": "terms_of_service", "url": f"{base}/terms"}],
        "payment": {"handlers": manifest_handlers(base), "instruments": []},
        "messages": messages,
    }
    if status == "requires_escalation":
        session["continue_url"] = f"{base}/pay/{checkout_id}"
        session["messages"] = [
            {
                "type": "info",
                "code": "buyer_payment_required",
                "path": "$.payment",
                "content_type": "plain",
                "content": "The buyer reviews the order and pays at continue_url.",
            }
        ]
    return session


def manifest_handlers(base: str) -> list[dict[str, Any]]:
    return [
        {"id": "mock_payment_handler", "name": "dev.brightwater.mock_payment", "version": UCP_VERSION, "config": {}}
    ]


@app.post("/checkout-sessions", status_code=201)
def create_checkout(
    body: dict[str, Any],
    request: Request,
    ucp_agent: str | None = Header(default=None, alias="UCP-Agent"),
    idempotency_key: str | None = Header(default=None, alias="idempotency-key"),
    db: Store = Depends(store),
) -> dict[str, Any]:
    if idempotency_key and (existing := db.by_idempotency_key(idempotency_key)):
        return existing
    lines, messages = _build_lines(body.get("line_items", []))
    session = _session(f"chk_{uuid.uuid4().hex[:16]}", lines, messages, body.get("buyer"), base_url(request))
    session["_agent"] = ucp_agent or "unknown"
    db.put(session, idempotency_key)
    return public(session)


def public(session: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in session.items() if not k.startswith("_")}


def _load(db: Store, checkout_id: str) -> dict[str, Any]:
    session = db.get(checkout_id)
    if session is None:
        raise HTTPException(404, "No such checkout")
    return session


@app.get("/checkout-sessions/{checkout_id}")
def get_checkout(checkout_id: str, db: Store = Depends(store)) -> dict[str, Any]:
    return public(_load(db, checkout_id))


@app.put("/checkout-sessions/{checkout_id}")
def update_checkout(
    checkout_id: str, body: dict[str, Any], request: Request, db: Store = Depends(store)
) -> dict[str, Any]:
    current = _load(db, checkout_id)
    if current["status"] in {"completed", "canceled", "complete_in_progress"}:
        raise HTTPException(409, f"Checkout is {current['status']}")
    requested = body.get("line_items") or [
        {"item": {"id": li["item"]["id"]}, "quantity": li["quantity"]} for li in current["line_items"]
    ]
    lines, messages = _build_lines(requested)
    session = _session(checkout_id, lines, messages, body.get("buyer") or current["buyer"], base_url(request))
    session["_agent"] = current.get("_agent")
    db.put(session)
    return public(session)


@app.post("/checkout-sessions/{checkout_id}/complete")
def complete_checkout(checkout_id: str, body: dict[str, Any], db: Store = Depends(store)) -> dict[str, Any]:
    session = _load(db, checkout_id)
    if session["status"] == "completed":
        return public(session)  # completing twice is not paying twice
    if session["status"] not in {"ready_for_complete", "requires_escalation"}:
        raise HTTPException(409, f"Checkout is {session['status']}")
    instrument = (body.get("payment") or {}).get("instruments", [{}])[0]
    if instrument.get("handler_id") != "mock_payment_handler":
        raise HTTPException(422, "Unsupported payment handler")
    session.update(status="completed", order={"id": f"ord_{checkout_id[4:]}"}, messages=[])
    session.pop("continue_url", None)
    db.put(session)
    return public(session)


@app.post("/checkout-sessions/{checkout_id}/cancel")
def cancel_checkout(checkout_id: str, db: Store = Depends(store)) -> dict[str, Any]:
    session = _load(db, checkout_id)
    if session["status"] == "completed":
        raise HTTPException(409, "Checkout is completed")
    session.update(status="canceled")
    session.pop("continue_url", None)
    db.put(session)
    return public(session)


@app.get("/pay/{checkout_id}", response_class=HTMLResponse)
def pay_page(checkout_id: str, db: Store = Depends(store)) -> str:
    """The buyer's page: the whole order, the total, and one button. Test mode: no money moves."""
    s = _load(db, checkout_id)
    rows = "".join(
        f"<tr><td>{escape(li['item']['title'])}</td><td>{li['quantity']}</td>"
        f"<td>${li['totals'][0]['amount'] / 100:,.2f}</td></tr>"
        for li in s["line_items"]
    )
    total = s["totals"][-1]["amount"] / 100
    if s["status"] == "completed":
        action = f"<p>Paid. Order {escape(s['order']['id'])}. Thank you.</p>"
    elif s["status"] == "requires_escalation":
        action = (
            f'<form method="post" action="/pay/{escape(checkout_id)}">'
            f'<button type="submit">Pay ${total:,.2f} (test mode, no charge)</button></form>'
        )
    else:
        action = f"<p>This order is {escape(s['status'])}.</p>"
    return (
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        "<title>Brightwater order</title>"
        "<body style='font-family:sans-serif;max-width:32rem;margin:2rem auto;padding:0 1rem'>"
        "<h1>Review your Brightwater order</h1>"
        "<p>Brightwater Home Services is a fictional company. This page is a demo.</p>"
        f"<table cellpadding=6>{rows}<tr><th align=left>Total</th><td></td><th>${total:,.2f}</th></tr></table>{action}"
    )


@app.post("/pay/{checkout_id}", response_class=HTMLResponse)
def pay(checkout_id: str, db: Store = Depends(store)) -> str:
    complete_checkout(checkout_id, {"payment": {"instruments": [{"handler_id": "mock_payment_handler"}]}}, db)
    return pay_page(checkout_id, db)


__all__ = ["app", "MemoryStore"]
