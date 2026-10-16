"""Opt-in real n8n integration; no changes to user accounts, data, or servers."""
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

import httpx
import pytest

from app.automation import envelope
from app.config import PROJECT_ROOT
from dotenv import dotenv_values

pytestmark = pytest.mark.skipif(os.getenv("RUN_N8N_INTEGRATION") != "1", reason="Opt-in local n8n integration")
API = "http://127.0.0.1:8003"
N8N = "http://127.0.0.1:5680"


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def wait_until(check, seconds=60):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return
        time.sleep(0.25)
    pytest.fail("Lokale integratievoorwaarde niet op tijd bevestigd; geen secrets of payloads gelogd.")


def test_real_n8n_retry_auth_and_one_effect():
    assert shutil.which("node"), "Node.js 24 nodig"
    assert (PROJECT_ROOT / "automation/n8n/node_modules/n8n/bin/n8n").is_file(), "Installeer eerst n8n"
    for port in (8003, 5680, 5780):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
    with tempfile.TemporaryDirectory(prefix="leadflow-n8n-test-") as directory:
        root = Path(directory)
        db_path = root / "leads.sqlite3"
        env_path = root / ".env"
        environment = {**os.environ, "APP_ENV": "test", "DEMO_DB_PATH": str(db_path),
                       "LEADFLOW_ENV_FILE": str(env_path), "LEADFLOW_N8N_DATA_DIR": str(root / "n8n"),
                       "LEADFLOW_N8N_PORT": "5680", "LEADFLOW_N8N_BROKER_PORT": "5780",
                       "LEADFLOW_AUTOMATION_API_URL": API, "N8N_WEBHOOK_URL": N8N + "/webhook/magnifize-leadflow",
                       "RATE_LIMIT_PER_MINUTE": "1000"}
        # Do not inherit user secrets or opt-in flags; setup generates a fresh private test secret.
        for key in ("ADMIN_EMAIL", "ADMIN_PASSWORD_HASH", "N8N_WEBHOOK_SECRET", "AUTOMATION_ENABLED"):
            environment.pop(key, None)
        backend = n8n = None
        with open(root / "servers.log", "w") as log, httpx.Client(trust_env=False, timeout=15) as client:
            try:
                setup = subprocess.run([sys.executable, "-m", "app.n8n_local", "setup"],
                    cwd=PROJECT_ROOT / "backend", env=environment, capture_output=True, text=True, timeout=180)
                assert setup.returncode == 0, "Geïsoleerde n8n-setup mislukt"
                secret = dotenv_values(env_path)["N8N_WEBHOOK_SECRET"]
                backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8003"],
                    cwd=PROJECT_ROOT / "backend", env=environment, stdout=log, stderr=log)

                def healthy(url):
                    try:
                        return client.get(url).status_code == 200
                    except httpx.HTTPError:
                        return False

                wait_until(lambda: healthy(API + "/health"))
                payload = {"name": "Lokale Workflowtest", "email": "workflow@example.com", "company_name": "Fictief Testbedrijf",
                           "description": "Met spoed onze aanvragen automatisch verwerken."}
                key = str(uuid4())
                response = client.post(API + "/api/leads", json=payload, headers={"Idempotency-Key": key})
                assert response.status_code == 201

                def row():
                    with sqlite3.connect(db_path) as db:
                        return db.execute("SELECT state, attempts, payload FROM lead_events").fetchone()

                # n8n is intentionally stopped: lead is saved and queue records a failed attempt.
                wait_until(lambda: row()[1] >= 1)
                assert row()[0] == "pending"

                def start_n8n():
                    return subprocess.Popen([sys.executable, "-m", "app.n8n_local", "start"],
                        cwd=PROJECT_ROOT / "backend", env=environment, stdout=log, stderr=log)

                n8n = start_n8n()
                wait_until(lambda: healthy(N8N + "/healthz"))
                wait_until(lambda: row()[0] == "delivered")
                assert row()[1] >= 2
                again = client.post(API + "/api/leads", json=payload, headers={"Idempotency-Key": key})
                assert again.status_code == 200 and again.json()["id"] == response.json()["id"]
                event = json.loads(row()[2])
                ack = client.post(N8N + "/webhook/magnifize-leadflow", json=envelope(event, secret), headers={"X-LeadFlow-Token": secret})
                assert ack.status_code == 200 and ack.json()["duplicate"] is True
                assert ack.json()["result"]["priority"] == "review_urgency"
                denied = client.post(N8N + "/webhook/magnifize-leadflow", json=envelope(event, secret), headers={"X-LeadFlow-Token": "invalid"})
                assert denied.status_code in {401, 403}
                tampered = envelope(json.loads(row()[2]), secret)
                tampered["event"]["lead"]["name"] = "Tampered"
                invalid = client.post(API + "/api/automation/process", json=tampered, headers={"X-LeadFlow-Token": secret})
                assert invalid.status_code == 401
                stop(n8n)
                n8n = start_n8n()
                wait_until(lambda: healthy(N8N + "/healthz"))
                # HTTP health can be ready before the published workflow has registered.
                def restarted_workflow():
                    try:
                        ack = client.post(N8N + "/webhook/magnifize-leadflow", json=envelope(event, secret), headers={"X-LeadFlow-Token": secret})
                        return ack.status_code == 200 and ack.json().get("duplicate") is True
                    except (httpx.HTTPError, ValueError):
                        return False
                wait_until(restarted_workflow)
                with sqlite3.connect(db_path) as db:
                    assert db.execute("SELECT count(*) FROM leads").fetchone()[0] == 1
                    assert db.execute("SELECT count(*) FROM lead_events").fetchone()[0] == 1
                    assert db.execute("SELECT count(*) FROM workflow_receipts").fetchone()[0] == 1
                    assert db.execute("SELECT status FROM leads").fetchone()[0] == "new"
                # Response arrives before workflow finalization. Wait for hard deletion of in-flight data.
                def no_retained_payloads():
                    with sqlite3.connect(root / "n8n/.n8n/database.sqlite") as db:
                        return db.execute("SELECT count(*) FROM execution_data").fetchone()[0] == 0
                wait_until(no_retained_payloads)
            finally:
                stop(n8n)
                stop(backend)
