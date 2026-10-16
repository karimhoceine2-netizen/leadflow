import asyncio
import json
import sqlite3

import pytest

from app.models import LeadRecord
from app.outbox import Outbox
from test_admin import client, settings, password_hash, login
from test_api import send


@pytest.mark.parametrize(
    "state,receipt,expected",
    [
        ("pending", False, "pending"),
        ("dead", False, "failed"),
        ("pending", True, "processed"),
        ("dead", True, "processed"),
        ("delivered", True, "processed"),
        ("delivered", False, "pending"),
    ],
)
def test_dashboard_uses_receipt_not_delivery_flag(client, settings, state, receipt, expected):
    lead_id = send(client).json()["id"]
    with sqlite3.connect(settings.demo_db_path) as db:
        event = json.loads(db.execute("SELECT payload FROM lead_events").fetchone()[0])
    if receipt:
        asyncio.run(Outbox(settings.demo_db_path).process(event))
    with sqlite3.connect(settings.demo_db_path) as db:
        db.execute("UPDATE lead_events SET state=?, attempts=2, last_error='private test detail'", (state,))
    login(client)
    detail = client.get(f"/api/admin/leads/{lead_id}").json()
    page = client.get("/api/admin/leads").json()
    info = detail["automation"]
    assert info == page["items"][0]["automation"]
    assert info["status"] == expected and info["attempts"] == 2
    assert info["delivery_state"] == state
    assert bool(info["processed_at"]) == receipt
    assert info["priority"] == ("normal" if receipt else None)
    assert set(info) == {"status", "delivery_state", "attempts", "processed_at", "priority"}
    assert "private test detail" not in str(info) and "description" not in str(info)
    assert detail["status"] == "new" and detail["version"] == 0 and detail["history"] == []


def test_older_leads_are_not_scheduled_and_new_leads_are_pending(client, settings):
    old = send(client).json()["id"]
    with sqlite3.connect(settings.demo_db_path) as db:
        db.execute("DELETE FROM lead_events WHERE lead_id=?", (old,))
    new = send(client).json()["id"]
    login(client)
    page = client.get("/api/admin/leads?page_size=1").json()
    assert page["total"] == 2 and len(page["items"]) == 1
    assert client.get(f"/api/admin/leads/{old}").json()["automation"]["status"] == "not_scheduled"
    assert client.get(f"/api/admin/leads/{new}").json()["automation"]["status"] == "pending"


def test_workflow_info_requires_admin_and_stays_out_of_public_response(client):
    response = send(client)
    assert "automation" not in response.json()
    assert client.get("/api/admin/leads").status_code == 401
    assert client.get(f"/api/admin/leads/{response.json()['id']}").status_code == 401


def test_processed_workflow_info_survives_manual_status_update(client, settings):
    lead_id = send(client).json()["id"]
    with sqlite3.connect(settings.demo_db_path) as db:
        event = json.loads(db.execute("SELECT payload FROM lead_events").fetchone()[0])
    asyncio.run(Outbox(settings.demo_db_path).process(event))
    headers = login(client)
    before = client.get(f"/api/admin/leads/{lead_id}").json()["automation"]
    result = client.patch(
        f"/api/admin/leads/{lead_id}/status", json={"status": "contacted", "expected_version": 0}, headers=headers
    ).json()
    assert result["status"] == "contacted" and result["automation"] == before
    assert len(result["history"]) == 1


def test_missing_workflow_info_is_explicitly_unavailable():
    # A record without workflow information must never be labelled as processed or not scheduled.
    record = LeadRecord(
        id="e5c0ca0c-7a37-4877-aec0-4925060005ab",
        name="Test User",
        email="test@example.com",
        company_name="Fictief Bedrijf",
        description="Fictieve aanvraag",
        status="new",
        version=0,
        created_at="2026-10-10T00:00:00Z",
        updated_at="2026-10-10T00:00:00Z",
    )
    assert record.automation.status == "unavailable"


def test_malformed_workflow_result_becomes_safe_storage_error(client, settings):
    lead_id = send(client).json()["id"]
    with sqlite3.connect(settings.demo_db_path) as db:
        event = json.loads(db.execute("SELECT payload FROM lead_events").fetchone()[0])
    asyncio.run(Outbox(settings.demo_db_path).process(event))
    with sqlite3.connect(settings.demo_db_path) as db:
        db.execute("UPDATE workflow_receipts SET result='[]'")
    login(client)
    assert client.get(f"/api/admin/leads/{lead_id}").status_code == 503
    assert client.get("/api/admin/leads").status_code == 503
