"""Project-scoped n8n setup/start. Never installs globally or prints secrets."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
from urllib.parse import urlparse

from dotenv import dotenv_values, set_key

from .config import PROJECT_ROOT, Settings

WORKFLOW_ID = "LeadFlowLocalDemo01"
CREDENTIAL_ID = "LeadFlowLocalToken01"
N8N_BIN = PROJECT_ROOT / "automation/n8n/node_modules/n8n/bin/n8n"


def data_dir():
    # Test suites override this with an ignored work/ path, never the user's n8n database.
    path = Path(os.getenv("LEADFLOW_N8N_DATA_DIR", str(PROJECT_ROOT / "automation/data")))
    return path if path.is_absolute() else PROJECT_ROOT / path


def runtime_environment():
    root = data_dir()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    port = int(os.getenv("LEADFLOW_N8N_PORT", "5678"))
    if not 1024 <= port <= 65535:
        raise ValueError("Kies een lokale n8n-poort tussen 1024 en 65535.")
    broker_port = int(os.getenv("LEADFLOW_N8N_BROKER_PORT", str(port + 100)))
    if not 1024 <= broker_port <= 65535 or broker_port == port:
        raise ValueError("De lokale runnerpoort moet geldig zijn en verschillen van de n8n-poort.")
    environment = {
        **os.environ,
        "N8N_USER_FOLDER": str(root),
        "N8N_LISTEN_ADDRESS": "127.0.0.1",
        "N8N_HOST": "127.0.0.1",
        "N8N_PORT": str(port),
        "N8N_PROTOCOL": "http",
        "N8N_SECURE_COOKIE": "false",
        "N8N_EDITOR_BASE_URL": f"http://127.0.0.1:{port}",
        "N8N_WEBHOOK_URL": f"http://127.0.0.1:{port}/",
        "N8N_DIAGNOSTICS_ENABLED": "false",
        "N8N_VERSION_NOTIFICATIONS_ENABLED": "false",
        "N8N_TEMPLATES_ENABLED": "false",
        "N8N_PERSONALIZATION_ENABLED": "false",
        "N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS": "true",
        "N8N_COMMUNITY_PACKAGES_ENABLED": "false",
        "N8N_UNVERIFIED_PACKAGES_ENABLED": "false",
        "NODES_INCLUDE": '["n8n-nodes-base.webhook","n8n-nodes-base.httpRequest","n8n-nodes-base.respondToWebhook"]',
        # Pruning uses delayed soft deletion; false makes unsaved production runs hard-delete immediately.
        "EXECUTIONS_DATA_PRUNE": "false",
        # n8n may persist in-flight data; completed production payloads must not be retained.
        "EXECUTIONS_DATA_SAVE_ON_SUCCESS": "none",
        "EXECUTIONS_DATA_SAVE_ON_ERROR": "none",
        "EXECUTIONS_DATA_SAVE_ON_PROGRESS": "false",
        "EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS": "false",
        "N8N_RUNNERS_BROKER_PORT": str(broker_port),
        "N8N_RUNNERS_BROKER_LISTEN_ADDRESS": "127.0.0.1",
        "N8N_HIRING_BANNER_ENABLED": "false",
        "N8N_BLOCK_ENV_ACCESS_IN_NODE": "true",
        "NO_PROXY": "localhost,127.0.0.1,::1",
    }
    return environment


def prepare():
    settings = Settings.load()
    path = settings.env_file
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.parent / ".leadflow-setup.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(descriptor)
        os.chmod(path, 0o600)
        values = dotenv_values(path)
        if not values.get("N8N_WEBHOOK_SECRET") and not os.getenv("N8N_WEBHOOK_SECRET"):
            set_key(str(path), "N8N_WEBHOOK_SECRET", secrets.token_urlsafe(48))
        if not values.get("N8N_WEBHOOK_URL") and not os.getenv("N8N_WEBHOOK_URL"):
            set_key(str(path), "N8N_WEBHOOK_URL", "http://127.0.0.1:5678/webhook/magnifize-leadflow")
        if not values.get("AUTOMATION_ENABLED") and not os.getenv("AUTOMATION_ENABLED"):
            set_key(str(path), "AUTOMATION_ENABLED", "false")
    return Settings.load()


def run_cli(arguments, secret):
    node = shutil.which("node")
    if not node or not N8N_BIN.is_file():
        raise RuntimeError("n8n ontbreekt. Voer vanuit de projectmap uit: npm ci --prefix automation/n8n")
    result = subprocess.run(
        [node, str(N8N_BIN), *arguments],
        cwd=PROJECT_ROOT,
        env=runtime_environment(),
        text=True,
        capture_output=True,
        timeout=180,
    )
    output = (result.stdout + result.stderr).replace(secret, "[redacted]")
    if result.returncode or "An error occurred" in output:
        raise RuntimeError(f"n8n {arguments[0]} mislukt: {output[-1600:]}")
    return output


def setup():
    settings = prepare()
    secret = settings.n8n_webhook_secret.get_secret_value()
    if len(secret) < 32:
        raise ValueError("De bestaande webhooksecret is te kort; vraag hulp zonder de sleutel te delen.")
    database = data_dir() / ".n8n/database.sqlite"
    if database.exists():
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as db:
            table = db.execute("SELECT name FROM sqlite_master WHERE name='workflow_entity'").fetchone()
            if table and db.execute("SELECT 1 FROM workflow_entity WHERE id=?", (WORKFLOW_ID,)).fetchone():
                print("De LeadFlow-workflow bestaat al; bestaande workflowinstellingen zijn niet overschreven.")
                return
    api_url = os.getenv("LEADFLOW_AUTOMATION_API_URL", "http://127.0.0.1:8000")
    target = urlparse(api_url)
    if (
        target.scheme != "http"
        or target.hostname not in {"127.0.0.1", "localhost", "::1"}
        or target.username
        or target.password
        or target.query
        or target.fragment
        or target.path not in {"", "/"}
    ):
        raise ValueError("De callback-API moet een lokale HTTP-URL zijn.")
    workflow = json.loads((PROJECT_ROOT / "outputs/leadflow-n8n-workflow.json").read_text())
    for node in workflow.get("nodes", []):
        if "credentials" in node:
            node["credentials"] = {
                kind: {"id": CREDENTIAL_ID, "name": "LeadFlow local demo"} for kind in node["credentials"]
            }
    workflow["nodes"][1]["parameters"]["url"] = api_url.rstrip("/") + "/api/automation/process"
    credential = [
        {
            "id": CREDENTIAL_ID,
            "name": "LeadFlow lokale webhook",
            "type": "httpHeaderAuth",
            "data": {"name": "X-LeadFlow-Token", "value": secret},
        }
    ]
    scratch = PROJECT_ROOT / "work"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="n8n-import-", dir=scratch) as temporary:
        # Private temporary files disappear after import; credentials live encrypted in n8n.
        credentials_file = Path(temporary) / "credentials.json"
        workflow_file = Path(temporary) / "workflow.json"
        credentials_file.write_text(json.dumps(credential))
        credentials_file.chmod(0o600)
        workflow_file.write_text(json.dumps(workflow))
        output = run_cli(["import:credentials", f"--input={credentials_file}"], secret)
        if "Successfully imported 1" not in output:
            raise RuntimeError("Credentialimport niet bevestigd; de koppeling is niet ingeschakeld.")
        output = run_cli(["import:workflow", f"--input={workflow_file}"], secret)
        if "Successfully imported 1" not in output:
            raise RuntimeError("Workflowimport niet bevestigd; de koppeling is niet ingeschakeld.")
        run_cli(["publish:workflow", f"--id={WORKFLOW_ID}"], secret)
    set_key(str(settings.env_file), "AUTOMATION_ENABLED", "true")
    settings.env_file.chmod(0o600)
    print("LeadFlow-workflow en beveiligde credential zijn ingesteld en gepubliceerd.")
    print("Herstart de backend en start n8n. Je bestaande beheeraccount is behouden.")


def main():
    parser = argparse.ArgumentParser(description="Start n8n veilig binnen dit LeadFlow-project")
    parser.add_argument("command", choices=["setup", "start"])
    args = parser.parse_args()
    try:
        if args.command == "setup":
            setup()
        else:
            node = shutil.which("node")
            if not node or not N8N_BIN.is_file():
                raise RuntimeError("n8n is nog niet geïnstalleerd in automation/n8n.")
            os.chdir(PROJECT_ROOT)
            os.execve(node, [node, str(N8N_BIN), "start"], runtime_environment())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
