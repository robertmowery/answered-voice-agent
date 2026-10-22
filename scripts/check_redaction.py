"""Check what CX Agent Studio stored for recent conversations: does any transcript contain a card number?

Usage: python scripts/check_redaction.py --project P [--since-minutes 60] --out results/part6/redaction.json

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google.protobuf.json_format import MessageToDict  # noqa: E402

from brightwater.config import load_app  # noqa: E402
from brightwater.deploy import app_name, make_client  # noqa: E402

CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")


def luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def has_card_number(text: str) -> bool:
    """A 13 to 19 digit run (spaces or dashes allowed) that passes the Luhn check, like 4111 1111 1111 1111."""
    for match in CARD.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if 13 <= len(digits) <= 19 and luhn(digits):
            return True
    return False


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--project", required=True)
    p.add_argument("--since-minutes", type=int, default=60)
    p.add_argument("--out")
    a = p.parse_args()
    client = make_client(a.project)
    app = app_name(a.project, load_app())
    since = datetime.now(UTC) - timedelta(minutes=a.since_minutes)
    rows = []
    for conv in client.list_conversations(parent=app):
        start = conv.start_time
        if start and start.replace(tzinfo=UTC) < since:
            continue
        full = client.get_conversation(name=conv.name)
        text = json.dumps(MessageToDict(full._pb))
        rows.append(
            {
                "conversation": conv.name.rsplit("/", 1)[-1],
                "start": str(start),
                "card_number_present": has_card_number(text),
                "redaction_marker_present": "CREDIT_CARD_NUMBER" in text,
            }
        )
    report = {
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "conversations": len(rows),
        "with_card_number": sum(r["card_number_present"] for r in rows),
        "with_redaction_marker": sum(r["redaction_marker_present"] for r in rows),
        "rows": rows,
    }
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
