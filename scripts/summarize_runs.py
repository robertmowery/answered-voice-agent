"""Summarize conversation-eval result files: pass rate, guardrail fallbacks, and where the time went.

Usage: python scripts/summarize_runs.py results/part2/*.json --out results/part2/summary.json

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

FALLBACK = "I can't promise a time or a price over the phone"


def med(values: list[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def summarize(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    turns = [t for c in data["cases"] for t in c["turns"]]
    tool_turns = [t for t in turns if t["tools"]]
    plain_turns = [t for t in turns if not t["tools"]]
    by_span: dict[str, list[float]] = {}
    triggered = 0
    for t in turns:
        for s in t.get("spans", []):
            by_span.setdefault(s["name"], []).append(s["seconds"])
            if s.get("triggered"):
                triggered += 1
    return {
        "file": path.name,
        "at": data["at"],
        "sessions": data["sessions"],
        "passed": data["passed"],
        "turns": len(turns),
        "fallback_replies": sum(1 for t in turns if t["reply"].startswith(FALLBACK)),
        "guardrail_triggered_spans": triggered,
        "guardrail_timeouts": sum(
            1 for t in turns for s in t.get("spans", []) if "timeout" in str(s.get("reason", "")).lower()
        ),
        "model_deadline_exceeded": sum(
            1 for t in turns for s in t.get("spans", []) if s.get("error") == "DEADLINE_EXCEEDED"
        ),
        "median_turn_seconds": med([t["seconds"] for t in turns]),
        "median_tool_turn_seconds": med([t["seconds"] for t in tool_turns]),
        "median_plain_turn_seconds": med([t["seconds"] for t in plain_turns]),
        "max_turn_seconds": max((t["seconds"] for t in turns), default=None),
        "median_span_seconds": {k: med(v) for k, v in by_span.items()},
        "span_counts": {k: len(v) for k, v in by_span.items()},
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("files", nargs="+")
    p.add_argument("--out")
    a = p.parse_args()
    out = [summarize(Path(f)) for f in sorted(a.files) if not f.endswith("summary.json")]
    text = json.dumps(out, indent=2)
    print(text)
    if a.out:
        Path(a.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
