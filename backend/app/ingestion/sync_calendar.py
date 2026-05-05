"""
Sync upcoming earnings calendar from Finnhub.
Pulls ALL earnings for the next 2 weeks and stores them.
Stocks not in our DB get auto-created with basic info.
"""

import asyncio
import httpx
from datetime import date, timedelta
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

settings = get_settings()
FINNHUB_BASE = "https://finnhub.io/api/v1"


async def sync_earnings_calendar(days_ahead: int = 7):
    """Fetch all earnings for the next N days and sync to database."""
    print(f"📅 Syncing earnings calendar (next {days_ahead} days)...\n")
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)

    today = date.today()
    end_date = today + timedelta(days=days_ahead)

    # Fetch from Finnhub
    params = {
        "from": today.isoformat(),
        "to": end_date.isoformat(),
        "token": settings.finnhub_api_key,
    }
    resp = await client.get(f"{FINNHUB_BASE}/calendar/earnings", params=params)
    if resp.status_code != 200:
        print(f"❌ Finnhub returned {resp.status_code}")
        await client.aclose()
        return

    calendar = resp.json().get("earningsCalendar", [])
    print(f"  Found {len(calendar)} earnings events from Finnhub")

    # Get existing stocks
    existing = sb.table("stocks").select("id, ticker").execute()
    stock_map = {s["ticker"]: s["id"] for s in existing.data}

    new_stocks = 0
    new_events = 0

    for event in calendar:
        ticker = event.get("symbol", "")
        if not ticker:
            continue

        # Auto-create stock if not in DB
        if ticker not in stock_map:
            stock_data = {
                "ticker": ticker,
                "company_name": ticker,  # Will be enriched later
                "is_active": True,
            }
            try:
                result = sb.table("stocks").upsert(stock_data, on_conflict="ticker")
                if result.data:
                    stock_map[ticker] = result.data[0]["id"]
                    new_stocks += 1
            except Exception:
                continue

        stock_id = stock_map.get(ticker)
        if not stock_id:
            continue

        # Insert earnings event
        earnings_data = {
            "stock_id": stock_id,
            "report_date": event.get("date"),
            "fiscal_quarter": f"Q{event.get('quarter', '?')} {event.get('year', '')}",
            "fiscal_year": event.get("year"),
            "report_time": "before_market" if event.get("hour") == "bmo" else "after_market",
            "eps_estimate": event.get("epsEstimate"),
            "revenue_estimate": event.get("revenueEstimate"),
            "is_confirmed": True,
        }

        try:
            sb.table("earnings_events").upsert(earnings_data, on_conflict="stock_id,report_date")
            new_events += 1
        except Exception:
            pass

    await client.aclose()
    print(f"✅ Synced: {new_events} events, {new_stocks} new stocks added")
    return new_events


if __name__ == "__main__":
    asyncio.run(sync_earnings_calendar(7))
