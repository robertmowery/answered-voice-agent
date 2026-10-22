"""Delete the Brightwater app from CX Agent Studio.

Usage:
    python scripts/teardown_agent.py --project YOUR_PROJECT [--yes]

Deletes the deployments first (an app with deployments can't be deleted), then
the app itself, which removes its agents, tools, guardrails and versions.
Release any Google Telephony Platform phone number in the console first; the
script stops if a phone channel is still attached.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google.api_core import exceptions  # noqa: E402
from google.cloud.ces_v1 import types  # noqa: E402

from brightwater.config import load_app  # noqa: E402
from brightwater.deploy import app_name, make_client  # noqa: E402

PHONE = types.ChannelProfile.ChannelType.GOOGLE_TELEPHONY_PLATFORM


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()
    if not args.project:
        parser.error("set --project or GOOGLE_CLOUD_PROJECT")

    client = make_client(args.project)
    app = app_name(args.project, load_app())
    try:
        deployments = list(client.list_deployments(parent=app))
    except exceptions.NotFound:
        print(f"Nothing to delete: {app} does not exist")
        return 0

    phones = [d.name for d in deployments if d.channel_profile.channel_type == PHONE]
    if phones:
        print("Release the phone number first (CX Agent Studio > Deploy):", *phones, sep="\n  ")
        return 1
    if not args.yes and input(f"Delete {app} and {len(deployments)} deployment(s)? [y/N] ").lower() != "y":
        return 1

    for d in deployments:
        client.delete_deployment(name=d.name)
        print(f"Deleted {d.name}")
    op = client.delete_app(name=app)
    if hasattr(op, "result"):
        op.result(timeout=300)
    print(f"Deleted {app}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
