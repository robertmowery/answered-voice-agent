"""Scripted multi-turn conversations against a deployment, with tool expectations.

Part 1's smoke test checks one reply. From Part 2 on, the interesting
behavior is what the agent *does*: which operations it calls, and whether it
ends the session with a transfer. Each case here is a short script of caller
turns, checked on the final reply and on the actions taken across the whole
conversation. One case is one session (one $0.50 CX Agent Studio session).

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
from google.protobuf.json_format import MessageToDict

from brightwater.smoke import _run_with_backoff


@dataclass(frozen=True)
class Script:
    id: str
    turns: list[str]
    must_include_any: list[list[str]] = field(default_factory=list)
    must_not_match: list[str] = field(default_factory=list)
    expect_tools: list[str] = field(default_factory=list)
    forbid_tools: list[str] = field(default_factory=list)
    expect_end_session: dict[str, Any] | None = None
    forbid_end_session: bool = False
    forbid_in_end_session: list[str] = field(default_factory=list)


@dataclass
class Turn:
    say: str
    reply: str
    seconds: float
    tools: list[str]
    end_session: dict[str, Any] | None
    spans: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Result:
    id: str
    turns: list[Turn]
    passed: bool
    failures: list[str]


def load_scripts(path: Path) -> list[Script]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        Script(
            id=c["id"],
            turns=list(c["turns"]),
            must_include_any=[list(g) for g in c.get("must_include_any", [])],
            must_not_match=list(c.get("must_not_match", [])),
            expect_tools=list(c.get("expect_tools", [])),
            forbid_tools=list(c.get("forbid_tools", [])),
            expect_end_session=c.get("expect_end_session"),
            forbid_end_session=bool(c.get("forbid_end_session", False)),
            forbid_in_end_session=[str(x) for x in c.get("forbid_in_end_session", [])],
        )
        for c in raw["cases"]
    ]


def _tool_name(call: Any) -> str:
    """A toolset operation reports as toolset_tool.tool_id; a plain tool by its resource name."""
    if call.toolset_tool and call.toolset_tool.tool_id:
        return str(call.toolset_tool.tool_id)
    return str(call.display_name or call.tool).rsplit("/", 1)[-1]


def spans(response: Any) -> list[dict[str, Any]]:
    """Where the time went in one turn: each LLM call, tool call and guardrail check, in order.

    The platform reports these in diagnostic_info.root_span; we keep name, seconds,
    and the few attributes that explain a result (tool name, guardrail outcome).
    """
    out: list[dict[str, Any]] = []
    for o in response.outputs:
        root = MessageToDict(o._pb).get("diagnosticInfo", {}).get("rootSpan")
        if not root:
            continue
        out.append({"name": "turn", "seconds": float(str(root.get("duration", "0s")).rstrip("s"))})
        for child in root.get("childSpans", []):
            attrs = child.get("attributes", {})
            wanted = ("name", "triggered", "reason", "error", "status", "input token count", "time to first chunk (ms)")
            keep = {k: v for k, v in attrs.items() if k in wanted}
            out.append(
                {"name": child.get("name"), "seconds": float(str(child.get("duration", "0s")).rstrip("s")), **keep}
            )
    return out


def actions(response: Any) -> tuple[str, list[str], dict[str, Any] | None]:
    """Reply text, tool names called, and end_session metadata from one turn's outputs."""
    texts, tools, ended = [], [], None
    for out in response.outputs:
        if out.text:
            texts.append(out.text)
        for call in out.tool_calls.tool_calls:
            tools.append(_tool_name(call))
        if "end_session" in out and out.end_session:
            ended = MessageToDict(out.end_session._pb).get("metadata", {})
        diag = MessageToDict(out._pb).get("diagnosticInfo", {})
        for message in diag.get("messages", []):
            for chunk in message.get("chunks", []):
                call = chunk.get("toolCall")
                if call:
                    tools.append((call.get("toolsetTool") or {}).get("toolId") or call.get("displayName", "?"))
    return " ".join(texts).strip(), tools, ended


def _contains(actual: dict[str, Any], wanted: dict[str, Any]) -> bool:
    for key, value in wanted.items():
        if key not in actual:
            return False
        if isinstance(value, dict):
            if not isinstance(actual[key], dict) or not _contains(actual[key], value):
                return False
        elif value != "*" and actual[key] != value:
            return False
    return True


def score(script: Script, turns: list[Turn]) -> list[str]:
    failures = []
    final = turns[-1].reply if turns else ""
    for group in script.must_include_any:
        if not any(word.lower() in final.lower() for word in group):
            failures.append(f"final reply missing any of {group}")
    for pattern in script.must_not_match:
        for t in turns:
            if re.search(pattern, t.reply, flags=re.IGNORECASE):
                failures.append(f"a reply matched forbidden pattern {pattern!r}")
                break
    called = {name for t in turns for name in t.tools}
    for tool in script.expect_tools:
        if tool not in called:
            failures.append(f"never called {tool}")
    for tool in script.forbid_tools:
        if tool in called:
            failures.append(f"called forbidden tool {tool}")
    ended = next((t.end_session for t in turns if t.end_session is not None), None)
    if script.expect_end_session is not None and (ended is None or not _contains(ended, script.expect_end_session)):
        failures.append(f"end_session {ended!r} did not contain {script.expect_end_session!r}")
    if script.forbid_end_session and ended is not None:
        failures.append(f"ended the session unexpectedly: {ended!r}")
    for value in script.forbid_in_end_session:
        if ended is not None and value in str(ended):
            failures.append(f"end_session carried {value!r}")
    failures.extend(handoff_failures(turns))
    return failures


def handoff_failures(turns: list[Turn]) -> list[str]:
    """Checks every warm hand-off, whatever the script says: the caller is told before the
    transfer, and the SIP headers arrive as a map with the hand-off ID (Part 5 found both broken)."""
    failures = []
    for t in turns:
        params = (t.end_session or {}).get("params") or {}
        handoff = params.get("liveAgentHandoff")
        if handoff is None:
            continue
        if not t.reply.strip():
            failures.append("transferred to a person without telling the caller")
        headers = handoff.get("xHeaders") if isinstance(handoff, dict) else None
        if not isinstance(headers, dict) or not headers.get("handoff-id"):
            failures.append(f"liveAgentHandoff.xHeaders is not a map with handoff-id: {headers!r}")
    return failures


def run_script(client: Any, app: str, deployment: str, script: Script, time_zone: str) -> Result:
    from google.cloud.ces_v1 import types

    session = f"{app}/sessions/eval-{script.id}-{uuid.uuid4().hex[:8]}"
    turns: list[Turn] = []
    for say in script.turns:
        request = types.RunSessionRequest(
            config=types.SessionConfig(session=session, deployment=deployment, time_zone=time_zone),
            inputs=[types.SessionInput(text=say)],
        )
        response, seconds = _run_with_backoff(client, request)
        reply, tools, ended = actions(response)
        turns.append(Turn(say, reply, seconds, tools, ended, spans(response)))
        if ended is not None:
            break
        time.sleep(1)
    failures = score(script, turns)
    return Result(script.id, turns, not failures, failures)
