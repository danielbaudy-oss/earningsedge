"""Sync calendar for next 30 days, then analyze all stocks."""
import asyncio
import httpx
from datetime import date, timedelta
from app.core.config import get_settings
from app.db.supabase_client import get_supabase
from app.ml.predict_with_model import predict_stock, load_models
from app.ml.batch_analyze_week import fetch_history_for_stock

settings = get_settings()
FINNHUB_BASE = "https://finnhub.io/api/v1"


async def main():
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)

    # Step 1: Sync calendar for next 30 days
    print("Syncing earnings calendar (next 30 days)...")
    today = date.today()
    end_date = today + timedelta(days=30)

    params = {
        "from": today.isoformat(),
        "to": end_date.isoformat(),
        "token": settings.finnhub_api_key,
    }
    resp = await client.get(f"{FINNHUB_BASE}/calendar/earnings", params=params)
    calendar = resp.json().get("earningsCalendar", [])
    print(f"  Found {len(calendar)} events from Finnhub")

    # Get existing stocks
    existing = sb.table("stocks").select("id, ticker").execute()
    stock_map = {s["ticker"]: s["id"] for s in existing.data}

    # Only process events in days 8-30 (skip this week, already done)
    next_week = today + timedelta(days=7)
    future_events = []

    for event in calendar:
        ticker = event.get("symbol", "")
        event_date = event.get("date", "")
        if not ticker or not event_date:
            continue
        if event_date <= next_week.isoformat():
            continue  # Skip this week

        # Create stock if needed
        if ticker not in stock_map:
            try:
                result = sb.table("stocks").upsert(
                    {"ticker": ticker, "company_name": ticker, "is_active": True},
                    on_conflict="ticker"
                )
                if result.data:
                    stock_map[ticker] = result.data[0]["id"]
            except Exception:
                continue

        stock_id = stock_map.get(ticker)
        if not stock_id:
            continue

        # Store earnings event
        earnings_data = {
            "stock_id": stock_id,
            "report_date": event_date,
            "fiscal_quarter": f"Q{event.get('quarter', '?')} {event.get('year', '')}",
            "report_time": "before_market" if event.get("hour") == "bmo" else "after_market",
            "eps_estimate": event.get("epsEstimate"),
            "revenue_estimate": event.get("revenueEstimate"),
            "is_confirmed": True,
        }
        try:
            result = sb.table("earnings_events").upsert(earnings_data, on_conflict="stock_id,report_date")
            if result.data:
                future_events.append({
                    "id": result.data[0]["id"],
                    "stock_id": stock_id,
                    "ticker": ticker,
                    "report_date": event_date,
                })
        except Exception:
            pass

    print(f"  Stored {len(future_events)} events for days 8-30")

    # Step 2: Analyze them
    beat_model, _, _, _ = load_models()
    if not beat_model:
        print("No model!")
        return

    print(f"\nAnalyzing {len(future_events)} stocks...")
    analyzed = 0
    buys = []

    for event in future_events:
        ticker = event["ticker"]
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
                    buys.append(f"  {ticker} ({event['report_date']}): BUY {score}%")
            except Exception:
                pass

        await asyncio.sleep(1.2)

    await client.aclose()
    print(f"\nAnalyzed {analyzed} stocks")
    print(f"\nTop BUY picks for next 30 days:")
    for b in sorted(buys, reverse=True)[:10]:
        print(b)


asyncio.run(main())
