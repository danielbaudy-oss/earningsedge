"""Fast backfill — no rate limit delay (paid Polygon plan)."""
import asyncio
import httpx
from datetime import date
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

settings = get_settings()
POLYGON_BASE = "https://api.polygon.io"


async def get_price(client, ticker, target_date, direction="before"):
    """Get closing price near a date."""
    from datetime import timedelta
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
        await asyncio.sleep(0.5)  # Small delay to be polite, not rate-limited
    return None


async def main():
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=15.0)

    headers = {
        "apikey": settings.supabase_service_key,
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "Content-Type": "application/json",
    }

    # Get ALL events missing price data
    resp = httpx.get(
        f"{settings.supabase_url}/rest/v1/earnings_events",
        params={
            "select": "id,stock_id,report_date,stocks(ticker)",
            "price_change_pct": "is.null",
            "eps_actual": "not.is.null",
            "report_date": f"lte.{date.today().isoformat()}",
            "order": "report_date.desc",
            "limit": "5000",
        },
        headers=headers,
        timeout=30,
    )

    events = resp.json()
    print(f"Found {len(events)} events to backfill")

    fetched = 0
    skipped = 0

    for i, event in enumerate(events):
        try:
            stock = event.get("stocks") or {}
            ticker = stock.get("ticker", "")
            if not ticker:
                continue

            report_date = event["report_date"]

            price_before = await get_price(client, ticker, report_date, "before")
            if not price_before:
                skipped += 1
                continue

            price_after = await get_price(client, ticker, report_date, "after")
            if not price_after:
                skipped += 1
                continue

            change_pct = ((price_after - price_before) / price_before) * 100

            httpx.patch(
                f"{settings.supabase_url}/rest/v1/earnings_events?id=eq.{event['id']}",
                json={
                    "price_before": price_before,
                    "price_after": price_after,
                    "price_change_pct": round(change_pct, 2),
                },
                headers=headers,
                timeout=10,
            )
            fetched += 1

            if fetched % 20 == 0:
                print(f"  [{fetched}/{len(events)}] Latest: {ticker} ({report_date}): {change_pct:+.2f}%")

        except Exception:
            skipped += 1
            continue

    await client.aclose()
    print(f"\nDone! Fetched: {fetched}, Skipped: {skipped}")


asyncio.run(main())
