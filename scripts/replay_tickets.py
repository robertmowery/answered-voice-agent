"""Republish tickets the worker recorded but never delivered to the office.

Usage: python scripts/replay_tickets.py --project YOUR_PROJECT [--dry-run]

The worker writes every ticket to Firestore before it touches the sheet, with
delivered=false until the sheet (and Chat) succeed. Anything still undelivered
after Pub/Sub gave up is in Firestore; this republishes it to the tickets topic,
and the worker's idempotent claim makes a double delivery harmless.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import argparse
import json
import os

from google.cloud import firestore, pubsub_v1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    p.add_argument("--topic", default="tickets")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    db = firestore.Client(project=a.project)
    publisher = pubsub_v1.PublisherClient()
    topic = publisher.topic_path(a.project, a.topic)
    pending = [d for d in db.collection("tickets").where("delivered", "==", False).stream()]
    for doc in pending:
        ticket = {k: v for k, v in doc.to_dict().items() if k != "delivered"}
        print(f"{'would replay' if a.dry_run else 'replaying'} {doc.id} (created {ticket.get('created_at')})")
        if not a.dry_run:
            publisher.publish(topic, json.dumps(ticket).encode(), event_type="ticket.created").result(timeout=10)
    print(f"{len(pending)} undelivered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
