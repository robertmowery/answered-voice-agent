"""The price list the office already maintains, read from its Google Sheet.

The agent quotes only what this returns: a flat fee or a range, with the note
the office wrote beside it. When the office changes a price in the sheet, the
agent's next call sees it within the cache window (five minutes). Readers
without Workspace get the same list from policy/price_list.csv.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import csv
import io
import os
import time
from pathlib import Path
from typing import Any

FALLBACK = Path(__file__).resolve().parent.parent / "policy" / "price_list.csv"
TTL_SECONDS = 300
_cache: tuple[float, list[dict[str, Any]]] | None = None


def _rows_from_table(table: list[list[str]]) -> list[dict[str, Any]]:
    header, *body = table
    rows = []
    for raw in body:
        row = dict(zip(header, raw + [""] * (len(header) - len(raw)), strict=False))
        if not row.get("service_id"):
            continue
        low, high = int(row["low_usd"]), int(row["high_usd"])
        if low > high:
            raise ValueError(f"{row['service_id']}: low_usd above high_usd")
        rows.append(
            {
                "service_id": row["service_id"],
                "service": row["service"],
                "low_usd": low,
                "high_usd": high,
                "how_priced": row["how_priced"],
                "note": row.get("note", ""),
                "say": spoken(row["how_priced"], low, high),
            }
        )
    return rows


def spoken(how: str, low: int, high: int) -> str:
    if how == "flat":
        return f"${low:,} flat"
    if how == "per_year":
        return f"${low:,} a year"
    return f"usually between ${low:,} and ${high:,}"


def _from_sheet(sheet_id: str) -> list[list[str]]:
    import google.auth
    from googleapiclient.discovery import build

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    api = build("sheets", "v4", credentials=creds, cache_discovery=False)
    result = api.spreadsheets().values().get(spreadsheetId=sheet_id, range="A:F").execute()
    return [list(map(str, r)) for r in result.get("values", [])]


def price_list(now: float | None = None) -> list[dict[str, Any]]:
    global _cache
    now = time.monotonic() if now is None else now
    if _cache and now - _cache[0] < TTL_SECONDS:
        return _cache[1]
    sheet_id = os.environ.get("PRICE_SHEET_ID")
    table = _from_sheet(sheet_id) if sheet_id else list(csv.reader(io.StringIO(FALLBACK.read_text())))
    rows = _rows_from_table(table)
    _cache = (now, rows)
    return rows
