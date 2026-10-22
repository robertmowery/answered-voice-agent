"""Count CX Agent Studio sessions this repo's scripts created, from their result files.

Usage: python scripts/session_ledger.py [--extra N "reason"] --out results/series_spend.json

Probes, single-case reruns and phone calls don't leave result files; pass them
with --extra so the ledger stays honest.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSION_USD = 0.50


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--extra", nargs=2, action="append", default=[], metavar=("N", "REASON"))
    p.add_argument("--out")
    a = p.parse_args()
    rows = []
    for path in sorted((ROOT / "results").glob("part*/*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("sessions"), int):
            rows.append({"source": f"{path.parent.name}/{path.name}", "sessions": data["sessions"]})
    rows += [{"source": reason, "sessions": int(n)} for n, reason in a.extra]
    total = sum(r["sessions"] for r in rows)
    report = {"sessions": total, "usd_at_list_price": round(total * SESSION_USD, 2), "rows": rows}
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}))
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
