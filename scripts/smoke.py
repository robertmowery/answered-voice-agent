"""Smoke-test the deployed Brightwater front desk before anyone dials it.

Usage:
    python scripts/smoke.py --project YOUR_PROJECT

Runs every case in evals/part1_smoke.yaml as its own session against the
api-smoke deployment and writes results/part1/smoke.json. Each case bills as
one CX Agent Studio session (8 cases, about $4 at $0.50 per session).

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google.api_core.client_options import ClientOptions  # noqa: E402
from google.cloud import ces_v1  # noqa: E402

from brightwater.config import load_app  # noqa: E402
from brightwater.deploy import app_name  # noqa: E402
from brightwater.smoke import load_cases, run_case  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--deployment", default="api-smoke")
    parser.add_argument("--cases", default=str(ROOT / "evals" / "part1_smoke.yaml"))
    parser.add_argument("--out", default=str(ROOT / "results" / "part1" / "smoke.json"))
    args = parser.parse_args()
    if not args.project:
        parser.error("set --project or GOOGLE_CLOUD_PROJECT")

    spec = load_app()
    app = app_name(args.project, spec)
    deployment = f"{app}/deployments/{args.deployment}"
    client = ces_v1.SessionServiceClient(client_options=ClientOptions(quota_project_id=args.project))

    outcomes = []
    for case in load_cases(Path(args.cases)):
        outcome = run_case(client, app, deployment, case, spec.time_zone)
        print(f"{'PASS' if outcome.passed else 'FAIL'} {outcome.id} ({outcome.seconds}s): {outcome.reply}")
        outcomes.append(outcome)

    latencies = [o.seconds for o in outcomes]
    summary = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "deployment": args.deployment,
        "sessions": len(outcomes),
        "passed": sum(o.passed for o in outcomes),
        "latency_seconds": {
            "median": round(statistics.median(latencies), 2),
            "max": max(latencies),
            "min": min(latencies),
        },
        "note": "Text sessions through runSession, timed from request to full reply. Not phone latency.",
        "cases": [asdict(o) for o in outcomes],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"{summary['passed']}/{summary['sessions']} passed; median {summary['latency_seconds']['median']}s")
    return 0 if summary["passed"] == summary["sessions"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
