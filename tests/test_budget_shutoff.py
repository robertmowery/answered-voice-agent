"""The shutoff decides only on the numbers in the alert.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

MAIN = Path(__file__).resolve().parent.parent / "infra" / "functions" / "budget_shutoff" / "main.py"


@pytest.fixture(scope="module")
def shutoff():  # type: ignore[no-untyped-def]
    # functions_framework only matters at deploy time; stub its decorator here.
    stub = types.ModuleType("functions_framework")
    stub.cloud_event = lambda f: f  # type: ignore[attr-defined]
    sys.modules.setdefault("functions_framework", stub)
    spec = importlib.util.spec_from_file_location("budget_shutoff_main", MAIN)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.mark.parametrize(
    ("cost", "budget", "expected"),
    [(10.0, 40.0, False), (39.99, 40.0, False), (40.0, 40.0, True), (55.0, 40.0, True), (5.0, 0.0, False)],
)
def test_should_shut_off(shutoff, cost: float, budget: float, expected: bool) -> None:  # type: ignore[no-untyped-def]
    assert shutoff.should_shut_off({"costAmount": cost, "budgetAmount": budget}) is expected
