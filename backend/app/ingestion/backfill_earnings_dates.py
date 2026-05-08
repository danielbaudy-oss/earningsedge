"""
Backfill correct earnings announcement dates from FMP.

Problem: Our DB has report_date = fiscal quarter end (e.g., 2026-03-31)
         but the actual announcement date is different (e.g., AAPL reported Apr 30).

Solution: FMP's earnings-calendar endpoint returns the ACTUAL announcement date
          for past events. We query week by week and update our records.

FMP free tier: 250 requests/day, ~4 results per query.
Strategy: Query 1-week windows going back in time. Each query uses 1 request.
          Run daily to gradually backfill.

Usage:
    python -m app.ingestion.backfill_earnings_dates
    python -m app.ingestion.backfill_earnings_dates --weeks 52
"""

import asyncio
import httpx
from datetime import date, timedelta
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

settings = get_settings()
FMP_BASE = "https://financialmodelingprep.com/stable"


async def fetch_fmp_week(client: httpx.AsyncClient, from_date: str, to_date: str) -> list:
    """Fetch earnings for a specific week from FMP."""
    if not settings.fmp_api_key:
        return []

    resp = await client.get(
        f"{FMP_BASE}/earnings-calendar",
        params={"from": from_date, "to": to_date, "apikey": settings.fmp_api_key},
        timeout=15.0,
    )
    if resp.status_code == 200:
        data = resp.json()
        return data if isinstance(data, list) else []
    return []


async def backfill_earnings_dates(weeks_back: int = 12, max_requests: int = 50):
    """
    Backfill correct earnings announcement dates from FMP.
    
    For each week going back, fetches the FMP calendar and updates
    our earnings_events records with the correct announcement date.
    
    Args:
        weeks_back: How many weeks to go back
        max_requests: Max FMP API calls (stay within daily limit)
    """
    print(f"📅 Backfilling earnings dates from FMP (last {weeks_back} weeks)...\n")
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)

    # Get existing stocks for matching
    stocks = sb.table("stocks").select("id, ticker").execute()
    stock_map = {s["ticker"]: s["id"] for s in stocks.data}

    updated = 0
    requests_made = 0
    today = date.today()

    for week in range(weeks_back):
        if requests_made >= max_requests:
            print(f"  Reached request limit ({max_requests}). Run again tomorrow.")
            break

        # Query one week at a time
        end = today - timedelta(weeks=week)
        start = end - timedelta(days=6)

        events = await fetch_fmp_week(client, start.isoformat(), end.isoformat())
        requests_made += 1

        if not events:
            continue

        for event in events:
            ticker = event.get("symbol", "")
            announcement_date = event.get("date")
            eps_actual = event.get("epsActual")
            eps_estimate = event.get("epsEstimated")
            rev_actual = event.get("revenueActual")
            rev_estimate = event.get("revenueEstimated")

            if not ticker or not announcement_date:
                continue

            stock_id = stock_map.get(ticker)
            if not stock_id:
                continue

            # Find the matching event in our DB
            # Match by stock_id and approximate date (within 60 days of announcement)
            # because our report_date might be the fiscal quarter end
            existing = (
                sb.table("earnings_events")
                .select("id, report_date, eps_actual")
                .eq("stock_id", stock_id)
                .gte("report_date", (date.fromisoformat(announcement_date) - timedelta(days=60)).isoformat())
                .lte("report_date", (date.fromisoformat(announcement_date) + timedelta(days=7)).isoformat())
                .limit(1)
                .execute()
            )

            if existing.data:
                # Update existing record with correct announcement date
                event_id = existing.data[0]["id"]
                old_date = existing.data[0]["report_date"]

                update_data = {}

                # Only update report_date if it's different (fiscal quarter end → actual date)
                if old_date != announcement_date:
                    update_data["report_date"] = announcement_date

                # Update EPS data if we have it from FMP
                if eps_actual is not None:
                    update_data["eps_actual"] = eps_actual
                if eps_estimate is not None:
                    update_data["eps_estimate"] = eps_estimate
                if rev_actual is not None:
                    update_data["revenue_actual"] = rev_actual
                if rev_estimate is not None:
                    update_data["revenue_estimate"] = rev_estimate

                # Calculate surprise
                if eps_actual is not None and eps_estimate and eps_estimate != 0:
                    surprise = eps_actual - eps_estimate
                    update_data["eps_surprise"] = surprise
                    update_data["eps_surprise_pct"] = (surprise / abs(eps_estimate)) * 100

                update_data["is_confirmed"] = True

                if update_data:
                    try:
                        headers = {
                            "apikey": settings.supabase_service_key,
                            "Authorization": f"Bearer {settings.supabase_service_key}",
                            "Content-Type": "application/json",
                        }
                        url = f"{settings.supabase_url}/rest/v1/earnings_events?id=eq.{event_id}"
                        async with httpx.AsyncClient() as patch_client:
                            await patch_client.patch(url, json=update_data, headers=headers)
                        if old_date != announcement_date:
                            print(f"  {ticker}: {old_date} → {announcement_date} (corrected)")
                        updated += 1
                    except Exception as e:
                        print(f"  {ticker}: update failed: {e}")
            else:
                # No matching event — insert new one with correct date
                new_event = {
                    "stock_id": stock_id,
                    "report_date": announcement_date,
                    "eps_actual": eps_actual,
                    "eps_estimate": eps_estimate,
                    "revenue_actual": rev_actual,
                    "revenue_estimate": rev_estimate,
                    "is_confirmed": True,
                }
                if eps_actual is not None and eps_estimate and eps_estimate != 0:
                    surprise = eps_actual - eps_estimate
                    new_event["eps_surprise"] = surprise
                    new_event["eps_surprise_pct"] = (surprise / abs(eps_estimate)) * 100

                try:
                    sb.table("earnings_events").upsert(new_event, on_conflict="stock_id,report_date")
                    updated += 1
                except Exception:
                    pass

        # Small delay between requests
        await asyncio.sleep(0.5)

    await client.aclose()
    print(f"\n✅ Updated {updated} earnings events with correct dates")
    print(f"   FMP requests used: {requests_made}/{max_requests}")
    return updated


if __name__ == "__main__":
    import sys

    weeks = 12
    max_req = 50

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--weeks" and i + 1 < len(args):
            weeks = int(args[i + 1])
            i += 2
        elif args[i] == "--max-requests" and i + 1 < len(args):
            max_req = int(args[i + 1])
            i += 2
        else:
            i += 1

    asyncio.run(backfill_earnings_dates(weeks_back=weeks, max_requests=max_req))
