"""Payment links: only for a payable checkout, only to the buyer on the order.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import pytest

from app import payments

CHECKOUT = {
    "id": "chk_1",
    "status": "requires_escalation",
    "continue_url": "https://ucp.example/pay/chk_1",
    "buyer": {"full_name": "Sam Rivera", "email": "sam@example.com"},
    "line_items": [
        {"quantity": 2, "item": {"title": "Furnace filter"}, "totals": [{"type": "subtotal", "amount": 7800}]}
    ],
    "totals": [{"type": "subtotal", "amount": 7800}, {"type": "total", "amount": 7800}],
}


def test_email_carries_the_link_and_the_total() -> None:
    body = payments.render(CHECKOUT, "SAM@example.com", "office@example.com").get_content()
    assert "https://ucp.example/pay/chk_1" in body and "Total: $78.00" in body


def test_no_link_for_a_checkout_that_cannot_be_paid() -> None:
    with pytest.raises(payments.CheckoutNotPayable):
        payments.render({**CHECKOUT, "status": "incomplete"}, "sam@example.com", "o@example.com")


def test_no_link_to_a_different_address() -> None:
    with pytest.raises(payments.CheckoutNotPayable, match="doesn't match"):
        payments.render(CHECKOUT, "someone.else@example.com", "o@example.com")
