"""Create Brightwater's dispatch calendar, owned by the tools-api service account.

Usage:
    python scripts/seed_workspace.py --project YOUR_PROJECT --share-with you@yourdomain.com

Runs as the tools-api service account (through impersonation, so no key file),
creates a secondary calendar it owns, and shares it with the person who will
watch bookings arrive. Prints the calendar ID to put in terraform.tfvars as
dispatch_calendar_id. Run it once; running it again creates a second calendar.

Delete the calendar at teardown with --delete CALENDAR_ID.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import argparse
import os

import google.auth
from google.auth import impersonated_credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def calendar_api(project: str):  # type: ignore[no-untyped-def]
    source, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    target = f"tools-api@{project}.iam.gserviceaccount.com"
    creds = impersonated_credentials.Credentials(
        source_credentials=source, target_principal=target, target_scopes=SCOPES
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--share-with", help="email to share the calendar with (writer)")
    parser.add_argument("--delete", metavar="CALENDAR_ID", help="delete this calendar instead")
    args = parser.parse_args()
    if not args.project:
        parser.error("set --project or GOOGLE_CLOUD_PROJECT")
    api = calendar_api(args.project)

    if args.delete:
        api.calendars().delete(calendarId=args.delete).execute()
        print(f"Deleted {args.delete}")
        return 0

    cal = (
        api.calendars()
        .insert(body={"summary": "Brightwater dispatch (fictional demo)", "timeZone": "America/New_York"})
        .execute()
    )
    if args.share_with:
        api.acl().insert(
            calendarId=cal["id"], body={"role": "writer", "scope": {"type": "user", "value": args.share_with}}
        ).execute()
    print(cal["id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
