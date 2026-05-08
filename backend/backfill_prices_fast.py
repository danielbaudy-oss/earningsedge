"""
Fast price reaction backfill using Polygon paid tier.
No rate limit delays — fetches T+1 and T+3 for all events missing price data.
"""

import asyncio
import httpx
from datetime import date, timedelta
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

settings = get_settings()
POLYGON_BASE = "https://api.polygon.io"


async def get_close(client: httpx.AsyncClient, ticker: str, target_date: str, direction: str = "back") -> tuple[float | None, str | None]:
    """Get closing price on or near a date. Returns (price, actual_date)."""
    offsets = range(0, 5) if direction == "back" else range(0, 5)
    for offset in offsets:
        if direction == "back":
            d = date.fromisoformat(target_date) - timedelta(days=offset)
        else:
            d = date.fromisoformat(target_date) + timedelta(days=offset)
        
        resp = await client.get(
            f"{POLYGON_BASE}/v1/open-close/{ticker}/{d.isoformat()}",
            params={"adjusted": "true", "apiKey": settings.polygon_api_key},
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("close"):
                return data["close"], d.isoformat()
    return None, None


async def get_t3_close(client: httpx.AsyncClient, ticker: str, start_date: str) -> float | None:
    """Get close price 3 trading days after start_date."""
    trading_days = 0
    last_close = None
    for offset in range(1, 8):
        d = date.fromisoformat(start_date) + timedelta(days=offset)
        resp = await client.get(
            f"{POLYGON_BASE}/v1/open-close/{ticker}/{d.isoformat()}",
            params={"adjusted": "true", "apiKey": settings.polygon_api_key},
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("close"):
                trading_days += 1
                last_close = data["close"]
                if trading_days >= 3:
                    return last_close
    return last_close if trading_days >= 2 else None


async def process_batch(client: httpx.AsyncClient, events: list, sb, semaphore: asyncio.Semaphore):
    """Process a batch of events concurrently."""
    tasks = [process_event(client, e, sb, semaphore) for e in events]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return sum(1 for r in results if r is True)


async def process_event(client: httpx.AsyncClient, event: dict, sb, semaphore: asyncio.Semaphore) -> bool:
    """Fetch price reaction for a single event."""
    async with semaphore:
        ticker = (event.get("stocks") or {}).get("ticker", "")
        if not ticker:
            return False

        report_date = event["report_date"]
        report_time = event.get("report_time", "")

        # Determine pre-earnings close date
        if report_time == "before_market":
            # BMO: pre-earnings = previous day close
            pre_date = (date.fromisoformat(report_date) - timedelta(days=1)).isoformat()
        else:
            # AMC (default): pre-earnings = same day close
            pre_date = report_date

        # Get pre-earnings close
        price_before, _ = await get_close(client, ticker, pre_date, "back")
        if not price_before:
            return False

        # Get T+1 close
        if report_time == "before_market":
            # BMO: T+1 = same day close
            price_after, _ = await get_close(client, ticker, report_date, "forward")
        else:
            # AMC: T+1 = next day close
            next_day = (date.fromisoformat(report_date) + timedelta(days=1)).isoformat()
            price_after, _ = await get_close(client, ticker, next_day, "forward")

        if not price_after:
            return False

        change_pct = ((price_after - price_before) / price_before) * 100

        # Get T+3 close
        price_t3 = await get_t3_close(client, ticker, report_date)
        change_pct_t3 = None
        if price_t3:
            change_pct_t3 = ((price_t3 - price_before) / price_before) * 100

        # Update DB
        update_data = {
            "price_before": round(price_before, 4),
            "price_after": round(price_after, 4),
            "price_change_pct": round(change_pct, 2),
        }
        # Note: price_after_t3 and price_change_pct_t3 columns may not exist yet
        # Store T+3 data only if the columns have been added via migration

        try:
            headers = {
                "apikey": settings.supabase_service_key,
                "Authorization": f"Bearer {settings.supabase_service_key}",
                "Content-Type": "application/json",
            }
            url = f"{settings.supabase_url}/rest/v1/earnings_events?id=eq.{event['id']}"
            async with httpx.AsyncClient() as patch_client:
                await patch_client.patch(url, json=update_data, headers=headers)
            return True
        except Exception:
            return False


async def main():
    print("🚀 Fast price reaction backfill (Polygon paid tier)\n")
    sb = get_supabase()

    # Get all events needing price data
    all_events = []
    page_size = 1000

    # Supabase returns max 1000 per query, paginate with limit/offset workaround
    batch = (
        sb.table("earnings_events")
        .select("id, stock_id, report_date, report_time, price_change_pct, stocks(ticker)")
        .order("report_date", desc=True)
        .limit(10000)
        .execute()
    )
    all_events = batch.data or []

    # Filter to events with actuals but no price data
    need_fetch = [e for e in all_events
                  if e.get("price_change_pct") is None
                  and e.get("report_date")
                  and e["report_date"] <= date.today().isoformat()]

    print(f"  Total events: {len(all_events)}")
    print(f"  Need price fetch: {len(need_fetch)}")
    print(f"  Concurrency: 10 parallel requests\n")

    # Process with concurrency limit (don't overwhelm Polygon)
    client = httpx.AsyncClient(timeout=15.0)
    semaphore = asyncio.Semaphore(10)  # 10 concurrent requests

    fetched = 0
    batch_size = 50
    for i in range(0, len(need_fetch), batch_size):
        batch = need_fetch[i:i + batch_size]
        count = await process_batch(client, batch, sb, semaphore)
        fetched += count
        pct = (i + len(batch)) / len(need_fetch) * 100
        print(f"  Progress: {i + len(batch)}/{len(need_fetch)} ({pct:.0f}%) — {fetched} fetched")

    await client.aclose()
    print(f"\n✅ Done! Fetched price reactions for {fetched}/{len(need_fetch)} events")


if __name__ == "__main__":
    asyncio.run(main())
