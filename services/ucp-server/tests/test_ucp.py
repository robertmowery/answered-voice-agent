"""UCP server: discovery, server-side pricing, limits, buyer handoff, idempotency.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.store import MemoryStore


@pytest.fixture()
def client():  # type: ignore[no-untyped-def]
    db = MemoryStore()
    main.app.dependency_overrides[main.store] = lambda: db
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


ORDER = {
    "line_items": [{"item": {"id": "filter-16x25x4-merv11"}, "quantity": 2}],
    "buyer": {"full_name": "Sam Rivera", "email": "sam@example.com"},
    "currency": "USD",
}


def test_manifest_declares_checkout_and_a_payment_handler(client) -> None:  # type: ignore[no-untyped-def]
    m = client.get("/.well-known/ucp").json()
    assert m["ucp"]["version"] == "2026-01-11"
    assert "dev.ucp.shopping" in m["ucp"]["services"]
    assert [c["name"] for c in m["ucp"]["capabilities"]] == ["dev.ucp.shopping.checkout"]
    assert m["payment"]["handlers"][0]["id"] == "mock_payment_handler"


def test_agent_checkout_hands_payment_to_the_buyer(client) -> None:  # type: ignore[no-untyped-def]
    s = client.post("/checkout-sessions", json=ORDER, headers={"UCP-Agent": "brightwater-commerce"}).json()
    assert s["status"] == "requires_escalation"
    assert s["continue_url"].endswith(f"/pay/{s['id']}")
    assert s["totals"][-1] == {"type": "total", "amount": 7800}


def test_prices_come_from_the_catalog_not_the_request(client) -> None:  # type: ignore[no-untyped-def]
    order = {**ORDER, "line_items": [{"item": {"id": "filter-16x25x4-merv11", "price": 1}, "quantity": 1}]}
    s = client.post("/checkout-sessions", json=order).json()
    assert s["totals"][-1]["amount"] == 3900


def test_limits_hold_the_order_for_a_person(client) -> None:  # type: ignore[no-untyped-def]
    big = {**ORDER, "line_items": [{"item": {"id": "maintenance-plan-annual"}, "quantity": 3}]}
    s = client.post("/checkout-sessions", json=big).json()
    assert s["status"] == "incomplete" and "continue_url" not in s
    assert s["messages"][0]["code"] == "limit_exceeded"
    many = {**ORDER, "line_items": [{"item": {"id": "filter-16x25x4-merv11"}, "quantity": 20}]}
    assert client.post("/checkout-sessions", json=many).json()["messages"][0]["code"] == "limit_exceeded"


def test_no_email_means_no_handoff(client) -> None:  # type: ignore[no-untyped-def]
    s = client.post("/checkout-sessions", json={**ORDER, "buyer": {"full_name": "Sam"}}).json()
    assert s["status"] == "incomplete"
    fixed = client.put(f"/checkout-sessions/{s['id']}", json={"buyer": {"full_name": "Sam", "email": "s@example.com"}})
    assert fixed.json()["status"] == "requires_escalation"


def test_idempotency_key_returns_the_same_checkout(client) -> None:  # type: ignore[no-untyped-def]
    a = client.post("/checkout-sessions", json=ORDER, headers={"idempotency-key": "k1"}).json()
    b = client.post("/checkout-sessions", json=ORDER, headers={"idempotency-key": "k1"}).json()
    assert a["id"] == b["id"]


def test_buyer_pays_once_on_the_page(client) -> None:  # type: ignore[no-untyped-def]
    s = client.post("/checkout-sessions", json=ORDER).json()
    page = client.get(f"/pay/{s['id']}").text
    assert "Pay $78.00 (test mode, no charge)" in page
    client.post(f"/pay/{s['id']}")
    done = client.get(f"/checkout-sessions/{s['id']}").json()
    assert done["status"] == "completed" and done["order"]["id"].startswith("ord_")
    again = client.post(
        f"/checkout-sessions/{s['id']}/complete",
        json={"payment": {"instruments": [{"handler_id": "mock_payment_handler"}]}},
    )
    assert again.json()["order"] == done["order"]


def test_catalog_search_understands_how_callers_talk(client) -> None:  # type: ignore[no-untyped-def]
    ids = [
        i["id"] for i in client.get("/catalog", params={"q": "replacement bulb for my air scrubber"}).json()["items"]
    ]
    assert ids == ["uv-lamp-replacement"]
