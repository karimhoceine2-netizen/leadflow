import asyncio
import secrets
import json
import sqlite3
import time
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.automation import Worker, envelope, signature
from app.config import Settings
from app.main import create_app
from app.models import LeadCreate, StatusUpdate
from app.outbox import EventMismatch, Outbox
from app.repository import DemoRepository
from test_api import PAYLOAD, send

SECRET = secrets.token_urlsafe(48)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        app_env="test",
        demo_db_path=tmp_path / "leads.sqlite3",
        env_file=tmp_path / ".env",
        automation_enabled=True,
        n8n_webhook_secret=SECRET,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, start_automation_worker=False), client=("127.0.0.1", 1)) as client:
        yield client


def saved_event(settings):
    with sqlite3.connect(settings.demo_db_path) as db:
        return json.loads(db.execute("SELECT payload FROM lead_events ORDER BY rowid DESC LIMIT 1").fetchone()[0])


def test_intake_commits_one_lead_and_one_event_on_retries(client, settings):
    key = uuid4()
    lead = send(client, key=key).json()
    assert send(client, key=key).json()["id"] == lead["id"]
    with sqlite3.connect(settings.demo_db_path) as db:
        assert db.execute("SELECT count(*) FROM leads").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM lead_events").fetchone()[0] == 1
    event = saved_event(settings)
    assert event["lead"]["id"] == lead["id"] and event["event_type"] == "lead.created"
    assert "idempotency_key" not in str(event) and "payload_hash" not in str(event)


def test_failed_event_insert_rolls_back_the_lead(client, settings):
    with sqlite3.connect(settings.demo_db_path) as db:
        db.execute(
            "CREATE TRIGGER fail_outbox BEFORE INSERT ON lead_events BEGIN SELECT RAISE(ABORT, 'test failure'); END"
        )
    response = send(client)
    assert response.status_code == 503
    with sqlite3.connect(settings.demo_db_path) as db:
        assert db.execute("SELECT count(*) FROM leads").fetchone()[0] == 0


def test_parallel_intake_creates_exactly_one_event(settings):
    async def scenario():
        repo = DemoRepository(settings.demo_db_path)
        await repo.initialize()
        key = uuid4()
        await asyncio.gather(*(repo.create(LeadCreate(**PAYLOAD), key) for _ in range(8)))
        assert (await Outbox(settings.demo_db_path).status())["counts"]["pending"] == 1

    asyncio.run(scenario())


def test_signed_receiver_is_idempotent_and_preserves_manual_status(client, settings):
    lead_id = send(client).json()["id"]
    event = saved_event(settings)
    asyncio.run(
        DemoRepository(settings.demo_db_path).update_status(
            UUID(lead_id), StatusUpdate(status="contacted", expected_version=0), "admin@example.com"
        )
    )
    payload = envelope(event, SECRET)
    first = client.post("/api/automation/process", json=payload, headers={"X-LeadFlow-Token": SECRET})
    again = client.post("/api/automation/process", json=payload, headers={"X-LeadFlow-Token": SECRET})
    assert first.status_code == again.status_code == 200
    assert first.json()["duplicate"] is False and again.json()["duplicate"] is True
    assert first.json()["result"] == again.json()["result"]
    with sqlite3.connect(settings.demo_db_path) as db:
        assert db.execute("SELECT count(*) FROM workflow_receipts").fetchone()[0] == 1
        assert db.execute("SELECT status FROM leads").fetchone()[0] == "contacted"


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("no_token", 401),
        ("bad_token", 401),
        ("tampered", 401),
        ("expired", 401),
        ("future", 401),
        ("unknown_event", 409),
        ("unknown_payload", 409),
        ("bad_signature_shape", 422),
        ("oversized", 413),
    ],
)
def test_receiver_rejects_invalid_requests_without_processing(client, settings, kind, expected):
    send(client)
    event = saved_event(settings)
    payload = envelope(event, SECRET)
    headers = {"X-LeadFlow-Token": SECRET}
    if kind == "no_token":
        headers = {}
    if kind == "bad_token":
        headers["X-LeadFlow-Token"] = "wrong"
    if kind == "tampered":
        payload["event"]["lead"]["name"] = "Tampered Name"
    if kind == "expired":
        payload = envelope(event, SECRET, int(time.time()) - 301)
    if kind == "future":
        payload = envelope(event, SECRET, int(time.time()) + 301)
    if kind == "unknown_event":
        event["event_id"] = str(uuid4())
        payload = envelope(event, SECRET)
    if kind == "unknown_payload":
        event["lead"]["name"] = "Different Name"
        payload = envelope(event, SECRET)
    if kind == "bad_signature_shape":
        payload["signature"] = "invalid"
    if kind == "oversized":
        payload["event"]["extra"] = "a" * 16385
    response = client.post("/api/automation/process", json=payload, headers=headers)
    assert response.status_code == expected
    with sqlite3.connect(settings.demo_db_path) as db:
        assert db.execute("SELECT count(*) FROM workflow_receipts").fetchone()[0] == 0


def test_receiver_is_disabled_and_not_available_to_remote_peers(settings):
    settings.automation_enabled = False
    with TestClient(create_app(settings, start_automation_worker=False), client=("127.0.0.1", 1)) as client:
        send(client)
        payload = envelope(saved_event(settings), SECRET)
        assert (
            client.post("/api/automation/process", json=payload, headers={"X-LeadFlow-Token": SECRET}).status_code
            == 401
        )
    settings.automation_enabled = True
    with TestClient(create_app(settings, start_automation_worker=False), client=("192.0.2.1", 1)) as client:
        assert (
            client.post("/api/automation/process", json=payload, headers={"X-LeadFlow-Token": SECRET}).status_code
            == 403
        )


def test_concurrent_callbacks_have_one_effect(client, settings):
    send(client)
    event = saved_event(settings)

    async def scenario():
        results = await asyncio.gather(*(Outbox(settings.demo_db_path).process(event) for _ in range(8)))
        assert sum(not item["duplicate"] for item in results) == 1

    asyncio.run(scenario())


def test_leases_exclude_other_workers_and_old_worker_cannot_ack(client, settings):
    send(client)

    async def scenario():
        queue = Outbox(settings.demo_db_path)
        jobs = await asyncio.gather(*(queue.claim(now=10) for _ in range(5)))
        claimed = [job for job in jobs if job]
        assert len(claimed) == 1
        assert await queue.claim(now=69) is None
        reclaimed = await queue.claim(now=71)
        assert reclaimed["id"] == claimed[0]["id"] and reclaimed["lease_token"] != claimed[0]["lease_token"]
        await queue.process(reclaimed["event"])
        assert await queue.finish(claimed[0]) is False
        assert await queue.finish(reclaimed) is True
        assert (await queue.status())["counts"]["delivered"] == 1

    asyncio.run(scenario())


def test_dead_letter_backoff_and_manual_retry_keep_the_same_event(client, settings):
    send(client)

    async def scenario():
        queue = Outbox(settings.demo_db_path)
        job = await queue.claim(max_attempts=1, now=10)
        await queue.finish(job, "connection_error", max_attempts=1, now=10)
        assert (await queue.status())["counts"]["dead"] == 1
        assert await queue.claim(now=100) is None
        assert await queue.retry(job["id"]) is True
        assert (await queue.claim(now=101))["id"] == job["id"]
        assert await queue.retry(str(uuid4())) is False

    asyncio.run(scenario())


def test_retry_delays_are_respected_and_last_attempt_crash_is_recoverable(client, settings):
    send(client)

    async def scenario():
        queue = Outbox(settings.demo_db_path)
        job = await queue.claim(now=10)
        await queue.finish(job, "http_503", now=10)
        assert await queue.claim(now=11) is None
        again = await queue.claim(max_attempts=2, now=13)
        assert again["attempts"] == 2
        assert await queue.claim(max_attempts=2, now=74) is None
        assert (await queue.status())["counts"]["dead"] == 1
        assert await queue.retry(again["id"])

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mode",
    [
        "success",
        "timeout_after_effect",
        "server_error",
        "invalid_ack",
        "ack_without_receipt",
        "wrong_event_id",
        "redirect",
    ],
)
def test_delivery_worker_requires_a_matching_ack_and_committed_effect(client, settings, mode):
    send(client)

    async def scenario():
        queue = Outbox(settings.demo_db_path)

        async def handler(request):
            assert request.url.host == "127.0.0.1"
            assert request.headers["X-LeadFlow-Token"] == SECRET
            payload = json.loads(request.content)
            assert payload["signature"] == signature(payload["event"], payload["timestamp"], SECRET)
            if mode == "server_error":
                return httpx.Response(503, json={"detail": "private error"})
            if mode == "redirect":
                return httpx.Response(302, headers={"Location": "https://outside.example"})
            if mode == "invalid_ack":
                return httpx.Response(200, json={"message": "Workflow was started"})
            if mode == "ack_without_receipt":
                return httpx.Response(200, json={"processed": True, "event_id": payload["event"]["event_id"]})
            result = await queue.process(payload["event"])
            if mode == "timeout_after_effect":
                raise httpx.ReadTimeout("test timeout")
            if mode == "wrong_event_id":
                result["event_id"] = str(uuid4())
            return httpx.Response(200, json=result)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            assert await Worker(settings, http).once() is True
            status = await queue.status()
            assert status["counts"]["delivered"] == (1 if mode == "success" else 0)
            if mode != "success":
                assert status["counts"]["pending"] == 1
                assert SECRET not in str(status) and "private error" not in str(status)
            if mode == "timeout_after_effect":
                # Delivery failed AFTER commit. A retry has no second business effect.
                event = saved_event(settings)
                assert (await queue.process(event))["duplicate"] is True
                assert (await queue.status())["processed"] == 1

    asyncio.run(scenario())


def test_outbox_and_receipts_survive_restarts_without_backfilling_old_leads(client, settings):
    send(client)
    event = saved_event(settings)
    asyncio.run(Outbox(settings.demo_db_path).process(event))
    asyncio.run(DemoRepository(settings.demo_db_path).initialize())
    assert asyncio.run(Outbox(settings.demo_db_path).process(event))["duplicate"] is True
    assert asyncio.run(Outbox(settings.demo_db_path).status())["counts"]["pending"] == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://outside.example/webhook/test",
        "http://192.0.2.1/webhook/test",
        "http://127.0.0.1:5678/webhook-test/test",
        "http://user:pass@localhost:5678/webhook/test",
        "http://127.0.0.1:5678/webhook/test?token=secret",
    ],
)
def test_nonlocal_or_unsafe_delivery_configuration_fails(url):
    with pytest.raises(ValueError):
        Settings(automation_enabled=True, n8n_webhook_url=url, n8n_webhook_secret=SECRET)


def test_incomplete_or_cloud_automation_configuration_fails():
    with pytest.raises(ValueError):
        Settings(automation_enabled=True)
    with pytest.raises(ValueError):
        Settings(automation_enabled=True, app_env="production", n8n_webhook_secret=SECRET)


def test_n8n_prepare_preserves_admin_config_and_never_rotates_existing_secret(tmp_path, monkeypatch):
    from app.n8n_local import prepare

    path = tmp_path / ".env"
    path.write_text("ADMIN_EMAIL='admin@example.com'\nADMIN_PASSWORD_HASH='existing-hash'\n")
    monkeypatch.setenv("LEADFLOW_ENV_FILE", str(path))
    monkeypatch.delenv("N8N_WEBHOOK_SECRET", raising=False)
    first = prepare()
    second = prepare()
    assert first.admin_password_hash.get_secret_value() == "existing-hash"
    assert first.n8n_webhook_secret.get_secret_value() == second.n8n_webhook_secret.get_secret_value()
    assert len(first.n8n_webhook_secret.get_secret_value()) >= 32
    assert second.automation_enabled is False
    assert path.stat().st_mode & 0o777 == 0o600


def test_n8n_runtime_is_local_and_does_not_save_payloads(tmp_path, monkeypatch):
    from app.n8n_local import runtime_environment

    monkeypatch.setenv("LEADFLOW_N8N_DATA_DIR", str(tmp_path / "n8n"))
    monkeypatch.setenv("LEADFLOW_N8N_PORT", "5680")
    environment = runtime_environment()
    assert environment["N8N_LISTEN_ADDRESS"] == environment["N8N_RUNNERS_BROKER_LISTEN_ADDRESS"] == "127.0.0.1"
    assert environment["N8N_RUNNERS_BROKER_PORT"] != environment["N8N_PORT"]
    assert environment["N8N_COMMUNITY_PACKAGES_ENABLED"] == "false"
    assert environment["EXECUTIONS_DATA_SAVE_ON_SUCCESS"] == environment["EXECUTIONS_DATA_SAVE_ON_ERROR"] == "none"
    assert environment["EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS"] == "false"
    assert environment["EXECUTIONS_DATA_PRUNE"] == "false"
    assert "code" not in environment["NODES_INCLUDE"]


@pytest.mark.parametrize("port,broker", [("5678", "5678"), ("65535", "65635"), ("80", "5780")])
def test_n8n_rejects_invalid_or_colliding_ports(tmp_path, monkeypatch, port, broker):
    from app.n8n_local import runtime_environment

    monkeypatch.setenv("LEADFLOW_N8N_DATA_DIR", str(tmp_path / "n8n"))
    monkeypatch.setenv("LEADFLOW_N8N_PORT", port)
    monkeypatch.setenv("LEADFLOW_N8N_BROKER_PORT", broker)
    with pytest.raises(ValueError):
        runtime_environment()
