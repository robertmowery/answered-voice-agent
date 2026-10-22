"""Checkout session storage: Firestore in the cloud, memory for tests and local runs.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import os
from typing import Any, Protocol


class Store(Protocol):
    def get(self, checkout_id: str) -> dict[str, Any] | None: ...

    def put(self, session: dict[str, Any], idempotency_key: str | None = None) -> None: ...

    def by_idempotency_key(self, key: str) -> dict[str, Any] | None: ...


class MemoryStore:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.keys: dict[str, str] = {}

    def get(self, checkout_id: str) -> dict[str, Any] | None:
        found = self.sessions.get(checkout_id)
        return dict(found) if found else None

    def put(self, session: dict[str, Any], idempotency_key: str | None = None) -> None:
        self.sessions[session["id"]] = dict(session)
        if idempotency_key:
            self.keys[idempotency_key] = session["id"]

    def by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        checkout_id = self.keys.get(key)
        return {k: v for k, v in self.get(checkout_id).items() if not k.startswith("_")} if checkout_id else None


class FirestoreStore:
    def __init__(self) -> None:
        from google.cloud import firestore

        db = firestore.Client()
        self._sessions = db.collection("checkouts")
        self._keys = db.collection("checkout_idempotency")

    def get(self, checkout_id: str) -> dict[str, Any] | None:
        snap = self._sessions.document(checkout_id).get()
        return snap.to_dict() if snap.exists else None

    def put(self, session: dict[str, Any], idempotency_key: str | None = None) -> None:
        self._sessions.document(session["id"]).set(session)
        if idempotency_key:
            self._keys.document(idempotency_key).set({"checkout_id": session["id"]})

    def by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        snap = self._keys.document(key).get()
        if not snap.exists:
            return None
        session = self.get(snap.to_dict()["checkout_id"])
        return {k: v for k, v in session.items() if not k.startswith("_")} if session else None


def make_store() -> Store:
    return FirestoreStore() if os.environ.get("GOOGLE_CLOUD_PROJECT") else MemoryStore()
