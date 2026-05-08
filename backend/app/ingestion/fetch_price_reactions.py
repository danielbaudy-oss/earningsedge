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


async def get_pre_earnings_close(client: httpx.AsyncClient, ticker: str,
                                  report_date: str, report_time: str = "after_market") -> float | None:
    """
    Get the correct pre-earnings close price.
    
    This is critical for accurate training data:
    - After market close (AMC): use same-day close (last price before news)
    - Before market open (BMO): use PREVIOUS day's close (last price before news)
    
    The distinction matters because:
    - AMC: stock trades normally all day, then news hits after 4pm → compare to same-day close
    - BMO: news hits before 9:30am → the entire day's trading IS the reaction → compare to prev close
    """
    if report_time == "before_market":
        # BMO: get previous trading day's close
        for offset in range(1, 5):
            d = date.fromisoformat(report_date) - timedelta(days=offset)
            url = f"{POLYGON_BASE}/v1/open-close/{ticker}/{d.isoformat()}"
            resp = await client.get(url, params={"adjusted": "true", "apiKey": settings.polygon_api_key})
            if resp.status_code == 200:
                data = resp.json()
                if data.get("close"):
                    return data["close"]
    else:
        # AMC (default): use same-day close
        return await get_close_price(client, ticker, report_date)
    
    return None


async def get_price_after(client: httpx.AsyncClient, ticker: str,
                          earnings_date: str, report_time: str = "after_market") -> float | None:
    """
    Get closing price for T+1 reaction.
    
    - AMC: T+1 = next trading day close (the first full day of reaction)
    - BMO: T+1 = same day close (the stock reacts during the day it's reported)
    """
    if report_time == "before_market":
        # BMO: the reaction IS the same day — get same-day close
        return await get_close_price(client, earnings_date, earnings_date)
    else:
        # AMC: get next trading day close
        for offset in range(1, 5):
            d = date.fromisoformat(earnings_date) + timedelta(days=offset)
            url = f"{POLYGON_BASE}/v1/open-close/{ticker}/{d.isoformat()}"
            resp = await client.get(url, params={"adjusted": "true", "apiKey": settings.polygon_api_key})
            if resp.status_code == 200:
                data = resp.json()
                if data.get("close"):
                    return data["close"]
    return None


async def get_price_after_t3(client: httpx.AsyncClient, ticker: str,
                              earnings_date: str, report_time: str = "after_market") -> float | None:
    """
    Get closing price 3 trading days after earnings.
    
    - AMC: count 3 trading days starting from the day after
    - BMO: count 3 trading days starting from the report day itself (day 1 = report day)
    """
    start_offset = 0 if report_time == "before_market" else 1
    trading_days_found = 0
    last_close = None
    
    for offset in range(start_offset, start_offset + 8):
        d = date.fromisoformat(earnings_date) + timedelta(days=offset)
        url = f"{POLYGON_BASE}/v1/open-close/{ticker}/{d.isoformat()}"
        resp = await client.get(url, params={"adjusted": "true", "apiKey": settings.polygon_api_key})
        if resp.status_code == 200:
            data = resp.json()
            if data.get("close"):
                trading_days_found += 1
                last_close = data["close"]
                if trading_days_found >= 3:
                    return last_close
    
    return last_close if trading_days_found >= 2 else None


async def fetch_reactions_for_stock(client: httpx.AsyncClient, stock_id: int,
                                     ticker: str, events: list) -> int:
    """Fetch price reactions (T+1 and T+3) for all historical earnings of one stock."""
    sb = get_supabase()
    updated = 0

    for event in events:
        # Skip if already has both T+1 and T+3 price data
        if event.get("price_change_pct") is not None and event.get("price_change_pct_t3") is not None:
            continue

        report_date = event["report_date"]
        report_time = event.get("report_time", "after_market")
        update_data = {}

        # Get pre-earnings close (handles BMO vs AMC correctly)
        price_before = event.get("price_before")
        if price_before is None:
            price_before = await get_pre_earnings_close(client, ticker, report_date, report_time)
            await asyncio.sleep(12.5)

        if not price_before:
            print(f"    {report_date}: Could not get pre-earnings price")
            continue

        # Get T+1 if missing
        if event.get("price_change_pct") is None:
            price_after = await get_price_after(client, ticker, report_date, report_time)
            await asyncio.sleep(12.5)

            if price_after:
                change_pct = ((price_after - price_before) / price_before) * 100
                update_data["price_before"] = price_before
                update_data["price_after"] = price_after
                update_data["price_change_pct"] = round(change_pct, 2)

        # Get T+3 if missing
        if event.get("price_change_pct_t3") is None:
            price_after_t3 = await get_price_after_t3(client, ticker, report_date, report_time)
            await asyncio.sleep(12.5)

            if price_after_t3:
                change_pct_t3 = ((price_after_t3 - price_before) / price_before) * 100
                update_data["price_after_t3"] = price_after_t3
                update_data["price_change_pct_t3"] = round(change_pct_t3, 2)

        if update_data:
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
                t1 = update_data.get("price_change_pct", "n/a")
                t3 = update_data.get("price_change_pct_t3", "n/a")
                print(f"    {report_date} ({report_time}): T+1={t1}% T+3={t3}%")
            except Exception as e:
                print(f"    {report_date}: {e}")
        else:
            print(f"    {report_date}: Could not fetch post-earnings prices")

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
            .select("id, report_date, report_time, price_before, price_change_pct, price_change_pct_t3")
            .eq("stock_id", stock["id"])
            .lte("report_date", date.today().isoformat())
            .order("report_date", desc=True)
            .limit(8)
            .execute()
        )

        # Filter to events missing price data (T+1 or T+3)
        missing = [e for e in events.data
                   if e.get("price_change_pct") is None or e.get("price_change_pct_t3") is None]
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


async def fetch_recent_reactions(days_back: int = 7) -> int:
    """
    Fetch price reactions for earnings that happened in the last N days.
    Called daily to keep the feedback loop fed with actual outcomes.
    Only fetches for events missing price_change_pct.
    """
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)

    today = date.today()
    cutoff = (today - timedelta(days=days_back)).isoformat()

    # Get recent earnings without price data
    # Use a direct query approach since our REST client has filter limitations
    import httpx as hx
    headers = {
        "apikey": settings.supabase_service_key,
        "Authorization": f"Bearer {settings.supabase_service_key}",
    }
    url = f"{settings.supabase_url}/rest/v1/earnings_events"
    params = {
        "select": "id,stock_id,report_date,report_time,price_before,price_change_pct,price_change_pct_t3,stocks(ticker)",
        "report_date": f"gte.{cutoff}",
        "price_change_pct": "is.null",
        "eps_actual": "not.is.null",
        "order": "report_date.desc",
        "limit": "20",
    }

    async with hx.AsyncClient(timeout=15.0) as req_client:
        resp = await req_client.get(url, params=params, headers=headers)

    if resp.status_code != 200:
        return 0

    events = resp.json()
    if not events:
        return 0

    print(f"  Found {len(events)} recent earnings needing price data")

    fetched = 0
    for event in events:
        stock = event.get("stocks") or {}
        ticker = stock.get("ticker", "")
        if not ticker:
            continue

        report_date = event["report_date"]
        report_time = event.get("report_time", "after_market")

        # Get pre-earnings close (BMO vs AMC aware)
        price_before = await get_pre_earnings_close(client, ticker, report_date, report_time)
        await asyncio.sleep(13)

        # Get T+1
        price_after = await get_price_after(client, ticker, report_date, report_time)
        await asyncio.sleep(13)

        if price_before and price_after:
            change_pct = ((price_after - price_before) / price_before) * 100
            update_data = {
                "price_before": price_before,
                "price_after": price_after,
                "price_change_pct": round(change_pct, 2),
            }
            try:
                patch_url = f"{settings.supabase_url}/rest/v1/earnings_events?id=eq.{event['id']}"
                async with hx.AsyncClient() as patch_client:
                    await patch_client.patch(patch_url, json=update_data, headers={
                        **headers, "Content-Type": "application/json", "Prefer": "return=representation"
                    })
                fetched += 1
                print(f"    {ticker} ({report_date} {report_time}): {change_pct:+.2f}%")
            except Exception:
                pass

    await client.aclose()
    return fetched


async def backfill_price_reactions(max_fetches: int = 10) -> int:
    """
    Slowly backfill historical price reactions.
    Grabs a few each day to stay within Polygon rate limits.
    Prioritizes stocks with the most earnings history (better training data).
    """
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)

    # Get events missing price data (oldest first, so we fill gaps)
    import httpx as hx
    headers = {
        "apikey": settings.supabase_service_key,
        "Authorization": f"Bearer {settings.supabase_service_key}",
    }
    url = f"{settings.supabase_url}/rest/v1/earnings_events"
    params = {
        "select": "id,stock_id,report_date,report_time,stocks(ticker)",
        "price_change_pct": "is.null",
        "eps_actual": "not.is.null",
        "report_date": f"lte.{date.today().isoformat()}",
        "order": "report_date.desc",
        "limit": str(max_fetches),
    }

    async with hx.AsyncClient(timeout=15.0) as req_client:
        resp = await req_client.get(url, params=params, headers=headers)

    if resp.status_code != 200:
        return 0

    events = resp.json()
    if not events:
        return 0

    fetched = 0
    for event in events:
        try:
            stock = event.get("stocks") or {}
            ticker = stock.get("ticker", "")
            if not ticker:
                continue

            report_date = event["report_date"]
            report_time = event.get("report_time", "after_market")

            price_before = await get_pre_earnings_close(client, ticker, report_date, report_time)
            await asyncio.sleep(13)

            price_after = await get_price_after(client, ticker, report_date, report_time)
            await asyncio.sleep(13)

            if price_before and price_after:
                change_pct = ((price_after - price_before) / price_before) * 100
                try:
                    patch_url = f"{settings.supabase_url}/rest/v1/earnings_events?id=eq.{event['id']}"
                    async with hx.AsyncClient() as patch_client:
                        await patch_client.patch(patch_url, json={
                            "price_before": price_before,
                            "price_after": price_after,
                            "price_change_pct": round(change_pct, 2),
                        }, headers={**headers, "Content-Type": "application/json"})
                    fetched += 1
                except Exception:
                    pass
        except Exception:
            # Skip this event on any error, continue with next
            await asyncio.sleep(13)
            continue

    await client.aclose()
    return fetched
