"""
Daily scheduled job — runs once per day.

Pipeline:
1. Sync earnings calendar (next 14 days) — cross-validated FMP + Finnhub
2. Verify recent earnings actually happened (confirm dates with FMP)
3. Fetch actual EPS results for recently reported stocks
4. Fetch price reactions (T+1) for confirmed reports
5. Update prediction outcomes (feedback loop)
6. Retrain model if enough new outcomes
7. Generate predictions for upcoming week

Key principle: NEVER store a price reaction unless we've confirmed
the earnings actually happened on that date.
"""

import asyncio
from datetime import date, timedelta
from app.core.config import get_settings
from app.ingestion.sync_calendar import sync_earnings_calendar
from app.services.feedback_loop import update_prediction_outcomes, get_model_accuracy
from app.ml.batch_analyze_week import batch_analyze
from app.ml.train_xgboost import main as train_model

settings = get_settings()


async def verify_and_fetch_actuals():
    """
    For earnings events in the last 7 days that don't have actuals yet:
    1. Check FMP to confirm the earnings actually happened
    2. If confirmed, store the actual EPS and revenue
    3. Only THEN is it safe to fetch price reactions
    
    This prevents storing price reactions for events that got rescheduled.
    """
    import httpx
    from app.db.supabase_client import get_supabase

    sb = get_supabase()
    today = date.today()
    week_ago = (today - timedelta(days=7)).isoformat()

    # Get recent events without actuals
    recent = (
        sb.table("earnings_events")
        .select("id, stock_id, report_date, eps_actual, stocks(ticker)")
        .gte("report_date", week_ago)
        .lte("report_date", today.isoformat())
        .order("report_date", desc=True)
        .execute()
    )

    need_verification = [e for e in recent.data if e.get("eps_actual") is None]
    if not need_verification:
        return 0

    print(f"  Verifying {len(need_verification)} recent events...")

    # Fetch from FMP for the past week (gives us confirmed actuals)
    verified = 0
    if settings.fmp_api_key:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://financialmodelingprep.com/stable/earnings-calendar",
                params={
                    "from": week_ago,
                    "to": today.isoformat(),
                    "apikey": settings.fmp_api_key,
                },
            )
            if resp.status_code == 200:
                fmp_data = resp.json()
                # Build lookup by symbol
                fmp_map = {}
                for e in (fmp_data if isinstance(fmp_data, list) else []):
                    if e.get("epsActual") is not None:
                        fmp_map[e["symbol"]] = e

                # Update our events with confirmed actuals
                for event in need_verification:
                    ticker = (event.get("stocks") or {}).get("ticker", "")
                    fmp_event = fmp_map.get(ticker)
                    if fmp_event and fmp_event.get("epsActual") is not None:
                        update_data = {
                            "eps_actual": fmp_event["epsActual"],
                            "is_confirmed": True,
                        }
                        if fmp_event.get("epsEstimated"):
                            update_data["eps_estimate"] = fmp_event["epsEstimated"]
                            surprise = fmp_event["epsActual"] - fmp_event["epsEstimated"]
                            update_data["eps_surprise"] = surprise
                            if fmp_event["epsEstimated"] != 0:
                                update_data["eps_surprise_pct"] = (surprise / abs(fmp_event["epsEstimated"])) * 100
                        if fmp_event.get("revenueActual"):
                            update_data["revenue_actual"] = fmp_event["revenueActual"]
                        if fmp_event.get("revenueEstimated"):
                            update_data["revenue_estimate"] = fmp_event["revenueEstimated"]

                        # Verify the date matches
                        if fmp_event.get("date") and fmp_event["date"] != event["report_date"]:
                            update_data["report_date"] = fmp_event["date"]
                            print(f"    {ticker}: date corrected {event['report_date']} → {fmp_event['date']}")

                        try:
                            headers = {
                                "apikey": settings.supabase_service_key,
                                "Authorization": f"Bearer {settings.supabase_service_key}",
                                "Content-Type": "application/json",
                            }
                            url = f"{settings.supabase_url}/rest/v1/earnings_events?id=eq.{event['id']}"
                            async with httpx.AsyncClient() as patch_client:
                                await patch_client.patch(url, json=update_data, headers=headers)
                            verified += 1
                        except Exception:
                            pass

    # Fallback: also check Finnhub for actuals
    if verified < len(need_verification):
        async with httpx.AsyncClient(timeout=15.0) as client:
            for event in need_verification:
                ticker = (event.get("stocks") or {}).get("ticker", "")
                if not ticker:
                    continue

                # Check if Finnhub has actuals
                resp = await client.get(
                    "https://finnhub.io/api/v1/stock/earnings",
                    params={"symbol": ticker, "limit": 1, "token": settings.finnhub_api_key},
                )
                if resp.status_code == 200:
                    earnings = resp.json()
                    if earnings and isinstance(earnings, list) and earnings[0].get("actual") is not None:
                        latest = earnings[0]
                        update_data = {
                            "eps_actual": latest["actual"],
                            "is_confirmed": True,
                        }
                        if latest.get("estimate"):
                            update_data["eps_estimate"] = latest["estimate"]
                            surprise = latest["actual"] - latest["estimate"]
                            update_data["eps_surprise"] = surprise
                            if latest["estimate"] != 0:
                                update_data["eps_surprise_pct"] = (surprise / abs(latest["estimate"])) * 100

                        try:
                            headers = {
                                "apikey": settings.supabase_service_key,
                                "Authorization": f"Bearer {settings.supabase_service_key}",
                                "Content-Type": "application/json",
                            }
                            url = f"{settings.supabase_url}/rest/v1/earnings_events?id=eq.{event['id']}"
                            async with httpx.AsyncClient() as patch_client:
                                await patch_client.patch(url, json=update_data, headers=headers)
                            verified += 1
                        except Exception:
                            pass

                await asyncio.sleep(1.2)  # Finnhub rate limit

    return verified


async def fetch_confirmed_price_reactions():
    """
    Fetch price reactions ONLY for events where:
    1. eps_actual is populated (earnings confirmed happened)
    2. is_confirmed = true (date is verified)
    3. price_change_pct is still null (not yet fetched)
    
    This ensures we never store a price reaction for a wrong date.
    """
    import httpx
    from app.db.supabase_client import get_supabase
    from app.ingestion.fetch_price_reactions import get_pre_earnings_close, get_price_after

    sb = get_supabase()
    today = date.today()

    # Get confirmed events without price data (last 14 days)
    two_weeks_ago = (today - timedelta(days=14)).isoformat()
    events = (
        sb.table("earnings_events")
        .select("id, stock_id, report_date, report_time, eps_actual, price_change_pct, stocks(ticker)")
        .gte("report_date", two_weeks_ago)
        .lte("report_date", today.isoformat())
        .eq("is_confirmed", True)
        .order("report_date", desc=True)
        .execute()
    )

    # Filter: has actuals but no price
    need_price = [e for e in events.data
                  if e.get("eps_actual") is not None and e.get("price_change_pct") is None]

    if not need_price:
        return 0

    print(f"  Fetching prices for {len(need_price)} confirmed events...")

    client = httpx.AsyncClient(timeout=15.0)
    fetched = 0

    for event in need_price:
        ticker = (event.get("stocks") or {}).get("ticker", "")
        if not ticker:
            continue

        report_date = event["report_date"]
        report_time = event.get("report_time", "after_market")

        price_before = await get_pre_earnings_close(client, ticker, report_date, report_time)
        if not price_before:
            continue

        price_after = await get_price_after(client, ticker, report_date, report_time)
        if not price_after:
            continue

        change_pct = ((price_after - price_before) / price_before) * 100

        try:
            headers = {
                "apikey": settings.supabase_service_key,
                "Authorization": f"Bearer {settings.supabase_service_key}",
                "Content-Type": "application/json",
            }
            url = f"{settings.supabase_url}/rest/v1/earnings_events?id=eq.{event['id']}"
            async with httpx.AsyncClient() as patch_client:
                await patch_client.patch(url, json={
                    "price_before": price_before,
                    "price_after": price_after,
                    "price_change_pct": round(change_pct, 2),
                }, headers=headers)
            fetched += 1
            print(f"    {ticker} ({report_date}): {change_pct:+.1f}%")
        except Exception:
            pass

    await client.aclose()
    return fetched


async def run_daily_job():
    """Full daily pipeline."""
    print("=" * 60)
    print(f"🕐 Daily Job — {date.today().isoformat()}")
    print("=" * 60)

    # Step 1: Sync calendar (next 14 days, cross-validated)
    print("\n📅 Step 1: Syncing earnings calendar...")
    try:
        await sync_earnings_calendar(14)
    except Exception as e:
        print(f"  ⚠️ Calendar sync failed: {e}")

    # Step 2: Verify recent earnings and fetch actuals
    print("\n✅ Step 2: Verifying recent earnings & fetching actuals...")
    try:
        verified = await verify_and_fetch_actuals()
        print(f"  Verified {verified} earnings events with actuals")
    except Exception as e:
        print(f"  ⚠️ Verification failed: {e}")

    # Step 3: Fetch price reactions for CONFIRMED events only
    print("\n📈 Step 3: Fetching price reactions (confirmed events only)...")
    try:
        fetched = await fetch_confirmed_price_reactions()
        print(f"  Fetched {fetched} price reactions")
    except Exception as e:
        print(f"  ⚠️ Price reaction fetch failed: {e}")

    # Step 4: Update prediction outcomes (feedback loop)
    print("\n🔄 Step 4: Updating prediction outcomes...")
    try:
        updated = await update_prediction_outcomes()
        print(f"  Updated {updated} outcomes")
    except Exception as e:
        print(f"  ⚠️ Outcome update failed: {e}")

    # Step 5: Check model accuracy and retrain if needed
    print("\n📊 Step 5: Checking model accuracy...")
    try:
        metrics = await get_model_accuracy()
        print(f"  Predictions with outcomes: {metrics.get('predictions_with_outcomes', 0)}")
        print(f"  Recommendation accuracy: {metrics.get('recommendation_accuracy', 0):.1%}")
        print(f"  Direction accuracy: {metrics.get('direction_accuracy', 0):.1%}")
        print(f"  Avg move error: {metrics.get('avg_move_error_pct', 0):.2f}%")

        if metrics.get("needs_retraining"):
            print("\n🤖 Step 5b: Retraining model...")
            try:
                await train_model()
                print("  ✅ Model retrained!")
            except Exception as e:
                print(f"  ⚠️ Retraining failed: {e}")
        else:
            print(f"  Model OK — retraining after 20+ new outcomes")
    except Exception as e:
        print(f"  ⚠️ Accuracy check failed: {e}")

    # Step 6: Generate predictions for upcoming week
    print("\n🤖 Step 6: Analyzing stocks reporting this week...")
    try:
        await batch_analyze()
    except Exception as e:
        print(f"  ⚠️ Batch analysis failed: {e}")

    print("\n" + "=" * 60)
    print("✅ Daily job complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_daily_job())
