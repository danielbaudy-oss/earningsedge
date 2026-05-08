"""
Correct backfill — uses Polygon's filing_date (actual earnings report date)
instead of fiscal period end date.

This is the RIGHT way to measure post-earnings price reactions.
"""
import asyncio
import httpx
from datetime import date, timedelta
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

settings = get_settings()
POLYGON_BASE = "https://api.polygon.io"


async def get_price(client, ticker, target_date, direction="before"):
    """Get closing price near a date."""
    d = date.fromisoformat(target_date)
    offsets = range(0, 5) if direction == "before" else range(1, 5)
    sign = -1 if direction == "before" else 1

    for offset in offsets:
        check = (d + timedelta(days=offset * sign)).isoformat()
        try:
            resp = await client.get(
                f"{POLYGON_BASE}/v1/open-close/{ticker}/{check}",
                params={"adjusted": "true", "apiKey": settings.polygon_api_key},
            )
            if resp.status_code == 200 and resp.json().get("close"):
                return resp.json()["close"]
        except Exception:
            pass
        await asyncio.sleep(0.3)
    return None


async def main():
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=15.0)

    headers = {
        "apikey": settings.supabase_service_key,
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "Content-Type": "application/json",
    }

    # Get all stocks with known tickers
    stocks_resp = httpx.get(
        f"{settings.supabase_url}/rest/v1/stocks",
        params={"select": "id,ticker", "limit": "2000"},
        headers=headers,
        timeout=30,
    )
    stocks = {s["id"]: s["ticker"] for s in stocks_resp.json()}
    print(f"Stocks: {len(stocks)}")

    # For each stock, get Polygon's financials (which have filing_date)
    total_fetched = 0
    total_skipped = 0

    for stock_id, ticker in stocks.items():
        try:
            # Get filing dates from Polygon
            fin_resp = await client.get(
                f"{POLYGON_BASE}/vX/reference/financials",
                params={"ticker": ticker, "limit": 12, "timeframe": "quarterly", "apiKey": settings.polygon_api_key},
            )
            await asyncio.sleep(0.3)

            if fin_resp.status_code != 200:
                continue

            financials = fin_resp.json().get("results", [])
            if not financials:
                continue

            for fin in financials:
                filing_date = fin.get("filing_date")
                if not filing_date:
                    continue

                # Get price before and after the FILING date (actual report date)
                price_before = await get_price(client, ticker, filing_date, "before")
                if not price_before:
                    break  # Polygon doesn't have this stock

                price_after = await get_price(client, ticker, filing_date, "after")
                if not price_after:
                    continue

                change_pct = ((price_after - price_before) / price_before) * 100

                # Find matching earnings event in our DB (by stock_id and approximate date)
                # The period end date in our DB might be different from filing_date
                # Update the event closest to this filing date
                period_end = fin.get("end_date") or fin.get("fiscal_period")

                # Update earnings event with correct price data
                # Match by stock_id and period end date
                events_resp = httpx.get(
                    f"{settings.supabase_url}/rest/v1/earnings_events",
                    params={
                        "select": "id,report_date",
                        "stock_id": f"eq.{stock_id}",
                        "limit": "12",
                    },
                    headers=headers,
                    timeout=10,
                )

                if events_resp.status_code == 200:
                    events = events_resp.json()
                    # Find the event with report_date closest to period end
                    best_event = None
                    best_dist = 999
                    for ev in events:
                        try:
                            ev_date = date.fromisoformat(ev["report_date"])
                            end_date = date.fromisoformat(fin["end_date"]) if fin.get("end_date") else None
                            if end_date:
                                dist = abs((ev_date - end_date).days)
                                if dist < best_dist:
                                    best_dist = dist
                                    best_event = ev
                        except Exception:
                            continue

                    if best_event and best_dist < 60:
                        httpx.patch(
                            f"{settings.supabase_url}/rest/v1/earnings_events?id=eq.{best_event['id']}",
                            json={
                                "price_before": price_before,
                                "price_after": price_after,
                                "price_change_pct": round(change_pct, 2),
                            },
                            headers=headers,
                            timeout=10,
                        )
                        total_fetched += 1

            if total_fetched % 20 == 0 and total_fetched > 0:
                print(f"  [{total_fetched}] Latest: {ticker}")

        except Exception:
            total_skipped += 1
            continue

    await client.aclose()
    print(f"\nDone! Fetched: {total_fetched}, Skipped: {total_skipped}")


asyncio.run(main())
