"""Idempotent, local-only seed command: python -m app.seed."""
import asyncio
from uuid import NAMESPACE_URL, uuid5

from .config import Settings
from .models import LeadCreate
from .repository import DemoRepository

SAMPLES = [
    LeadCreate(company_name="Demo Studio Alpha", name="Demo Alpha", email="alpha@example.com", description="Demo: intakeformulieren koppelen aan een takenlijst."),
    LeadCreate(company_name="Demo Studio Bravo", name="Demo Bravo", email="bravo@example.com", description="Demo: dringende aanvraag voor automatische opvolging."),
    LeadCreate(company_name="Demo Studio Charlie", name="Demo Charlie", email="charlie@example.com", description="Demo: documenten sorteren en een medewerker laten beoordelen."),
]


async def main():
    settings = Settings.load()
    if settings.storage_mode != "demo":
        raise SystemExit("Seed only supports STORAGE_MODE=demo")
    repository = DemoRepository(settings.demo_db_path)
    await repository.initialize()
    for lead in SAMPLES:
        result = await repository.create(lead, uuid5(NAMESPACE_URL, f"leadflow-demo:{lead.email}"))
        print(f"{lead.company_name}: {'already exists' if result.duplicate else 'created'}")


if __name__ == "__main__":
    asyncio.run(main())
