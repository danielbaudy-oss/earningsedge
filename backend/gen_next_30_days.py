"""Generate predictions for stocks reporting in days 8-30 to populate watchlist."""
import asyncio
import httpx
from datetime import date, timedelta
from app.core.config import get_settings
from app.db.supabase_client import get_supabase
from app.ml.predict_with_model import predict_stock, load_models
from app.ml.batch_analyze_week import fetch_history_for_stock

settings = get_settings()


async def main():
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)
    beat_model, _, _, _ = load_models()
    if not beat_model:
        print("No model")
        return

    next_week = (date.today() + timedelta(days=7)).isoformat()
    next_month = (date.today() + timedelta(days=30)).isoformat()
    today = date.today().isoformat()

    # Use SQL-style date filtering via the REST API
    # Get events between day 8 and day 30
    events = (
        sb.table("earnings_events")
        .select("id, stock_id, report_date, stocks(ticker)")
        .gte("report_date", next_week)
        .lte("report_date", next_month)
        .order("report_date")
        .limit(200)
        .execute()
    )

    # Filter to only 2026 dates (avoid old data)
    future_events = [e for e in events.data if e.get("report_date", "").startswith("2026")]
    print(f"Found {len(future_events)} events in days 8-30 (2026 only)")

    analyzed = 0
    for event in future_events:
        stock = event.get("stocks") or {}
        ticker = stock.get("ticker", "?")

        # Fetch history if needed
        has_history = await fetch_history_for_stock(client, event["stock_id"], ticker, sb)
        if not has_history:
            continue

        pred = await predict_stock(client, ticker, event["stock_id"], event["id"], "trader")
        if pred:
            try:
                sb.table("predictions").upsert(pred, on_conflict="stock_id,earnings_event_id")
                analyzed += 1
                rec = pred["recommendation"]
                score = pred["feature_importance"]["total_score"]
                if rec == "buy" and score >= 70:
                    print(f"  * {ticker} ({event['report_date']}): {rec.upper()} {score}%")
            except Exception:
                pass

        await asyncio.sleep(1.2)

    await client.aclose()
    print(f"\nDone! Analyzed {analyzed} stocks for next 30 days")


asyncio.run(main())
