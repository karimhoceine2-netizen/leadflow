import os
from urllib.parse import urlparse
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    app_env: str = "development"
    demo_db_path: Path = PROJECT_ROOT / "backend/data/leadflow.sqlite3"
    allowed_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    rate_limit_per_minute: int = Field(default=30, ge=1, le=1000)
    admin_email: str = ""
    admin_password_hash: SecretStr = SecretStr("")
    env_file: Path = PROJECT_ROOT / ".env"
    auth_rate_limit_per_minute: int = Field(default=5, ge=1, le=1000)
    automation_enabled: bool = False
    n8n_webhook_url: str = "http://127.0.0.1:5678/webhook/magnifize-leadflow"
    n8n_webhook_secret: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def validate_configuration(self):
        if self.app_env not in {"development", "production", "test"}:
            raise ValueError("APP_ENV must be development, production or test")
        if self.app_env == "production":
            raise ValueError("This showcase is a local SQLite demo; APP_ENV=production is not supported")
        if not self.allowed_origins or "*" in self.allowed_origins:
            raise ValueError("ALLOWED_ORIGINS requires explicit origins")
        if self.automation_enabled:
            target = urlparse(self.n8n_webhook_url)
            if target.scheme != "http" or target.hostname not in {"127.0.0.1", "localhost", "::1"} or target.username or target.password or target.query or target.fragment or not target.path.startswith("/webhook/"):
                raise ValueError("Local n8n requires an HTTP loopback production webhook URL")
            if len(self.n8n_webhook_secret.get_secret_value()) < 32:
                raise ValueError("N8N_WEBHOOK_SECRET must have at least 32 characters")
        return self

    @classmethod
    def load(cls):
        env_file = Path(os.getenv("LEADFLOW_ENV_FILE", str(PROJECT_ROOT / ".env")))
        env_file = env_file if env_file.is_absolute() else PROJECT_ROOT / env_file
        values = {**dotenv_values(env_file), **os.environ}
        path = Path(values.get("DEMO_DB_PATH") or "backend/data/leadflow.sqlite3")
        return cls(
            app_env=values.get("APP_ENV", "development"),
            demo_db_path=path if path.is_absolute() else PROJECT_ROOT / path,
            allowed_origins=[item.strip() for item in (values.get("ALLOWED_ORIGINS") or "http://localhost:3000,http://127.0.0.1:3000").split(",") if item.strip()],
            rate_limit_per_minute=values.get("RATE_LIMIT_PER_MINUTE", "30"),
            admin_email=(values.get("ADMIN_EMAIL") or "").lower(),
            admin_password_hash=SecretStr(values.get("ADMIN_PASSWORD_HASH") or ""),
            env_file=env_file,
            auth_rate_limit_per_minute=values.get("AUTH_RATE_LIMIT_PER_MINUTE", "5"),
            automation_enabled=values.get("AUTOMATION_ENABLED") or "false",
            n8n_webhook_url=values.get("N8N_WEBHOOK_URL") or "http://127.0.0.1:5678/webhook/magnifize-leadflow",
            n8n_webhook_secret=values.get("N8N_WEBHOOK_SECRET") or "",
        )
