"""The executive numbers from every recorded conversation: containment, supervision ratio, cost per call.

Usage: python scripts/cost_report.py [--infra-usd X] --out results/part7/cost_report.json

Reads every conversation result file under results/ (the files run_evals.py
writes), classifies how each conversation ended, and prices it:

- resolved by the agent: answered, booked, ordered (payment link sent), or told
  the caller exactly what happens next without needing a person;
- handed to a person: a transfer to the on-call technician, a warm hand-off
  to the call desk, or a ticket the office must work;
- failed: the caller heard a fallback line, or the conversation ended unresolved.

The CX Agent Studio price is a dated constant from Google's pricing page.
Infrastructure (Cloud Run, Firestore, Pub/Sub, Vertex AI for the commerce
agent) comes from the bill, passed in with --infra-usd once it posts.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SESSION_USD = 0.50  # CX Agent Studio, chat or voice, pay as you go; pricing page checked 2026-10-14
VOICE_OVERAGE_USD_PER_SECOND = 0.0025  # after 300 seconds of a voice session
HUMAN_TOOLS = {"createTicket", "prepareHandoff"}
FALLBACKS = (
    "I can't promise a time or a price over the phone",
    "I'm having trouble with that",
    "Hmm, I'm having trouble",
)


def outcome(case: dict[str, Any]) -> str:
    turns = case["turns"]
    tools = {t for turn in turns for t in turn["tools"]}
    ended = next((t["end_session"] for t in turns if t.get("end_session")), None)
    if any(turn["reply"].startswith(FALLBACKS) for turn in turns[-1:]):
        return "failed"
    if ended and ("telephonyTransferCall" in json.dumps(ended) or "liveAgentHandoff" in json.dumps(ended)):
        return "handed_to_person"
    if tools & HUMAN_TOOLS:
        return "handed_to_person"
    return "resolved_by_agent"


def collect(results_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(results_dir.glob("part*/*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or "cases" not in data or "turns" not in data:
            continue
        for case in data["cases"]:
            if "turns" not in case:
                continue
            rows.append({"file": f"{path.parent.name}/{path.name}", "id": case["id"], "outcome": outcome(case)})
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--results", default=str(ROOT / "results"))
    p.add_argument("--infra-usd", type=float, default=None, help="infrastructure spend from the bill, if posted")
    p.add_argument("--final-only", action="store_true", help="only each part's final run (files without _run)")
    p.add_argument("--out")
    a = p.parse_args()
    rows = collect(Path(a.results))
    if a.final_only:
        rows = [r for r in rows if "_run" not in r["file"] and "before" not in r["file"]]
    counts = Counter(r["outcome"] for r in rows)
    total = len(rows)
    sessions_usd = total * SESSION_USD
    report = {
        "conversations": total,
        "outcomes": dict(counts),
        "containment": round(counts["resolved_by_agent"] / total, 3) if total else None,
        "supervision_ratio": round(counts["handed_to_person"] / total, 3) if total else None,
        "failure_rate": round(counts["failed"] / total, 3) if total else None,
        "session_price_usd": SESSION_USD,
        "sessions_usd": round(sessions_usd, 2),
        "infra_usd": a.infra_usd,
        "cost_per_conversation_usd": round((sessions_usd + (a.infra_usd or 0)) / total, 3) if total else None,
        "cost_per_resolved_conversation_usd": (
            round((sessions_usd + (a.infra_usd or 0)) / counts["resolved_by_agent"], 3)
            if counts["resolved_by_agent"]
            else None
        ),
        "note": "Text sessions over the API; voice calls under five minutes price the same per session.",
        "rows": rows,
    }
    text = json.dumps(report, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
