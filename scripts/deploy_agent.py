"""Deploy the Brightwater app from agent/ to CX Agent Studio.

Usage:
    python scripts/deploy_agent.py --project YOUR_PROJECT [--label part1]

Reads agent/app.yaml, creates or updates the app, its agents and guardrails,
snapshots a version, points each deployment at it, and records what it did in
results/deployments.jsonl.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brightwater.config import load_app  # noqa: E402
from brightwater.deploy import deploy  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"), required=False)
    parser.add_argument("--label", default="release", help="prefix for the app version ID")
    args = parser.parse_args()
    if not args.project:
        parser.error("set --project or GOOGLE_CLOUD_PROJECT")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    spec = load_app(require_urls=True)
    started = time.monotonic()
    result = deploy(args.project, spec, label=args.label)
    seconds = round(time.monotonic() - started, 1)

    record = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "seconds": seconds, **asdict(result)}
    out = ROOT / "results" / "deployments.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record).replace(args.project, "PROJECT") + "\n")
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
