import asyncio
import sqlite3
from uuid import UUID, uuid4

import httpx
import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.auth import COOKIE, hash_password, verify_password
from app.config import Settings
from app.main import create_app
from app.models import LeadCreate, StatusUpdate
from app.repository import DemoRepository, StorageUnavailable, VersionConflict
from test_api import PAYLOAD, send

ORIGIN = {"Origin": "http://localhost:3000"}
CREDENTIALS = {"email": "admin@example.com", "password": "Local-test-passphrase-2026"}


@pytest.fixture(scope="module")
def password_hash():
    return hash_password(CREDENTIALS["password"])


@pytest.fixture
def settings(tmp_path, password_hash):
    return Settings(
        app_env="test",
        demo_db_path=tmp_path / "leads.sqlite3",
        env_file=tmp_path / ".env",
        admin_email=CREDENTIALS["email"],
        admin_password_hash=SecretStr(password_hash),
        auth_rate_limit_per_minute=100,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), client=("127.0.0.1", 12345)) as client:
        yield client


def login(client):
    response = client.post("/api/admin/login", json=CREDENTIALS, headers=ORIGIN)
    assert response.status_code == 200
    return {**ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


def test_first_account_setup_persists_hash_and_does_not_replace_config(settings, monkeypatch):
    settings.admin_email = ""
    settings.admin_password_hash = SecretStr("")
    settings.env_file.write_text("RATE_LIMIT_PER_MINUTE=17\n", encoding="utf-8")
    with TestClient(create_app(settings), client=("127.0.0.1", 1)) as client:
        assert client.get("/api/admin/session").json()["setup_required"] is True
        assert (
            client.post("/api/admin/setup", json={**CREDENTIALS, "password": "short"}, headers=ORIGIN).status_code
            == 422
        )
        created = client.post("/api/admin/setup", json=CREDENTIALS, headers=ORIGIN)
        assert created.status_code == 201
        assert client.get("/api/admin/leads").status_code == 200
        assert client.post("/api/admin/setup", json=CREDENTIALS, headers=ORIGIN).status_code == 409
    values = dotenv_values(settings.env_file)
    assert values["RATE_LIMIT_PER_MINUTE"] == "17"
    assert values["ADMIN_EMAIL"] == CREDENTIALS["email"]
    assert verify_password(CREDENTIALS["password"], values["ADMIN_PASSWORD_HASH"])
    assert CREDENTIALS["password"] not in settings.env_file.read_text()
    assert settings.env_file.stat().st_mode & 0o777 == 0o600
    monkeypatch.setenv("LEADFLOW_ENV_FILE", str(settings.env_file))
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
    restored = Settings.load()
    assert restored.admin_email == CREDENTIALS["email"]
    assert verify_password(CREDENTIALS["password"], restored.admin_password_hash.get_secret_value())


def test_account_disk_failure_returns_safe_error_without_session(settings, monkeypatch):
    settings.admin_password_hash = SecretStr("")
    app = create_app(settings)

    def fail(*args):
        raise OSError("private disk details")

    monkeypatch.setattr(app.state.auth, "_persist", fail)
    with TestClient(app, client=("127.0.0.1", 1)) as client:
        response = client.post("/api/admin/setup", json=CREDENTIALS, headers=ORIGIN)
        assert response.status_code == 503 and "private" not in response.text
        assert client.cookies.get(COOKIE) is None
        assert client.get("/api/admin/session").json()["setup_required"] is True


def test_setup_lock_prevents_overwriting_an_existing_disk_account(settings):
    settings.env_file.write_text("ADMIN_PASSWORD_HASH='existing-hash'\n", encoding="utf-8")
    settings.admin_password_hash = SecretStr("")
    with TestClient(create_app(settings), client=("127.0.0.1", 1)) as client:
        result = client.post("/api/admin/setup", json=CREDENTIALS, headers=ORIGIN)
        assert result.status_code == 409
        assert dotenv_values(settings.env_file)["ADMIN_PASSWORD_HASH"] == "existing-hash"


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/admin/leads", "get"),
        (f"/api/admin/leads/{uuid4()}", "get"),
        (f"/api/admin/leads/{uuid4()}/status", "patch"),
    ],
)
def test_personal_data_and_status_writes_require_authentication(client, path, method):
    result = getattr(client, method)(path)
    assert result.status_code == 401
    assert "items" not in result.json()


def test_cookie_logout_rotation_and_expiry(client):
    headers = login(client)
    old_cookie = client.cookies.get(COOKIE)
    assert client.get("/api/admin/session").json()["email"] == CREDENTIALS["email"]
    result = client.post("/api/admin/login", json=CREDENTIALS, headers=ORIGIN)
    assert "HttpOnly" in result.headers["set-cookie"] and "SameSite=strict" in result.headers["set-cookie"]
    assert "Path=/api/admin" in result.headers["set-cookie"]
    assert client.cookies.get(COOKIE) != old_cookie
    assert len(client.app.state.auth.sessions) == 1
    headers["X-CSRF-Token"] = result.json()["csrf_token"]
    assert client.post("/api/admin/logout", headers=headers).status_code == 200
    assert client.get("/api/admin/leads").status_code == 401
    login(client)
    next(iter(client.app.state.auth.sessions.values())).expires_at = 0
    assert client.get("/api/admin/leads").status_code == 401


def test_credentials_work_after_restart_but_old_session_does_not(settings):
    with TestClient(create_app(settings), client=("127.0.0.1", 1)) as first:
        login(first)
        cookies = first.cookies
    with TestClient(create_app(settings), client=("127.0.0.1", 1)) as second:
        second.cookies.update(cookies)
        assert second.get("/api/admin/session").status_code == 401
        login(second)
        assert second.get("/api/admin/leads").status_code == 200


@pytest.mark.parametrize(
    "changes", [{"password": "incorrect"}, {"email": "other@example.com"}, {"email": "é@example.com"}]
)
def test_invalid_login_is_generic_and_safe(client, changes):
    result = client.post("/api/admin/login", json={**CREDENTIALS, **changes}, headers=ORIGIN)
    assert result.status_code == 401
    assert result.json()["detail"] == "E-mailadres of wachtwoord klopt niet."
    assert CREDENTIALS["password"] not in result.text


def test_login_throttled(settings):
    settings.auth_rate_limit_per_minute = 1
    with TestClient(create_app(settings), client=("127.0.0.1", 1)) as client:
        login(client)
        response = client.post("/api/admin/login", json=CREDENTIALS, headers=ORIGIN)
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "60"


@pytest.mark.parametrize("headers", [{}, {"Origin": "https://evil.example"}])
def test_login_requires_trusted_origin(client, headers):
    assert client.post("/api/admin/login", json=CREDENTIALS, headers=headers).status_code == 403


def test_non_loopback_and_production_login_blocked(settings):
    with TestClient(create_app(settings), client=("192.0.2.1", 1)) as client:
        assert client.get("/api/admin/session").status_code == 403
    settings.app_env = "production"
    with TestClient(create_app(settings), client=("127.0.0.1", 1)) as client:
        assert client.get("/api/admin/session").status_code == 403


@pytest.mark.parametrize(
    "headers",
    [
        ORIGIN,
        {"Origin": "http://localhost:3000", "X-CSRF-Token": "wrong"},
        {"Origin": "https://evil.example", "X-CSRF-Token": "wrong"},
    ],
)
def test_status_and_logout_require_csrf(client, headers):
    login(client)
    lead = send(client).json()
    assert (
        client.patch(
            f"/api/admin/leads/{lead['id']}/status",
            json={"status": "qualified", "expected_version": 0},
            headers=headers,
        ).status_code
        == 403
    )
    assert client.post("/api/admin/logout", headers=headers).status_code == 403
    assert client.get(f"/api/admin/leads/{lead['id']}").json()["status"] == "new"


def test_list_search_filter_pagination_and_private_fields(client):
    login(client)
    for company in ["Northstar BV", "Magnifize Demo", "Southstar BV"]:
        send(client, {**PAYLOAD, "company_name": company})
    result = client.get("/api/admin/leads?page_size=2").json()
    assert result["total"] == 3 and len(result["items"]) == 2
    assert result["counts"] == {"new": 3, "contacted": 0, "qualified": 0, "closed": 0}
    assert len(client.get("/api/admin/leads?page=2&page_size=2").json()["items"]) == 1
    assert client.get("/api/admin/leads?q=MAGNIFIZE").json()["total"] == 1
    assert client.get("/api/admin/leads?q=%27%20OR%201=1%20--").json()["total"] == 0
    assert client.get("/api/admin/leads?status=qualified").json()["total"] == 0
    assert "payload_hash" not in str(result) and "idempotency_key" not in str(result)
    for query in ["status=invalid", "page=0", "page=999999999999999999999999", "page_size=101", "q=" + "a" * 101]:
        assert client.get("/api/admin/leads?" + query).status_code == 422


def test_detail_status_history_noop_and_conflict(client):
    headers = login(client)
    lead_id = send(client).json()["id"]
    detail = client.get(f"/api/admin/leads/{lead_id}").json()
    assert detail["history"] == [] and detail["version"] == 0
    path = f"/api/admin/leads/{lead_id}/status"
    changed = client.patch(path, json={"status": "contacted", "expected_version": 0}, headers=headers)
    assert changed.status_code == 200
    assert changed.json()["version"] == 1
    event = changed.json()["history"][0]
    assert (event["previous_status"], event["new_status"], event["actor"]) == ("new", "contacted", CREDENTIALS["email"])
    assert client.patch(path, json={"status": "qualified", "expected_version": 0}, headers=headers).status_code == 409
    unchanged = client.patch(path, json={"status": "contacted", "expected_version": 1}, headers=headers).json()
    assert unchanged["version"] == 1 and len(unchanged["history"]) == 1
    assert client.get(f"/api/admin/leads/{uuid4()}").status_code == 404
    assert (
        client.patch(
            f"/api/admin/leads/{uuid4()}/status", json={"status": "qualified", "expected_version": 0}, headers=headers
        ).status_code
        == 404
    )
    for payload in [
        {"status": "unknown", "expected_version": 1},
        {"status": "closed", "expected_version": -1},
        {"status": "closed", "expected_version": 1, "actor": "spoof@example.com"},
    ]:
        assert client.patch(path, json=payload, headers=headers).status_code == 422


def test_parallel_edits_have_one_winner_and_audit_is_atomic(settings):
    async def scenario():
        repo = DemoRepository(settings.demo_db_path)
        await repo.initialize()
        lead = await repo.create(LeadCreate(**PAYLOAD), uuid4())
        results = await asyncio.gather(
            *(
                repo.update_status(lead.id, StatusUpdate(status="contacted", expected_version=0), CREDENTIALS["email"])
                for _ in range(5)
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(item, VersionConflict) for item in results) == 4
        assert len((await repo.detail(lead.id)).history) == 1
        # A failed history insert must roll back the status change, too.
        with sqlite3.connect(settings.demo_db_path) as db:
            db.execute(
                "CREATE TRIGGER fail_audit BEFORE INSERT ON lead_status_events BEGIN SELECT RAISE(ABORT, 'test failure'); END"
            )
        with pytest.raises(StorageUnavailable):
            await repo.update_status(lead.id, StatusUpdate(status="closed", expected_version=1), CREDENTIALS["email"])
        detail = await repo.detail(lead.id)
        assert detail.status == "contacted" and detail.version == 1 and len(detail.history) == 1

    asyncio.run(scenario())


def test_migration_preserves_phase_one_leads(settings):
    with sqlite3.connect(settings.demo_db_path) as db:
        db.execute(
            "CREATE TABLE leads (id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, company_name TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', idempotency_key TEXT NOT NULL UNIQUE, payload_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        lead_id = str(uuid4())
        db.execute(
            "INSERT INTO leads (id, name, email, company_name, description, idempotency_key, payload_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (lead_id, *PAYLOAD.values(), str(uuid4()), "a" * 64),
        )

    async def scenario():
        repo = DemoRepository(settings.demo_db_path)
        await repo.initialize()
        await repo.initialize()
        detail = await repo.detail(UUID(lead_id))
        assert detail.company_name == PAYLOAD["company_name"] and detail.version == 0
        assert detail.updated_at == detail.created_at
        with sqlite3.connect(settings.demo_db_path) as db:
            assert db.execute("SELECT count(*) FROM lead_events").fetchone()[0] == 0

    asyncio.run(scenario())


def test_admin_storage_failure_is_safe(client):
    headers = login(client)

    class Unavailable:
        async def list(self, *args):
            raise StorageUnavailable("secret")

        async def detail(self, *args):
            raise StorageUnavailable("secret")

        async def update_status(self, *args):
            raise StorageUnavailable("secret")

    client.app.state.repository = Unavailable()
    for result in [
        client.get("/api/admin/leads"),
        client.get(f"/api/admin/leads/{uuid4()}"),
        client.patch(
            f"/api/admin/leads/{uuid4()}/status", json={"status": "closed", "expected_version": 0}, headers=headers
        ),
    ]:
        assert result.status_code == 503 and "secret" not in result.text
