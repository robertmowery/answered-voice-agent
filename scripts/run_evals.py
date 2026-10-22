"""Run scripted conversations against a deployment and record what the agent did.

Usage:
    python scripts/run_evals.py --project YOUR_PROJECT --cases evals/part2_routing.yaml \\
        --out results/part2/conversations.json

Each case is one CX Agent Studio session ($0.50). The file records every turn:
what the caller said, the reply, the seconds it took, the operations the agent
called, and any end_session parameters (a transfer), plus pass or fail.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "tools-api"))

from google.api_core.client_options import ClientOptions  # noqa: E402
from google.cloud import ces_v1  # noqa: E402

from app import hours  # noqa: E402
from brightwater.config import load_app  # noqa: E402
from brightwater.conversation import Script, load_scripts, run_script  # noqa: E402
from brightwater.deploy import app_name  # noqa: E402


def fill(script: Script, values: dict[str, str]) -> Script:
    """Replace {on_call_number} and friends in expectations with today's values from the policy."""
    if script.expect_end_session is None:
        return script
    text = json.dumps(script.expect_end_session)
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return replace(script, expect_end_session=json.loads(text))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--deployment", default="api-smoke")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", nargs="*", help="run only these case IDs")
    args = parser.parse_args()
    if not args.project:
        parser.error("set --project or GOOGLE_CLOUD_PROJECT")

    spec = load_app()
    app = app_name(args.project, spec)
    deployment = f"{app}/deployments/{args.deployment}"
    client = ces_v1.SessionServiceClient(client_options=ClientOptions(quota_project_id=args.project))
    now = datetime.now(UTC)
    status = hours.status(hours.load_schedule(), now)
    values = {"on_call_number": status.transfer_number}

    results = []
    for script in load_scripts(Path(args.cases)):
        if args.only and script.id not in args.only:
            continue
        result = run_script(client, app, deployment, fill(script, values), spec.time_zone)
        print(f"{'PASS' if result.passed else 'FAIL'} {result.id}: {result.failures or ''}")
        for t in result.turns:
            print(f"   caller: {t.say}\n   agent ({t.seconds}s, tools={t.tools}): {t.reply}")
            if t.end_session is not None:
                print(f"   end_session: {json.dumps(t.end_session)}")
        results.append(result)

    seconds = [t.seconds for r in results for t in r.turns]
    summary = {
        "at": now.isoformat(timespec="seconds"),
        "office_status_at_run": {"open": status.open, "reason": status.reason, "local_time": status.local_time},
        "deployment": args.deployment,
        "sessions": len(results),
        "turns": len(seconds),
        "passed": sum(r.passed for r in results),
        "turn_seconds": {
            "median": round(statistics.median(seconds), 2) if seconds else None,
            "max": max(seconds, default=None),
            "min": min(seconds, default=None),
        },
        "note": "Text sessions through runSession; each turn timed from request to full reply, tool calls included.",
        "cases": [asdict(r) for r in results],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2).replace(args.project, "PROJECT") + "\n", encoding="utf-8")
    print(f"{summary['passed']}/{summary['sessions']} passed; median turn {summary['turn_seconds']['median']}s")
    return 0 if summary["passed"] == summary["sessions"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
