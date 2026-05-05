"""Generate predictions for tracked stocks reporting in days 8-30 (watchlist)."""
import asyncio
import httpx
from datetime import date, timedelta
from app.db.supabase_client import get_supabase
from app.ml.predict_with_model import predict_stock, load_models
from app.core.config import get_settings

settings = get_settings()

# Our tracked stocks with upcoming earnings beyond this week
WATCHLIST_EVENTS = [
    {"id": 113, "stock_id": 13, "ticker": "HD", "report_date": "2026-05-19"},
    {"id": 111, "stock_id": 5, "ticker": "NVDA", "report_date": "2026-05-20"},
    {"id": 112, "stock_id": 44, "ticker": "CSCO", "report_date": "2026-05-20"},
    {"id": 110, "stock_id": 50, "ticker": "SNOW", "report_date": "2026-05-27"},
    {"id": 109, "stock_id": 18, "ticker": "COST", "report_date": "2026-05-28"},
    {"id": 108, "stock_id": 16, "ticker": "CRM", "report_date": "2026-06-03"},
    {"id": 107, "stock_id": 45, "ticker": "AVGO", "report_date": "2026-06-04"},
]


async def main():
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)
    beat_model, _, _, _ = load_models()
    if not beat_model:
        print("No model")
        return

    print(f"Generating watchlist predictions for {len(WATCHLIST_EVENTS)} stocks...\n")

    for event in WATCHLIST_EVENTS:
        ticker = event["ticker"]
        pred = await predict_stock(client, ticker, event["stock_id"], event["id"], "trader")
        if pred:
            try:
                sb.table("predictions").upsert(pred, on_conflict="stock_id,earnings_event_id")
                rec = pred["recommendation"]
                score = pred["feature_importance"]["total_score"]
                move = pred.get("expected_move_pct", 0)
                print(f"  {ticker} ({event['report_date']}): {rec.upper()} Score:{score}% Move:{move:+.1f}%")
            except Exception as e:
                print(f"  {ticker}: error {e}")
        else:
            print(f"  {ticker}: insufficient data")
        await asyncio.sleep(1.5)

    await client.aclose()
    print("\nDone!")


asyncio.run(main())
