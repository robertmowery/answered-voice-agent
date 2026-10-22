"""Commerce agent tools against the real UCP server app, in process. No model calls.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

UCP_DIR = Path(__file__).resolve().parents[2] / "ucp-server"


@pytest.fixture()
def tools(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    saved = {k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, str(UCP_DIR))
    ucp_main = importlib.import_module("app.main")
    ucp_store = importlib.import_module("app.store")
    db = ucp_store.MemoryStore()
    ucp_main.app.dependency_overrides[ucp_main.store] = lambda: db
    ucp = TestClient(ucp_main.app, headers={"UCP-Agent": "test"})
    sys.path.remove(str(UCP_DIR))
    for k in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
        del sys.modules[k]
    sys.modules.update(saved)
    agent = importlib.import_module("app.agent")
    monkeypatch.setattr(agent, "_client", lambda: ucp)
    yield agent


def test_search_then_checkout_returns_an_id_and_a_total(tools) -> None:  # type: ignore[no-untyped-def]
    found = tools.search_catalog("humidifier water panel")["items"]
    assert [i["id"] for i in found] == ["humidifier-water-panel"]
    result = tools.start_checkout([{"id": found[0]["id"], "quantity": 2}], "Sam Rivera", "sam@example.com")
    assert result["checkout_id"].startswith("chk_")
    assert result["status"] == "requires_escalation"
    assert result["total_cents"] == 5800


def test_limits_come_back_as_messages(tools) -> None:  # type: ignore[no-untyped-def]
    result = tools.start_checkout([{"id": "maintenance-plan-annual", "quantity": 3}], "Sam", "sam@example.com")
    assert result["status"] == "incomplete"
    assert any("need a person" in m for m in result["messages"])
