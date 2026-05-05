"""
Fetch historical post-earnings price reactions from Polygon.
This is the critical training data for the ML model.

For each historical earnings event, we fetch:
- Price the day before earnings
- Price the day after earnings
- Calculate the actual % move
- Store in earnings_events table
"""

import asyncio
import httpx
from datetime import date, timedelta, datetime
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

settings = get_settings()
POLYGON_BASE = "https://api.polygon.io"


async def get_close_price(client: httpx.AsyncClient, ticker: str, target_date: str) -> float | None:
    """Get closing price for a ticker on or near a date."""
    # Try the exact date, then go back up to 3 days (weekends/holidays)
    for offset in range(0, 5):
        d = date.fromisoformat(target_date) - timedelta(days=offset)
        url = f"{POLYGON_BASE}/v1/open-close/{ticker}/{d.isoformat()}"
        resp = await client.get(url, params={"adjusted": "true", "apiKey": settings.polygon_api_key})
        if resp.status_code == 200:
            data = resp.json()
            if data.get("close"):
                return data["close"]
    return None


async def get_price_after(client: httpx.AsyncClient, ticker: str, earnings_date: str) -> float | None:
    """Get closing price 1 trading day after earnings."""
    # Go forward 1-3 days to find next trading day
    for offset in range(1, 5):
        d = date.fromisoformat(earnings_date) + timedelta(days=offset)
        url = f"{POLYGON_BASE}/v1/open-close/{ticker}/{d.isoformat()}"
        resp = await client.get(url, params={"adjusted": "true", "apiKey": settings.polygon_api_key})
        if resp.status_code == 200:
            data = resp.json()
            if data.get("close"):
                return data["close"]
    return None


async def fetch_reactions_for_stock(client: httpx.AsyncClient, stock_id: int,
                                     ticker: str, events: list) -> int:
    """Fetch price reactions for all historical earnings of one stock."""
    sb = get_supabase()
    updated = 0

    for event in events:
        # Skip if already has price data
        if event.get("price_change_pct") is not None:
            continue

        report_date = event["report_date"]

        # Get price before (day before or same day open)
        price_before = await get_close_price(client, ticker, report_date)
        await asyncio.sleep(12.5)  # Polygon rate limit

        # Get price after (next trading day close)
        price_after = await get_price_after(client, ticker, report_date)
        await asyncio.sleep(12.5)  # Polygon rate limit

        if price_before and price_after:
            change_pct = ((price_after - price_before) / price_before) * 100

            # Update in Supabase
            update_data = {
                "price_before": price_before,
                "price_after": price_after,
                "price_change_pct": round(change_pct, 2),
            }

            try:
                headers = {
                    "apikey": settings.supabase_service_key,
                    "Authorization": f"Bearer {settings.supabase_service_key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                }
                url = f"{settings.supabase_url}/rest/v1/earnings_events?id=eq.{event['id']}"
                async with httpx.AsyncClient() as patch_client:
                    await patch_client.patch(url, json=update_data, headers=headers)
                updated += 1
                print(f"    {report_date}: ${price_before:.2f} → ${price_after:.2f} ({change_pct:+.2f}%)")
            except Exception as e:
                print(f"    ❌ {report_date}: {e}")
        else:
            print(f"    ⚠️  {report_date}: Could not fetch prices")

    return updated


async def fetch_all_price_reactions():
    """Fetch price reactions for all historical earnings events."""
    print("📈 Fetching post-earnings price reactions from Polygon...\n")
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)

    # Get all stocks
    stocks = sb.table("stocks").select("id, ticker").execute()

    total_updated = 0
    for stock in stocks.data:
        ticker = stock["ticker"]

        # Get historical earnings without price data
        events = (
            sb.table("earnings_events")
            .select("id, report_date, price_change_pct")
            .eq("stock_id", stock["id"])
            .lte("report_date", date.today().isoformat())
            .order("report_date", desc=True)
            .limit(8)
            .execute()
        )

        # Filter to events missing price data
        missing = [e for e in events.data if e.get("price_change_pct") is None]
        if not missing:
            continue

        print(f"  {ticker}: fetching {len(missing)} price reactions...")
        updated = await fetch_reactions_for_stock(client, stock["id"], ticker, missing)
        total_updated += updated

    await client.aclose()
    print(f"\n✅ Updated {total_updated} earnings events with price reactions")
    return total_updated


if __name__ == "__main__":
    asyncio.run(fetch_all_price_reactions())
