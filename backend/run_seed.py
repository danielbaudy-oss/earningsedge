"""Run earnings seed only (stocks already partially seeded)."""
import asyncio
from app.ingestion.seed import seed_earnings_calendar, seed_earnings_history


async def main():
    print("Testing Finnhub earnings calendar...")
    await seed_earnings_calendar()
    print("\nSeeding earnings history for existing stocks...")
    await seed_earnings_history()


asyncio.run(main())
