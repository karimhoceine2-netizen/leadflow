"""Run the outbox workflow offline using an in-process mock webhook, not a running n8n server."""

import asyncio
import json
import secrets
import tempfile
from pathlib import Path
from uuid import uuid4
import httpx
from .automation import Worker
from .config import Settings
from .models import LeadCreate
from .outbox import Outbox
from .repository import DemoRepository


async def main():
    with tempfile.TemporaryDirectory(prefix="leadflow-demo-") as scratch:
        path = Path(scratch) / "demo.sqlite3"
        settings = Settings(
            app_env="test", demo_db_path=path, automation_enabled=True, n8n_webhook_secret=secrets.token_urlsafe(48)
        )
        repository = DemoRepository(path)
        await repository.initialize()
        lead = LeadCreate(
            name="Demo Alpha",
            email="alpha@example.com",
            company_name="Demo Studio Alpha",
            description="Demo: dringende aanvraag om intake automatisch te verwerken.",
        )
        key = uuid4()
        first = await repository.create(lead, key)
        again = await repository.create(lead, key)
        assert first.id == again.id and again.duplicate
        outbox = Outbox(path)

        async def webhook(request):
            # Mock just the HTTP transport. The real outbox processor handles the event.
            body = json.loads(request.content)
            return httpx.Response(200, json=await outbox.process(body["event"]))

        async with httpx.AsyncClient(transport=httpx.MockTransport(webhook)) as client:
            assert await Worker(settings, client).once()
        status = await outbox.status()
        assert status["counts"]["delivered"] == 1 and status["processed"] == 1
        print(
            json.dumps(
                {
                    "mode": "offline mock webhook",
                    "duplicate_intake_deduplicated": True,
                    "delivered_events": status["counts"]["delivered"],
                    "workflow_receipts": status["processed"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
