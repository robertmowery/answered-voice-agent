"""Debug helper: send one turn and print the full diagnostic info (spans, guardrail results, tool calls).

Usage: python scripts/probe_turn.py --project P "Are you open right now?" ["next turn" ...]

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google.api_core.client_options import ClientOptions  # noqa: E402
from google.cloud import ces_v1  # noqa: E402
from google.cloud.ces_v1 import types  # noqa: E402
from google.protobuf.json_format import MessageToDict  # noqa: E402

from brightwater.config import load_app  # noqa: E402
from brightwater.deploy import app_name  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--project", required=True)
    p.add_argument("--deployment", default="api-smoke")
    p.add_argument("turns", nargs="+")
    a = p.parse_args()
    spec = load_app()
    app = app_name(a.project, spec)
    client = ces_v1.SessionServiceClient(client_options=ClientOptions(quota_project_id=a.project))
    session = f"{app}/sessions/probe-{uuid.uuid4().hex[:8]}"
    for say in a.turns:
        req = types.RunSessionRequest(
            config=types.SessionConfig(
                session=session, deployment=f"{app}/deployments/{a.deployment}", time_zone=spec.time_zone
            ),
            inputs=[types.SessionInput(text=say)],
        )
        t = time.monotonic()
        resp = client.run_session(request=req)
        print(f"=== {say!r} ({time.monotonic() - t:.2f}s)")
        print(json.dumps(MessageToDict(resp._pb), indent=1)[:12000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
