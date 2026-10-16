import asyncio
import sqlite3
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import LeadCreate
from app.repository import DemoRepository, IdempotencyConflict, StorageUnavailable, SupabaseRepository

PAYLOAD = {"name": "Amina Jansen", "email": "amina@example.com", "company_name": "Northstar BV", "description": "We willen inkomende aanvragen automatisch verdelen."}


@pytest.fixture
def settings(tmp_path):
    return Settings(app_env="test", demo_db_path=tmp_path / "leads.sqlite3")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def send(client, payload=None, key=None):
    return client.post("/api/leads", json=payload if payload is not None else PAYLOAD, headers={"Idempotency-Key": str(key or uuid4())})


def test_intake_is_saved_and_normalized(client, settings):
    result = send(client, {**PAYLOAD, "name": "  Amina Jansen  "})
    assert result.status_code == 201
    assert result.json()["status"] == "new"
    assert result.json()["duplicate"] is False
    with sqlite3.connect(settings.demo_db_path) as db:
        assert db.execute("select name, email from leads").fetchone() == ("Amina Jansen", "amina@example.com")


@pytest.mark.parametrize("field,value", [("name", "a"), ("name", "  "), ("name", 123), ("name", "A\x00B"), ("email", "no-email"), ("company_name", " "), ("description", "short"), ("description", "a" * 2001)])
def test_invalid_input_is_not_saved(client, settings, field, value):
    result = send(client, {**PAYLOAD, field: value})
    assert result.status_code == 422
    assert field in [error["field"] for error in result.json()["errors"]]
    assert "input" not in result.text
    with sqlite3.connect(settings.demo_db_path) as db:
        assert db.execute("select count(*) from leads").fetchone()[0] == 0


def test_status_cannot_be_set_by_public_user(client):
    assert send(client, {**PAYLOAD, "status": "qualified"}).status_code == 422


@pytest.mark.parametrize("key", [None, "not-a-uuid", str(uuid4()).replace("-", "")[:16]])
def test_key_is_required(client, key):
    result = client.post("/api/leads", json=PAYLOAD, headers={"Idempotency-Key": key} if key else {})
    assert result.status_code == 400


def test_retry_returns_original_lead_and_one_row(client, settings):
    key = uuid4()
    first = send(client, key=key)
    retry = send(client, key=key)
    assert retry.status_code == 200
    assert retry.json()["duplicate"] is True
    assert first.json()["id"] == retry.json()["id"]
    with sqlite3.connect(settings.demo_db_path) as db:
        assert db.execute("select count(*) from leads").fetchone()[0] == 1


def test_different_content_with_same_key_is_conflict(client):
    key = uuid4()
    assert send(client, key=key).status_code == 201
    assert send(client, {**PAYLOAD, "name": "Andere Naam"}, key).status_code == 409


def test_retry_survives_backend_restart(settings):
    key = uuid4()
    with TestClient(create_app(settings)) as first:
        created = send(first, key=key).json()
    with TestClient(create_app(settings)) as restarted:
        retry = send(restarted, key=key)
        assert retry.status_code == 200
        assert retry.json()["id"] == created["id"]


def test_concurrent_submissions_are_atomic(settings):
    async def scenario():
        repository = DemoRepository(settings.demo_db_path)
        await repository.initialize()
        key = uuid4()
        results = await asyncio.gather(*(repository.create(LeadCreate(**PAYLOAD), key) for _ in range(8)))
        assert len({result.id for result in results}) == 1
        assert sum(not result.duplicate for result in results) == 1
    asyncio.run(scenario())


def test_storage_failure_has_actionable_safe_error(client):
    class Unavailable:
        async def create(self, lead, key):
            raise StorageUnavailable("SECRET-DO-NOT-ECHO")
    client.app.state.repository = Unavailable()
    result = send(client)
    assert result.status_code == 503
    assert "SECRET" not in result.text


def test_malformed_json(client):
    result = client.post("/api/leads", content="{not json", headers={"Content-Type": "application/json"})
    assert result.status_code == 422


def test_large_request_is_rejected(client):
    result = client.post("/api/leads", content="a" * 16385)
    assert result.status_code == 413


def test_cors_allows_only_configured_origins(client):
    for origin, allowed in [("http://localhost:3000", True), ("https://other.example", False)]:
        result = client.options("/api/leads", headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type,Idempotency-Key"})
        assert (result.headers.get("access-control-allow-origin") == origin) == allowed


def test_rate_limit_and_cors_on_errors(settings):
    settings.rate_limit_per_minute = 1
    with TestClient(create_app(settings)) as client:
        assert send(client).status_code == 201
        result = client.post("/api/leads", json=PAYLOAD, headers={"Origin": "http://localhost:3000"})
        assert result.status_code == 429
        assert result.headers["Retry-After"] == "60"
        assert result.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_no_public_lead_listing(client):
    assert client.get("/api/leads").status_code == 405
    assert client.get("/health").json() == {"status": "ok", "storage": "demo"}


@pytest.mark.parametrize("configuration", [{"app_env": "production"}, {"storage_mode": "supabase"}, {"allowed_origins": ["*"]}])
def test_unsafe_or_incomplete_configuration_fails(configuration):
    with pytest.raises(ValueError):
        Settings(**configuration)


def test_environment_file_is_loaded_from_root(tmp_path, monkeypatch):
    import app.config as config
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "dotenv_values", lambda path: {"STORAGE_MODE": "demo", "RATE_LIMIT_PER_MINUTE": "11"})
    monkeypatch.delenv("RATE_LIMIT_PER_MINUTE", raising=False)
    assert Settings.load().rate_limit_per_minute == 11
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "12")
    assert Settings.load().rate_limit_per_minute == 12


@pytest.mark.parametrize("status,body,expected", [
    (200, {"id": "651bdaf0-f0c4-4044-b751-bf6384c97e9b", "status": "new", "duplicate": False}, None),
    (409, {"code": "23505"}, IdempotencyConflict),
    (401, {"message": "bad key"}, StorageUnavailable),
    (500, {"message": "private DB details"}, StorageUnavailable),
    (200, {"bad": "shape"}, StorageUnavailable),
])
def test_supabase_adapter_contract_without_external_calls(status, body, expected):
    def handler(request):
        assert request.url.path == "/rest/v1/rpc/submit_lead"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(status, json=body)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            repository = SupabaseRepository("https://example.supabase.co", "test-key", client)
            if expected:
                with pytest.raises(expected):
                    await repository.create(LeadCreate(**PAYLOAD), uuid4())
            else:
                assert (await repository.create(LeadCreate(**PAYLOAD), uuid4())).status == "new"
    asyncio.run(scenario())
