import argparse
import asyncio
import json
from uuid import UUID

from .config import Settings
from .outbox import Outbox
from .repository import DemoRepository


async def main():
    parser = argparse.ArgumentParser(description="Controleer de lokale workflowwachtrij zonder secrets te tonen")
    parser.add_argument("command", choices=["status", "retry"])
    parser.add_argument("event_id", nargs="?", type=UUID)
    parser.add_argument("--json", action="store_true", help="Machineleesbaar statusoverzicht")
    args = parser.parse_args()
    settings = Settings.load()
    await DemoRepository(settings.demo_db_path).initialize()
    outbox = Outbox(settings.demo_db_path)
    if args.command == "retry":
        if not args.event_id:
            parser.error("retry vereist een event-ID uit het statusoverzicht")
        print("Opnieuw ingepland." if await outbox.retry(str(args.event_id)) else "Geen mislukt event met dit ID gevonden.")
    else:
        status = await outbox.status()
        if args.json:
            print(json.dumps({"enabled": settings.automation_enabled, **status}, indent=2))
        else:
            print("Automatisering: " + ("ingeschakeld" if settings.automation_enabled else "uitgeschakeld"))
            print(f"Wacht op verwerking: {status['counts']['pending']}")
            print(f"Afgeleverd en bevestigd: {status['counts']['delivered']}")
            print(f"Eenmalig verwerkt: {status['processed']}")
            print(f"Handmatige retry nodig: {status['counts']['dead']}")
            for event in status["recent"]:
                if event["state"] == "dead":
                    print(f"Mislukt event: {event['id']} ({event['last_error']})")


if __name__ == "__main__":
    asyncio.run(main())
