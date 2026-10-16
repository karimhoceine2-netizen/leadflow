"""Durable local outbox and idempotent workflow effects, separate from lead status."""

import asyncio
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .repository_errors import StorageUnavailable


def canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def initialize(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS lead_events (
        id TEXT PRIMARY KEY, lead_id TEXT NOT NULL REFERENCES leads(id),
        event_type TEXT NOT NULL, payload TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending', 'delivered', 'dead')),
        attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0,
        lease_token TEXT, lease_until REAL, last_error TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, delivered_at TEXT,
        UNIQUE(lead_id, event_type)
    )""")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS lead_events_pending ON lead_events(state, available_at, lease_until)"
    )
    connection.execute("""CREATE TABLE IF NOT EXISTS workflow_receipts (
        event_id TEXT PRIMARY KEY REFERENCES lead_events(id), result TEXT NOT NULL,
        processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")


def enqueue(connection, lead_id: str, lead):
    event_id = str(uuid4())
    event = {
        "event_id": event_id,
        "event_type": "lead.created",
        "schema_version": 1,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "lead": {"id": lead_id, **lead.model_dump(), "status": "new"},
    }
    connection.execute(
        "INSERT INTO lead_events (id, lead_id, event_type, payload) VALUES (?, ?, ?, ?)",
        (event_id, lead_id, "lead.created", canonical(event)),
    )


class EventMismatch(Exception):
    pass


class Outbox:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=8)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    async def claim(self, max_attempts=10, now=None):
        return await asyncio.to_thread(self._claim, max_attempts, time.time() if now is None else now)

    def _claim(self, max_attempts, now):
        try:
            with self.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                # A worker that crashed on its final attempt must not leave a job stuck forever.
                db.execute(
                    """UPDATE lead_events SET state = 'dead', last_error = 'attempts_exhausted',
                    lease_token = NULL, lease_until = NULL WHERE state = 'pending' AND attempts >= ?
                    AND (lease_until IS NULL OR lease_until <= ?)""",
                    (max_attempts, now),
                )
                row = db.execute(
                    """SELECT * FROM lead_events WHERE state = 'pending' AND attempts < ?
                    AND available_at <= ? AND (lease_until IS NULL OR lease_until <= ?)
                    ORDER BY created_at, id LIMIT 1""",
                    (max_attempts, now, now),
                ).fetchone()
                if not row:
                    return None
                token = str(uuid4())
                db.execute(
                    "UPDATE lead_events SET attempts = attempts + 1, lease_token = ?, lease_until = ? WHERE id = ?",
                    (token, now + 60, row["id"]),
                )
                return {
                    "id": row["id"],
                    "event": json.loads(row["payload"]),
                    "attempts": row["attempts"] + 1,
                    "lease_token": token,
                }
        except (sqlite3.Error, ValueError):
            raise StorageUnavailable() from None

    async def finish(self, job, error=None, max_attempts=10, now=None):
        return await asyncio.to_thread(self._finish, job, error, max_attempts, time.time() if now is None else now)

    def _finish(self, job, error, max_attempts, now):
        try:
            with self.connection() as db:
                if error is None:
                    # An HTTP 200 alone is not enough: the idempotent effect must be committed.
                    cursor = db.execute(
                        """UPDATE lead_events SET state = 'delivered', delivered_at = CURRENT_TIMESTAMP,
                        lease_token = NULL, lease_until = NULL, last_error = NULL
                        WHERE id = ? AND lease_token = ? AND EXISTS
                        (SELECT 1 FROM workflow_receipts WHERE event_id = lead_events.id)""",
                        (job["id"], job["lease_token"]),
                    )
                    return cursor.rowcount == 1
                state = "dead" if job["attempts"] >= max_attempts else "pending"
                delay = min(300, 2 ** min(job["attempts"], 9))
                cursor = db.execute(
                    """UPDATE lead_events SET state = ?, available_at = ?, last_error = ?,
                    lease_token = NULL, lease_until = NULL WHERE id = ? AND lease_token = ?""",
                    (state, now + delay, error, job["id"], job["lease_token"]),
                )
                return cursor.rowcount == 1
        except sqlite3.Error:
            raise StorageUnavailable() from None

    async def process(self, event: dict):
        return await asyncio.to_thread(self._process, event)

    def _process(self, event):
        try:
            with self.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                saved = db.execute("SELECT payload FROM lead_events WHERE id = ?", (event["event_id"],)).fetchone()
                if not saved or canonical(event) != saved["payload"]:
                    raise EventMismatch()
                previous = db.execute(
                    "SELECT result FROM workflow_receipts WHERE event_id = ?", (event["event_id"],)
                ).fetchone()
                if previous:
                    result = json.loads(previous["result"])
                else:
                    # Deterministic demo rules, not AI. Does not change the CRM's manual status.
                    description = event["lead"]["description"].casefold()
                    result = {
                        "method": "demo_rules",
                        "category": "automation_interest",
                        "priority": "review_urgency"
                        if any(word in description for word in ("spoed", "urgent", "dringend"))
                        else "normal",
                    }
                    db.execute(
                        "INSERT INTO workflow_receipts (event_id, result) VALUES (?, ?)",
                        (event["event_id"], canonical(result)),
                    )
                return {"event_id": event["event_id"], "processed": True, "duplicate": bool(previous), "result": result}
        except (sqlite3.Error, ValueError, KeyError, TypeError):
            raise StorageUnavailable() from None

    async def status(self):
        return await asyncio.to_thread(self._status)

    def _status(self):
        with self.connection() as db:
            counts = {"pending": 0, "delivered": 0, "dead": 0}
            counts.update(
                {row[0]: row[1] for row in db.execute("SELECT state, count(*) FROM lead_events GROUP BY state")}
            )
            return {
                "counts": counts,
                "processed": db.execute("SELECT count(*) FROM workflow_receipts").fetchone()[0],
                "recent": [
                    dict(row)
                    for row in db.execute(
                        "SELECT id, state, attempts, last_error FROM lead_events ORDER BY rowid DESC LIMIT 10"
                    )
                ],
            }

    async def retry(self, event_id: str):
        def reset():
            with self.connection() as db:
                cursor = db.execute(
                    """UPDATE lead_events SET state = 'pending', attempts = 0, available_at = 0,
                    last_error = NULL, lease_token = NULL, lease_until = NULL WHERE id = ? AND state = 'dead'""",
                    (event_id,),
                )
                return cursor.rowcount == 1

        return await asyncio.to_thread(reset)
