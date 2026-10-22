"""Print the stored hand-off records, as the call desk's screen pop would show them.

Usage:
    python scripts/dump_handoffs.py --project P --since 2026-10-15T00:00:00 --out results/part5/handoff_records.json

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from google.cloud import firestore


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--project", required=True)
    p.add_argument("--since", default="")
    p.add_argument("--out", required=True)
    a = p.parse_args()
    db = firestore.Client(project=a.project)
    records = [d.to_dict() for d in db.collection("handoffs").stream()]
    records = sorted((r for r in records if str(r.get("created_at", "")) >= a.since), key=lambda r: r["created_at"])
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(records, indent=2, default=str) + "\n")
    print(json.dumps(records, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
