"""Smart backfill — only fetch price data for stocks Polygon likely covers."""
import asyncio
import httpx
from datetime import date, timedelta
from app.core.config import get_settings
from app.db.supabase_client import get_supabase
from app.ingestion.fetch_price_reactions import get_close_price, get_price_after

settings = get_settings()


async def main():
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)

    # Only get events for stocks with exchange data (XNAS, XNYS = Polygon covered)
    # OR stocks from our original seed list (known large caps)
    headers = {
        "apikey": settings.supabase_service_key,
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "Content-Type": "application/json",
    }

    # Get stocks that have exchange info (these are on Polygon)
    url = f"{settings.supabase_url}/rest/v1/stocks"
    resp = httpx.get(url, params={
        "select": "id,ticker",
        "or": "(exchange.eq.XNAS,exchange.eq.XNYS,exchange.eq.XASE)",
    }, headers=headers, timeout=15)

    if resp.status_code != 200:
        print(f"Failed to get stocks: {resp.status_code}")
        return

    valid_stocks = {s["id"]: s["ticker"] for s in resp.json()}
    print(f"Found {len(valid_stocks)} stocks with known exchanges (Polygon-covered)")

    # Get events for these stocks that need price data
    # Fetch in batches by stock
    total_fetched = 0
    for stock_id, ticker in valid_stocks.items():
        events_resp = httpx.get(
            f"{settings.supabase_url}/rest/v1/earnings_events",
            params={
                "select": "id,report_date",
                "stock_id": f"eq.{stock_id}",
                "price_change_pct": "is.null",
                "eps_actual": "not.is.null",
                "report_date": f"lte.{date.today().isoformat()}",
                "order": "report_date.desc",
                "limit": "12",
            },
            headers=headers,
            timeout=15,
        )

        if events_resp.status_code != 200:
            continue

        events = events_resp.json()
        if not events:
            continue

        for event in events:
            try:
                report_date = event["report_date"]
                price_before = await get_close_price(client, ticker, report_date)
                await asyncio.sleep(13)

                if not price_before:
                    # Polygon doesn't have this stock — skip all remaining events for it
                    break

                price_after = await get_price_after(client, ticker, report_date)
                await asyncio.sleep(13)

                if price_before and price_after:
                    change_pct = ((price_after - price_before) / price_before) * 100
                    patch_resp = httpx.patch(
                        f"{settings.supabase_url}/rest/v1/earnings_events?id=eq.{event['id']}",
                        json={
                            "price_before": price_before,
                            "price_after": price_after,
                            "price_change_pct": round(change_pct, 2),
                        },
                        headers=headers,
                        timeout=10,
                    )
                    total_fetched += 1
                    if total_fetched % 5 == 0:
                        print(f"  [{total_fetched}] {ticker} ({report_date}): {change_pct:+.2f}%")
            except Exception:
                await asyncio.sleep(13)
                continue

    await client.aclose()
    print(f"\nDone! Fetched {total_fetched} price reactions")


asyncio.run(main())
