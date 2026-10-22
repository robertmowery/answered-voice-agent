"""Run scripted one-turn conversations against a deployment and score the replies.

The scoring is plain string checks, defined in evals/part1_smoke.yaml, so a
reader can see exactly why a case passed or failed. Fuller evaluations, with
CX Agent Studio's own evaluation service, arrive in Part 7.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Case:
    id: str
    say: str
    must_include_any: list[list[str]] = field(default_factory=list)
    must_not_match: list[str] = field(default_factory=list)


@dataclass
class Outcome:
    id: str
    say: str
    reply: str
    seconds: float
    passed: bool
    failures: list[str]


def load_cases(path: Path) -> list[Case]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        Case(
            id=c["id"],
            say=c["say"],
            must_include_any=[list(g) for g in c.get("must_include_any", [])],
            must_not_match=list(c.get("must_not_match", [])),
        )
        for c in raw["cases"]
    ]


def score(case: Case, reply: str) -> list[str]:
    """Return the reasons a reply fails its case; an empty list means it passed."""
    failures = []
    lowered = reply.lower()
    for group in case.must_include_any:
        if not any(word.lower() in lowered for word in group):
            failures.append(f"missing any of {group}")
    for pattern in case.must_not_match:
        if re.search(pattern, reply, flags=re.IGNORECASE):
            failures.append(f"matched forbidden pattern {pattern!r}")
    return failures


def reply_text(response: Any) -> str:
    """Join the text the agent said across every output of one turn."""
    return " ".join(o.text for o in response.outputs if o.text).strip()


def _run_with_backoff(client: Any, request: Any, attempts: int = 4, wait_seconds: float = 65.0) -> tuple[Any, float]:
    """Call runSession, waiting out per-minute quota (HTTP 429) instead of failing.

    A new project allows 1,000 LLM tokens per minute per model by default, which
    is about one Brightwater turn. A rejected 429 call is not billed, so waiting
    a minute and retrying costs nothing but time. The timing excludes the wait.
    """
    from google.api_core import exceptions
    from google.api_core.retry import Retry

    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            response = client.run_session(request=request, retry=Retry(predicate=lambda e: False))
            return response, round(time.monotonic() - started, 2)
        except exceptions.ResourceExhausted:
            if attempt == attempts:
                raise
            time.sleep(wait_seconds)
    raise RuntimeError("unreachable")


def run_case(client: Any, app: str, deployment: str, case: Case, time_zone: str) -> Outcome:
    """One fresh session, one user turn, timed from request to full reply."""
    from google.cloud.ces_v1 import types

    session = f"{app}/sessions/smoke-{case.id}-{uuid.uuid4().hex[:8]}"
    request = types.RunSessionRequest(
        config=types.SessionConfig(session=session, deployment=deployment, time_zone=time_zone),
        inputs=[types.SessionInput(text=case.say)],
    )
    response, seconds = _run_with_backoff(client, request)
    reply = reply_text(response)
    failures = score(case, reply)
    return Outcome(case.id, case.say, reply, seconds, not failures, failures)
