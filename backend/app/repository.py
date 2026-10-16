import asyncio
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

import httpx

from .models import AutomationInfo, LeadCreate, LeadResponse, LeadRecord, LeadDetail, LeadPage, StatusEvent, StatusUpdate
from .repository_errors import StorageUnavailable
from . import outbox


class IdempotencyConflict(Exception):
    """The same key was used for different input."""


class VersionConflict(Exception):
    """Another edit has already changed this record."""


def payload_hash(lead: LeadCreate) -> str:
    return hashlib.sha256(json.dumps(lead.model_dump(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class LeadRepository(Protocol):
    async def create(self, lead: LeadCreate, key: UUID) -> LeadResponse: ...
    async def list(self, query: str, status: str | None, page: int, page_size: int) -> LeadPage: ...
    async def detail(self, lead_id: UUID) -> LeadDetail | None: ...
    async def update_status(self, lead_id: UUID, change: StatusUpdate, actor: str) -> LeadDetail | None: ...


class DemoRepository:
    """Persistent SQLite; UNIQUE prevents duplicates across concurrent requests."""

    def __init__(self, path: Path):
        self.path = path

    async def initialize(self):
        await asyncio.to_thread(self._initialize)

    def _initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS leads (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL,
                company_name TEXT NOT NULL, description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new', idempotency_key TEXT NOT NULL UNIQUE,
                payload_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(leads)")}
            if "version" not in columns:
                connection.execute("ALTER TABLE leads ADD COLUMN version INTEGER NOT NULL DEFAULT 0")
            if "updated_at" not in columns:
                connection.execute("ALTER TABLE leads ADD COLUMN updated_at TEXT")
            connection.execute("UPDATE leads SET updated_at = created_at WHERE updated_at IS NULL")
            connection.execute("""CREATE TABLE IF NOT EXISTS lead_status_events (
                id TEXT PRIMARY KEY, lead_id TEXT NOT NULL REFERENCES leads(id),
                previous_status TEXT NOT NULL, new_status TEXT NOT NULL, actor TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            outbox.initialize(connection)

    async def create(self, lead: LeadCreate, key: UUID) -> LeadResponse:
        try:
            return await asyncio.to_thread(self._create, lead, key)
        except sqlite3.Error:
            raise StorageUnavailable() from None

    def _create(self, lead: LeadCreate, key: UUID) -> LeadResponse:
        digest = payload_hash(lead)
        with sqlite3.connect(self.path, timeout=8) as connection:
            cursor = connection.execute(
                """INSERT INTO leads (id, name, email, company_name, description, idempotency_key, payload_hash, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(idempotency_key) DO NOTHING""",
                (str(uuid4()), lead.name, str(lead.email), lead.company_name, lead.description, str(key), digest),
            )
            row = connection.execute(
                "SELECT id, status, payload_hash FROM leads WHERE idempotency_key = ?", (str(key),)
            ).fetchone()
            if row[2] != digest:
                raise IdempotencyConflict()
            if cursor.rowcount == 1:
                # Same transaction as the new lead: both commit, or neither does.
                outbox.enqueue(connection, row[0], lead)
            return LeadResponse(id=row[0], status=row[1], duplicate=cursor.rowcount == 0)

    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=8)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    async def list(self, query: str, status: str | None, page: int, page_size: int) -> LeadPage:
        try:
            return await asyncio.to_thread(self._list, query, status, page, page_size)
        except (sqlite3.Error, ValueError):
            raise StorageUnavailable() from None

    def _list(self, query, status, page, page_size):
        with self._connection() as connection:
            where = "WHERE instr(lower(leads.name || ' ' || leads.email || ' ' || leads.company_name), lower(?)) > 0"
            values: list = [query]
            if status:
                where += " AND leads.status = ?"
                values.append(status)
            total = connection.execute(f"SELECT count(*) FROM leads {where}", values).fetchone()[0]
            rows = connection.execute(f"{self._automation_query()} {where} ORDER BY leads.created_at DESC, leads.id DESC LIMIT ? OFFSET ?", [*values, page_size, (page - 1) * page_size]).fetchall()
            counts = {key: 0 for key in ("new", "contacted", "qualified", "closed")}
            counts.update({row[0]: row[1] for row in connection.execute("SELECT status, count(*) FROM leads GROUP BY status")})
            return LeadPage(items=[LeadRecord(**dict(row), automation=self._automation_info(row)) for row in rows], total=total, page=page, page_size=page_size, counts=counts)

    @staticmethod
    def _automation_query():
        # One join for the entire page, no per-lead queries and no payload/secret serialization.
        return """SELECT leads.*, e.id AS _event_id, e.state AS _delivery_state,
            e.attempts AS _attempts, r.event_id AS _receipt_id, r.processed_at AS _processed_at,
            r.result AS _result FROM leads
            LEFT JOIN lead_events e ON e.lead_id = leads.id AND e.event_type = 'lead.created'
            LEFT JOIN workflow_receipts r ON r.event_id = e.id"""

    @staticmethod
    def _automation_info(row):
        if row["_event_id"] is None:
            return AutomationInfo(status="not_scheduled")
        processed = row["_receipt_id"] is not None
        result = json.loads(row["_result"]) if processed else {}
        if not isinstance(result, dict):
            raise ValueError("Invalid stored workflow result")
        return AutomationInfo(status="processed" if processed else "failed" if row["_delivery_state"] == "dead" else "pending",
            delivery_state=row["_delivery_state"], attempts=row["_attempts"],
            processed_at=row["_processed_at"], priority=result.get("priority"))

    def _detail(self, connection, lead_id):
        row = connection.execute(self._automation_query() + " WHERE leads.id = ?", (str(lead_id),)).fetchone()
        if not row:
            return None
        history = connection.execute("SELECT * FROM lead_status_events WHERE lead_id = ? ORDER BY rowid DESC", (str(lead_id),)).fetchall()
        return LeadDetail(**dict(row), automation=self._automation_info(row), history=[StatusEvent.model_validate(dict(event)) for event in history])

    async def detail(self, lead_id: UUID) -> LeadDetail | None:
        def read():
            with self._connection() as connection:
                return self._detail(connection, lead_id)
        try:
            return await asyncio.to_thread(read)
        except (sqlite3.Error, ValueError):
            raise StorageUnavailable() from None

    async def update_status(self, lead_id: UUID, change: StatusUpdate, actor: str) -> LeadDetail | None:
        try:
            return await asyncio.to_thread(self._update_status, lead_id, change, actor)
        except (sqlite3.Error, ValueError):
            raise StorageUnavailable() from None

    def _update_status(self, lead_id, change, actor):
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT status, version FROM leads WHERE id = ?", (str(lead_id),)).fetchone()
            if not row:
                return None
            if row["version"] != change.expected_version:
                raise VersionConflict()
            if row["status"] != change.status:
                connection.execute("UPDATE leads SET status = ?, version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (change.status, str(lead_id)))
                connection.execute("INSERT INTO lead_status_events (id, lead_id, previous_status, new_status, actor) VALUES (?, ?, ?, ?, ?)", (str(uuid4()), str(lead_id), row["status"], change.status, actor))
            return self._detail(connection, lead_id)


@dataclass
class SupabaseRepository:
    url: str
    key: str
    client: httpx.AsyncClient

    async def create(self, lead: LeadCreate, key: UUID) -> LeadResponse:
        # PostgreSQL RPC handles insert/retry/conflict in one transaction.
        try:
            response = await self.client.post(
                f"{self.url}/rest/v1/rpc/submit_lead",
                headers={"apikey": self.key, "Authorization": f"Bearer {self.key}"},
                json={"p_lead": lead.model_dump(), "p_key": str(key), "p_hash": payload_hash(lead)},
            )
            if response.status_code == 409 and response.json().get("code") == "23505":
                raise IdempotencyConflict()
            response.raise_for_status()
            return LeadResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            raise StorageUnavailable() from None

    async def _rpc(self, name: str, payload: dict):
        try:
            response = await self.client.post(f"{self.url}/rest/v1/rpc/{name}", headers={"apikey": self.key, "Authorization": f"Bearer {self.key}"}, json=payload)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise StorageUnavailable() from None

    async def list(self, query: str, status: str | None, page: int, page_size: int) -> LeadPage:
        result = await self._rpc("list_leads", {"p_query": query, "p_status": status, "p_page": page, "p_size": page_size})
        try:
            return LeadPage.model_validate(result)
        except ValueError:
            raise StorageUnavailable() from None

    async def detail(self, lead_id: UUID) -> LeadDetail | None:
        result = await self._rpc("get_lead_detail", {"p_id": str(lead_id)})
        try:
            return LeadDetail.model_validate(result) if result else None
        except ValueError:
            raise StorageUnavailable() from None

    async def update_status(self, lead_id: UUID, change: StatusUpdate, actor: str) -> LeadDetail | None:
        result = await self._rpc("update_lead_status", {"p_id": str(lead_id), "p_status": change.status, "p_version": change.expected_version, "p_actor": actor})
        if isinstance(result, dict) and result.get("conflict"):
            raise VersionConflict()
        try:
            return LeadDetail.model_validate(result) if result else None
        except ValueError:
            raise StorageUnavailable() from None
