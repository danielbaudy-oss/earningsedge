"""
Batch analyze all stocks reporting earnings in the next 7 days.
Fetches historical data from Finnhub on-demand and generates predictions.
"""

import asyncio
import httpx
from datetime import date, timedelta
from app.core.config import get_settings
from app.db.supabase_client import get_supabase
from app.ml.predict_with_model import predict_stock, load_models

settings = get_settings()
FINNHUB_BASE = "https://finnhub.io/api/v1"


async def fetch_history_for_stock(client: httpx.AsyncClient, stock_id: int, ticker: str, sb):
    """Fetch historical earnings from Finnhub if missing."""
    # Check if we already have history
    existing = (
        sb.table("earnings_events")
        .select("id")
        .eq("stock_id", stock_id)
        .lte("report_date", date.today().isoformat())
        .limit(1)
        .execute()
    )
    if existing.data:
        return True  # Already have history

    # Fetch from Finnhub
    params = {"symbol": ticker, "limit": 8, "token": settings.finnhub_api_key}
    resp = await client.get(f"{FINNHUB_BASE}/stock/earnings", params=params)
    if resp.status_code != 200:
        return False

    earnings = resp.json()
    if not isinstance(earnings, list) or not earnings:
        return False

    for e in earnings:
        if not e.get("period"):
            continue
        data = {
            "stock_id": stock_id,
            "report_date": e.get("period"),
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
        except Exception:
            pass

    return True


async def batch_analyze():
    """Analyze all stocks reporting in the next 7 days."""
    print("🔄 Batch analyzing stocks reporting this week...\n")
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)

    # Check models
    beat_model, _, _, _ = load_models()
    if beat_model is None:
        print("❌ Models not trained. Run train_xgboost.py first.")
        return

    today = date.today().isoformat()
    next_week = (date.today() + timedelta(days=7)).isoformat()

    # Get all earnings events this week (FUTURE ONLY)
    events = (
        sb.table("earnings_events")
        .select("id, stock_id, report_date, stocks(ticker, company_name)")
        .gte("report_date", today)
        .lte("report_date", next_week)
        .order("report_date")
        .execute()
    )

    # Double-check: only process events that are actually in the future
    future_events = [e for e in events.data if e.get("report_date", "") >= today]
    print(f"  Found {len(future_events)} earnings events from {today} to {next_week}")

    analyzed = 0
    skipped = 0
    for event in future_events:
        stock = event.get("stocks") or {}
        ticker = stock.get("ticker", "???")

        # Fetch history if needed
        has_history = await fetch_history_for_stock(client, event["stock_id"], ticker, sb)
        if not has_history:
            skipped += 1
            continue

        # Generate prediction
        pred = await predict_stock(client, ticker, event["stock_id"], event["id"], "trader")
        if pred is None:
            skipped += 1
            continue

        # Store
        try:
            sb.table("predictions").upsert(pred, on_conflict="stock_id,earnings_event_id")
            analyzed += 1
            emoji = {"buy": "🟢", "sell": "🔴", "avoid": "🟡"}[pred["recommendation"]]
            print(f"  {emoji} {ticker} ({event['report_date']}): "
                  f"{pred['recommendation'].upper()} Score:{pred['feature_importance']['total_score']}%")
        except Exception as e:
            print(f"  ❌ {ticker}: {e}")
            skipped += 1

        # Rate limit (Finnhub: 60/min)
        await asyncio.sleep(1.2)

    await client.aclose()
    print(f"\n✅ Analyzed {analyzed} stocks, skipped {skipped} (insufficient data)")


if __name__ == "__main__":
    asyncio.run(batch_analyze())
