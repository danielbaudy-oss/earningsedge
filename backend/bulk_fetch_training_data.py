"""
Bulk fetch historical earnings data for 100+ stocks to build training dataset.
Fetches 12 quarters of earnings history from Finnhub for each stock.
This is a one-time bootstrap — run overnight due to API rate limits.

Finnhub: 60 calls/min (1 call per stock for earnings history)
Estimated time: ~100 stocks × 1.2s = ~2 minutes for earnings
Then price reactions from Polygon: 5 calls/min = much longer
"""

import asyncio
import httpx
from datetime import date, timedelta
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

settings = get_settings()
FINNHUB_BASE = "https://finnhub.io/api/v1"
POLYGON_BASE = "https://api.polygon.io"

# Top 100 most-traded US stocks with good earnings history
TRAINING_STOCKS = [
    # Mega caps (already have some)
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B",
    "JPM", "V", "UNH", "MA", "HD", "PG", "JNJ", "COST", "ABBV", "CRM",
    "NFLX", "AMD", "INTC", "DIS", "PYPL", "BA", "NKE", "SBUX",
    # Large caps with consistent earnings
    "ADBE", "ORCL", "CSCO", "QCOM", "AVGO", "TXN", "NOW", "UBER", "ABNB",
    "SNOW", "SQ", "SHOP", "ROKU", "SNAP", "PLTR", "COIN",
    # Financials
    "GS", "MS", "BAC", "WFC", "C", "AXP", "BLK", "SCHW",
    # Healthcare
    "PFE", "MRK", "LLY", "TMO", "ABT", "BMY", "GILD", "AMGN", "ISRG",
    # Consumer
    "WMT", "TGT", "MCD", "SBUX", "KO", "PEP", "CL", "EL",
    # Industrials
    "CAT", "DE", "HON", "GE", "RTX", "LMT", "UPS", "FDX",
    # Tech
    "CRM", "PANW", "CRWD", "ZS", "DDOG", "NET", "MDB", "TEAM",
    "WDAY", "VEEV", "HUBS", "TTD", "PINS", "RBLX", "U",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG",
    # Semiconductors
    "MRVL", "LRCX", "KLAC", "AMAT", "MU", "ON", "SWKS",
    # More popular retail
    "RIVN", "LCID", "SOFI", "HOOD", "AFRM", "UPST",
]


async def fetch_earnings_history(client: httpx.AsyncClient, ticker: str) -> list:
    """Fetch up to 12 quarters of earnings from Finnhub."""
    params = {"symbol": ticker, "limit": 12, "token": settings.finnhub_api_key}
    try:
        resp = await client.get(f"{FINNHUB_BASE}/stock/earnings", params=params)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


async def fetch_price_reaction(client: httpx.AsyncClient, ticker: str, report_date: str) -> float | None:
    """Fetch post-earnings price reaction from Polygon."""
    d = date.fromisoformat(report_date)

    # Get price before (day of or day before)
    price_before = None
    for offset in range(0, 4):
        check_date = (d - timedelta(days=offset)).isoformat()
        url = f"{POLYGON_BASE}/v1/open-close/{ticker}/{check_date}"
        try:
            resp = await client.get(url, params={"adjusted": "true", "apiKey": settings.polygon_api_key})
            if resp.status_code == 200 and resp.json().get("close"):
                price_before = resp.json()["close"]
                break
        except Exception:
            pass

    # Get price after (next trading day)
    price_after = None
    for offset in range(1, 5):
        check_date = (d + timedelta(days=offset)).isoformat()
        url = f"{POLYGON_BASE}/v1/open-close/{ticker}/{check_date}"
        try:
            resp = await client.get(url, params={"adjusted": "true", "apiKey": settings.polygon_api_key})
            if resp.status_code == 200 and resp.json().get("close"):
                price_after = resp.json()["close"]
                break
        except Exception:
            pass

    if price_before and price_after:
        return round(((price_after - price_before) / price_before) * 100, 2)
    return None


async def main():
    print("=" * 60)
    print("BULK TRAINING DATA FETCH")
    print(f"Stocks: {len(set(TRAINING_STOCKS))}")
    print("=" * 60)

    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)

    # Deduplicate
    tickers = list(dict.fromkeys(TRAINING_STOCKS))

    # Step 1: Ensure all stocks exist in DB
    print("\n[1/3] Creating stock records...")
    existing = sb.table("stocks").select("id, ticker").execute()
    stock_map = {s["ticker"]: s["id"] for s in existing.data}

    for ticker in tickers:
        if ticker not in stock_map:
            try:
                result = sb.table("stocks").upsert(
                    {"ticker": ticker, "company_name": ticker, "is_active": True},
                    on_conflict="ticker"
                )
                if result.data:
                    stock_map[ticker] = result.data[0]["id"]
            except Exception:
                pass
    print(f"  {len(stock_map)} stocks in DB")

    # Step 2: Fetch earnings history from Finnhub
    print("\n[2/3] Fetching earnings history from Finnhub...")
    total_events = 0
    for i, ticker in enumerate(tickers):
        stock_id = stock_map.get(ticker)
        if not stock_id:
            continue

        earnings = await fetch_earnings_history(client, ticker)
        stored = 0
        for e in earnings:
            if not e.get("period"):
                continue
            data = {
                "stock_id": stock_id,
                "report_date": e["period"],
                "fiscal_quarter": f"Q{e.get('quarter', '?')} {e.get('year', '')}",
                "fiscal_year": e.get("year"),
                "eps_estimate": e.get("estimate"),
                "eps_actual": e.get("actual"),
                "is_confirmed": True,
            }
            if e.get("actual") is not None and e.get("estimate") and e["estimate"] != 0:
                surprise = e["actual"] - e["estimate"]
                data["eps_surprise"] = surprise
                data["eps_surprise_pct"] = (surprise / abs(e["estimate"])) * 100
            try:
                sb.table("earnings_events").upsert(data, on_conflict="stock_id,report_date")
                stored += 1
            except Exception:
                pass

        total_events += stored
        if stored > 0:
            print(f"  [{i+1}/{len(tickers)}] {ticker}: {stored} quarters")

        await asyncio.sleep(1.1)  # Finnhub rate limit

    print(f"  Total: {total_events} earnings events stored")

    # Step 3: Fetch price reactions from Polygon (slow — 5 calls/min)
    print("\n[3/3] Fetching price reactions from Polygon (this takes a while)...")
    print("  Rate limit: 5 calls/min = ~13s per price point")

    # Get events missing price data
    events_needing_prices = []
    for ticker in tickers[:50]:  # Limit to top 50 for tonight
        stock_id = stock_map.get(ticker)
        if not stock_id:
            continue
        events = (
            sb.table("earnings_events")
            .select("id, report_date, price_change_pct")
            .eq("stock_id", stock_id)
            .lte("report_date", date.today().isoformat())
            .order("report_date", desc=True)
            .limit(12)
            .execute()
        )
        for e in events.data:
            if e.get("price_change_pct") is None:
                events_needing_prices.append({"id": e["id"], "ticker": ticker, "date": e["report_date"]})

    print(f"  {len(events_needing_prices)} events need price data")
    print(f"  Estimated time: {len(events_needing_prices) * 26 // 60} minutes")

    fetched = 0
    for i, event in enumerate(events_needing_prices):
        change = await fetch_price_reaction(client, event["ticker"], event["date"])
        if change is not None:
            try:
                headers = {
                    "apikey": settings.supabase_service_key,
                    "Authorization": f"Bearer {settings.supabase_service_key}",
                    "Content-Type": "application/json",
                }
                url = f"{settings.supabase_url}/rest/v1/earnings_events?id=eq.{event['id']}"
                async with httpx.AsyncClient() as patch_client:
                    await patch_client.patch(url, json={"price_change_pct": change}, headers=headers)
                fetched += 1
                if fetched % 10 == 0:
                    print(f"  [{fetched}/{len(events_needing_prices)}] Latest: {event['ticker']} {event['date']}: {change:+.2f}%")
            except Exception:
                pass

        await asyncio.sleep(13)  # Polygon rate limit: 5/min, 2 calls per event

    await client.aclose()
    print(f"\n  Fetched {fetched} price reactions")
    print("\n" + "=" * 60)
    print("DONE! Retrain the model with:")
    print("  python -m app.ml.train_xgboost")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
