"""Turn recorded conversations into CX Agent Studio golden evaluations, and run them.

Usage:
    python scripts/golden_evals.py --project P generate --match eval-book-and-confirm eval-order-filters ...
    python scripts/golden_evals.py --project P run --out results/part7/golden_run.json

`generate` finds the most recent conversation whose name contains each match
string, asks CX Agent Studio to draft a golden evaluation from it
(conversations:generateEvaluation, which returns the draft without saving it),
and saves the draft as an evaluation in the app. `run` replays every golden evaluation in
the app against the current version (apps:runEvaluation) and records pass or
fail per evaluation, with the platform's explanations.

Uses the v1beta REST API through an authorized session; the Python client
google-cloud-ces 0.7.2 has no evaluation methods.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import google.auth
from google.auth.transport.requests import AuthorizedSession

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brightwater.config import load_app  # noqa: E402
from brightwater.deploy import app_name  # noqa: E402

API = "https://ces.googleapis.com/v1beta"


class Ces:
    def __init__(self, project: str) -> None:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        self.http = AuthorizedSession(creds)
        self.headers = {"x-goog-user-project": project}

    def call(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        r = self.http.request(method, f"{API}/{path}", headers=self.headers, timeout=120, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:500]}")
        return dict(r.json()) if r.text else {}

    def wait(self, operation: dict[str, Any], timeout_s: int = 900) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        while not operation.get("done"):
            if time.monotonic() > deadline:
                raise TimeoutError(operation.get("name"))
            time.sleep(10)
            operation = self.call("GET", operation["name"])
        if "error" in operation:
            raise RuntimeError(json.dumps(operation["error"]))
        return dict(operation.get("response", {}))

    def pages(self, path: str, key: str) -> list[dict[str, Any]]:
        out, token = [], None
        while True:
            params = {"pageSize": 100, **({"pageToken": token} if token else {})}
            page = self.call("GET", path, params=params)
            out.extend(page.get(key, []))
            token = page.get("nextPageToken")
            if not token:
                return out


def generate(ces: Ces, app: str, matches: list[str]) -> list[str]:
    conversations = ces.pages(f"{app}/conversations", "conversations")
    made = []
    for match in matches:
        found = sorted(
            (c for c in conversations if match in json.dumps(c)), key=lambda c: c.get("startTime", ""), reverse=True
        )
        if not found:
            print(f"no conversation matches {match!r}")
            continue
        # generateEvaluation drafts the golden; it isn't saved until we create it.
        draft = ces.wait(ces.call("POST", f"{found[0]['name']}:generateEvaluation", json={}))
        draft.pop("@type", None)
        draft["displayName"] = match
        draft["description"] = f"Golden from recorded conversation {found[0]['name'].rsplit('/', 1)[-1]}"
        evaluation = ces.call("POST", f"{app}/evaluations", json=draft)
        print(f"{match}: {evaluation.get('name')}")
        made.append(str(evaluation.get("name")))
    return made


def run(ces: Ces, app: str, out: Path) -> None:
    evaluations = [e["name"] for e in ces.pages(f"{app}/evaluations", "evaluations")]
    started = time.monotonic()
    response = ces.wait(
        ces.call(
            "POST",
            f"{app}:runEvaluation",
            json={"app": app, "evaluations": evaluations, "goldenRunMethod": "STABLE", "generateLatencyReport": True},
        )
    )
    run_name = response.get("name") or response.get("evaluationRun")
    runs = ces.pages(f"{app}/evaluationRuns", "evaluationRuns")
    latest = next((r for r in runs if r["name"] == run_name), runs[0] if runs else {})
    results = []
    for result_name in latest.get("evaluationResults", []):
        r = ces.call("GET", result_name)
        expectations = r.get("goldenResult", {}).get("evaluationExpectationResults", [])
        results.append(
            {
                "evaluation": result_name.split("/evaluations/")[1].split("/")[0],
                "status": r.get("evaluationStatus"),
                "state": r.get("executionState"),
                "expectations": [
                    {"outcome": e.get("outcome"), "explanation": (e.get("explanation") or "")[:300]}
                    for e in expectations
                ],
                "turn_latencies": [
                    t.get("turnLatency") for t in r.get("goldenResult", {}).get("turnReplayResults", [])
                ],
            }
        )
    report = {
        "run": run_name,
        "seconds": round(time.monotonic() - started, 1),
        "progress": latest.get("progress"),
        "app_version": latest.get("appVersionDisplayName"),
        "results": results,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2).replace(app.split("/")[1], "PROJECT") + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
    for r in results:
        print(r["evaluation"], r["status"])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--project", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--match", nargs="+", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    a = p.parse_args()
    ces = Ces(a.project)
    app = app_name(a.project, load_app())
    if a.cmd == "generate":
        generate(ces, app, a.match)
    else:
        run(ces, app, Path(a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
