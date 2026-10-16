"""Signed local delivery with leases, retries, and idempotent receiver effects."""
import asyncio
import hashlib
import hmac
import logging
import time

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .outbox import EventMismatch, Outbox, canonical
from .repository_errors import StorageUnavailable

logger = logging.getLogger("leadflow.automation")
router = APIRouter(prefix="/api/automation", tags=["Local automation"])


def signature(event: dict, timestamp: int, secret: str):
    message = f"{timestamp}.{canonical(event)}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def envelope(event: dict, secret: str, timestamp=None):
    timestamp = int(time.time()) if timestamp is None else timestamp
    return {"event": event, "timestamp": timestamp, "signature": signature(event, timestamp, secret)}


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event: dict
    timestamp: int = Field(ge=0, le=253402300799)
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.post("/process")
async def process(payload: Envelope, request: Request, x_leadflow_token: str = Header(default="")):
    settings = request.app.state.settings
    # This receiver is intentionally local-only, including when behind the Next proxy.
    request.app.state.auth.require_local(request)
    secret = settings.n8n_webhook_secret.get_secret_value()
    if not settings.automation_enabled or not secret or not hmac.compare_digest(x_leadflow_token.encode(), secret.encode()):
        raise HTTPException(401, "Workflowauthenticatie is niet geldig.")
    if abs(time.time() - payload.timestamp) > 300 or not hmac.compare_digest(payload.signature, signature(payload.event, payload.timestamp, secret)):
        raise HTTPException(401, "De workflowhandtekening is niet geldig of verlopen.")
    try:
        return await Outbox(settings.demo_db_path).process(payload.event)
    except EventMismatch:
        raise HTTPException(409, "Dit event komt niet overeen met een opgeslagen aanvraag.") from None
    except StorageUnavailable:
        raise HTTPException(503, "Workflowverwerking is tijdelijk niet mogelijk.") from None


class Worker:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client
        self.outbox = Outbox(settings.demo_db_path)

    async def once(self):
        job = await self.outbox.claim()
        if not job:
            return False
        secret = self.settings.n8n_webhook_secret.get_secret_value()
        error = None
        try:
            response = await self.client.post(self.settings.n8n_webhook_url,
                headers={"X-LeadFlow-Token": secret}, json=envelope(job["event"], secret),
                follow_redirects=False, timeout=15)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict) or result.get("processed") is not True or result.get("event_id") != job["id"]:
                error = "invalid_ack"
            elif not await self.outbox.finish(job):
                error = "missing_receipt_or_lease"
        except httpx.HTTPStatusError as exc:
            error = f"http_{exc.response.status_code}"
        except httpx.HTTPError:
            error = "connection_error"
        except (ValueError, TypeError):
            error = "invalid_ack"
        if error:
            await self.outbox.finish(job, error)
            # Never log lead data, credentials, full URLs, or response bodies.
            logger.warning("Workflow delivery deferred: %s", error)
        return True

    async def run(self):
        while True:
            try:
                busy = await self.once()
            except StorageUnavailable:
                logger.error("Workflow storage unavailable")
                busy = False
            await asyncio.sleep(0.1 if busy else 2)
