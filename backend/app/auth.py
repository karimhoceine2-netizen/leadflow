"""Local demo authentication; no browser-visible password hashes or session tokens."""
import asyncio
import hashlib
import hmac
import ipaddress
import secrets
import time
from dataclasses import dataclass

from dotenv import dotenv_values, set_key
from fastapi import HTTPException, Request, Response
from pydantic import SecretStr

from .config import Settings

COOKIE = "leadflow_admin"
SESSION_SECONDS = 3600
ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not 600_000 <= int(rounds) <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


@dataclass
class Session:
    email: str
    csrf: str
    expires_at: float


class LocalAuth:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.sessions: dict[str, Session] = {}
        self.setup_lock = asyncio.Lock()

    @property
    def configured(self):
        return bool(self.settings.admin_email and self.settings.admin_password_hash.get_secret_value())

    def require_local(self, request: Request):
        if self.settings.app_env == "production":
            raise HTTPException(403, "De lokale beheerlogin is niet beschikbaar in productie.")
        host = request.client.host if request.client else ""
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = False
        if not local:
            raise HTTPException(403, "Deze demo-login is alleen lokaal beschikbaar.")

    def require_origin(self, request: Request):
        if request.headers.get("origin") not in self.settings.allowed_origins:
            raise HTTPException(403, "De herkomst van dit verzoek is niet toegestaan.")

    def get_session(self, request: Request):
        self.require_local(request)
        now = time.monotonic()
        for key in [key for key, value in self.sessions.items() if value.expires_at <= now]:
            del self.sessions[key]
        token = request.cookies.get(COOKIE, "")
        session = self.sessions.get(hashlib.sha256(token.encode()).hexdigest())
        if not session:
            raise HTTPException(401, "Log in om aanvragen te bekijken.")
        return session

    def require_write(self, request: Request):
        session = self.get_session(request)
        self.require_origin(request)
        if not hmac.compare_digest(request.headers.get("x-csrf-token", "").encode(), session.csrf.encode()):
            raise HTTPException(403, "De sessiecontrole is verlopen. Vernieuw de pagina.")
        return session

    def start_session(self, request: Request, response: Response):
        now = time.monotonic()
        for key in [key for key, value in self.sessions.items() if value.expires_at <= now]:
            del self.sessions[key]
        # Rotate any previous session on successful authentication.
        self.sessions.pop(hashlib.sha256(request.cookies.get(COOKIE, "").encode()).hexdigest(), None)
        if len(self.sessions) >= 1000:
            raise HTTPException(429, "Te veel actieve sessies. Probeer later opnieuw.")
        token = secrets.token_urlsafe(32)
        session = Session(self.settings.admin_email, secrets.token_urlsafe(32), time.monotonic() + SESSION_SECONDS)
        self.sessions[hashlib.sha256(token.encode()).hexdigest()] = session
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, secure=False,
                            samesite="strict", path="/api/admin")
        return {"email": session.email, "csrf_token": session.csrf}

    async def setup(self, request: Request, email: str, password: str):
        self.require_local(request)
        self.require_origin(request)
        async with self.setup_lock:
            if self.configured:
                raise HTTPException(409, "Er is al een beheeraccount ingesteld.")
            encoded = await asyncio.to_thread(hash_password, password)
            await asyncio.to_thread(self._persist, email.lower(), encoded)
            self.settings.admin_email = email.lower()
            self.settings.admin_password_hash = SecretStr(encoded)

    def _persist(self, email: str, encoded: str):
        # Advisory file lock makes first-run setup exclusive across local processes.
        import fcntl
        import os
        path = self.settings.env_file
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path.parent / ".leadflow-setup.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if dotenv_values(path).get("ADMIN_PASSWORD_HASH"):
                raise HTTPException(409, "Er is al een beheeraccount ingesteld. Herstart de backend.")
            # Restrict permissions before any credential material is written.
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
            os.close(descriptor)
            os.chmod(path, 0o600)
            set_key(str(path), "ADMIN_EMAIL", email)
            set_key(str(path), "ADMIN_PASSWORD_HASH", encoded)
            os.chmod(path, 0o600)
