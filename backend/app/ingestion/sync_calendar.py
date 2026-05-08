"""
Sync upcoming earnings calendar from multiple sources.

Strategy:
1. FMP (Financial Modeling Prep) — primary for confirmed dates (has lastUpdated field)
2. Finnhub — broader coverage, especially small caps
3. Cross-validate: when both have a date, prefer the most recently updated one
4. Mark events as confirmed/unconfirmed based on source agreement

This is the CORE of the app — accurate earnings dates are everything.
"""

import asyncio
import httpx
from datetime import date, timedelta
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

settings = get_settings()
FINNHUB_BASE = "https://finnhub.io/api/v1"
FMP_BASE = "https://financialmodelingprep.com/stable"


async def fetch_fmp_calendar(client: httpx.AsyncClient, from_date: str, to_date: str) -> list:
    """
    Fetch earnings calendar from FMP.
    FMP has a lastUpdated field — more recently updated = more reliable.
    Free tier is limited in results, but covers major stocks well.
    """
    if not settings.fmp_api_key:
        return []

    try:
        resp = await client.get(
            f"{FMP_BASE}/earnings-calendar",
            params={"from": from_date, "to": to_date, "apikey": settings.fmp_api_key},
            timeout=15.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return data
    except Exception as e:
        print(f"  ⚠️ FMP calendar fetch failed: {e}")

    return []


async def fetch_finnhub_calendar(client: httpx.AsyncClient, from_date: str, to_date: str) -> list:
    """Fetch earnings calendar from Finnhub. Broader coverage but less reliable dates."""
    try:
        params = {
            "from": from_date,
            "to": to_date,
            "token": settings.finnhub_api_key,
        }
        resp = await client.get(f"{FINNHUB_BASE}/calendar/earnings", params=params, timeout=15.0)
        if resp.status_code == 200:
            return resp.json().get("earningsCalendar", [])
    except Exception as e:
        print(f"  ⚠️ Finnhub calendar fetch failed: {e}")

    return []


def merge_calendars(fmp_events: list, finnhub_events: list) -> list:
    """
    Merge earnings events from both sources.
    
    Rules:
    - If both sources have the same ticker, prefer FMP (has lastUpdated, more accurate)
    - If only Finnhub has it, use Finnhub but mark as unconfirmed
    - If dates disagree by > 2 days, mark as unconfirmed
    """
    # Build FMP lookup: ticker -> event
    fmp_map = {}
    for event in fmp_events:
        ticker = event.get("symbol", "")
        if ticker:
            fmp_map[ticker] = {
                "ticker": ticker,
                "date": event.get("date"),
                "eps_estimate": event.get("epsEstimated"),
                "revenue_estimate": event.get("revenueEstimated"),
                "source": "fmp",
                "last_updated": event.get("lastUpdated"),
                "is_confirmed": True,  # FMP dates are generally confirmed
            }

    # Build merged list
    merged = {}

    # Add all FMP events first (higher priority)
    for ticker, event in fmp_map.items():
        merged[ticker] = event

    # Add Finnhub events, cross-validating where possible
    for event in finnhub_events:
        ticker = event.get("symbol", "")
        if not ticker:
            continue

        finnhub_date = event.get("date")
        finnhub_data = {
            "ticker": ticker,
            "date": finnhub_date,
            "eps_estimate": event.get("epsEstimate"),
            "revenue_estimate": event.get("revenueEstimate"),
            "report_time": "before_market" if event.get("hour") == "bmo" else "after_market",
            "fiscal_quarter": f"Q{event.get('quarter', '?')} {event.get('year', '')}",
            "fiscal_year": event.get("year"),
            "source": "finnhub",
            "is_confirmed": False,  # Finnhub alone = unconfirmed
        }

        if ticker in merged:
            # Both sources have this ticker — cross-validate
            fmp_date = merged[ticker]["date"]
            if fmp_date and finnhub_date:
                try:
                    fmp_d = date.fromisoformat(fmp_date)
                    fh_d = date.fromisoformat(finnhub_date)
                    diff = abs((fmp_d - fh_d).days)

                    if diff == 0:
                        # Perfect agreement — high confidence
                        merged[ticker]["is_confirmed"] = True
                        merged[ticker]["source"] = "fmp+finnhub"
                    elif diff <= 2:
                        # Close enough — prefer FMP, still confirmed
                        merged[ticker]["is_confirmed"] = True
                        merged[ticker]["source"] = "fmp (finnhub differs by " + str(diff) + "d)"
                    else:
                        # Significant disagreement — mark unconfirmed, prefer FMP
                        merged[ticker]["is_confirmed"] = False
                        merged[ticker]["source"] = f"fmp:{fmp_date} vs finnhub:{finnhub_date}"
                except (ValueError, TypeError):
                    pass

            # Add report_time and fiscal info from Finnhub (FMP doesn't have these)
            if finnhub_data.get("report_time"):
                merged[ticker]["report_time"] = finnhub_data["report_time"]
            if finnhub_data.get("fiscal_quarter"):
                merged[ticker]["fiscal_quarter"] = finnhub_data["fiscal_quarter"]
            if finnhub_data.get("fiscal_year"):
                merged[ticker]["fiscal_year"] = finnhub_data["fiscal_year"]
        else:
            # Only Finnhub has this ticker — use it but mark unconfirmed
            merged[ticker] = finnhub_data

    return list(merged.values())


async def sync_earnings_calendar(days_ahead: int = 7):
    """Fetch earnings from multiple sources, cross-validate, and sync to database."""
    print(f"📅 Syncing earnings calendar (next {days_ahead} days)...\n")
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)

    today = date.today()
    end_date = today + timedelta(days=days_ahead)
    from_str = today.isoformat()
    to_str = end_date.isoformat()

    # Fetch from both sources
    print("  Fetching from FMP...")
    fmp_events = await fetch_fmp_calendar(client, from_str, to_str)
    print(f"  FMP: {len(fmp_events)} events")

    print("  Fetching from Finnhub...")
    finnhub_events = await fetch_finnhub_calendar(client, from_str, to_str)
    print(f"  Finnhub: {len(finnhub_events)} events")

    # Merge and cross-validate
    merged = merge_calendars(fmp_events, finnhub_events)
    confirmed = sum(1 for e in merged if e.get("is_confirmed"))
    print(f"  Merged: {len(merged)} unique events ({confirmed} confirmed, {len(merged) - confirmed} unconfirmed)")

    # Get existing stocks
    existing = sb.table("stocks").select("id, ticker").execute()
    stock_map = {s["ticker"]: s["id"] for s in existing.data}

    new_stocks = 0
    new_events = 0

    for event in merged:
        ticker = event.get("ticker", "")
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

        # Insert/update earnings event
        earnings_data = {
            "stock_id": stock_id,
            "report_date": event.get("date"),
            "is_confirmed": event.get("is_confirmed", False),
        }

        # Add optional fields if available
        if event.get("fiscal_quarter"):
            earnings_data["fiscal_quarter"] = event["fiscal_quarter"]
        if event.get("fiscal_year"):
            earnings_data["fiscal_year"] = event["fiscal_year"]
        if event.get("report_time"):
            earnings_data["report_time"] = event["report_time"]
        if event.get("eps_estimate") is not None:
            earnings_data["eps_estimate"] = event["eps_estimate"]
        if event.get("revenue_estimate") is not None:
            earnings_data["revenue_estimate"] = event["revenue_estimate"]

        try:
            sb.table("earnings_events").upsert(earnings_data, on_conflict="stock_id,report_date")
            new_events += 1
        except Exception:
            pass

    await client.aclose()
    print(f"✅ Synced: {new_events} events, {new_stocks} new stocks added")
    print(f"   Sources: FMP={len(fmp_events)}, Finnhub={len(finnhub_events)}, Merged={len(merged)}")
    return new_events


if __name__ == "__main__":
    asyncio.run(sync_earnings_calendar(7))
