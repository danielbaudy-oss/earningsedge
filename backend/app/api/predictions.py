"""Prediction endpoints using Supabase client."""

from fastapi import APIRouter, Query, HTTPException
from app.db.supabase_client import get_supabase
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime

router = APIRouter()


class PredictionResponse(BaseModel):
    id: int
    ticker: Optional[str] = None
    company_name: Optional[str] = None
    earnings_date: Optional[str] = None
    recommendation: str
    confidence_score: float
    beat_probability: Optional[float] = None
    miss_probability: Optional[float] = None
    price_up_probability: Optional[float] = None
    price_down_probability: Optional[float] = None
    expected_move_pct: Optional[float] = None
    expected_volatility: Optional[float] = None
    predicted_direction: Optional[str] = None
    feature_importance: Optional[dict] = None
    explanation_text: Optional[str] = None
    actual_outcome: Optional[str] = None
    actual_move_pct: Optional[float] = None
    prediction_correct: Optional[bool] = None
    model_version: str = ""
    prediction_date: Optional[str] = None


@router.get("/{ticker}", response_model=PredictionResponse)
async def get_prediction(ticker: str):
    """Get latest prediction for a stock's upcoming earnings."""
    sb = get_supabase()

    # Get stock
    stock_result = sb.table("stocks").select("id,ticker,company_name").eq("ticker", ticker.upper()).execute()
    if not stock_result.data:
        raise HTTPException(status_code=404, detail="Stock not found")

    stock = stock_result.data[0]

    # Get latest prediction
    pred_result = (
        sb.table("predictions")
        .select("*, earnings_events(report_date)")
        .eq("stock_id", stock["id"])
        .order("prediction_date", desc=True)
        .limit(1)
        .execute()
    )

    if not pred_result.data:
        raise HTTPException(status_code=404, detail="No prediction found")

    pred = pred_result.data[0]
    event = pred.get("earnings_events") or {}

    return PredictionResponse(
        id=pred["id"],
        ticker=stock["ticker"],
        company_name=stock["company_name"],
        earnings_date=event.get("report_date"),
        recommendation=pred["recommendation"],
        confidence_score=pred["confidence_score"],
        beat_probability=pred.get("beat_probability"),
        miss_probability=pred.get("miss_probability"),
        price_up_probability=pred.get("price_up_probability"),
        price_down_probability=pred.get("price_down_probability"),
        expected_move_pct=pred.get("expected_move_pct"),
        expected_volatility=pred.get("expected_volatility"),
        predicted_direction=pred.get("predicted_direction"),
        feature_importance=pred.get("feature_importance"),
        explanation_text=pred.get("explanation_text"),
        actual_outcome=pred.get("actual_outcome"),
        actual_move_pct=pred.get("actual_move_pct"),
        prediction_correct=pred.get("prediction_correct"),
        model_version=pred.get("model_version", ""),
        prediction_date=pred.get("prediction_date"),
    )


@router.get("/upcoming/all", response_model=list[PredictionResponse])
async def get_upcoming_predictions(
    min_confidence: float = Query(0.0, ge=0, le=1),
    recommendation: Optional[str] = Query(None),
    mode: Optional[str] = Query("trader", description="trader or longterm"),
    limit: int = Query(20, le=100),
):
    """Get predictions for earnings in the next 7 days, sorted by confidence."""
    sb = get_supabase()
    today = date.today().isoformat()
    from datetime import timedelta
    next_week = (date.today() + timedelta(days=7)).isoformat()

    query = (
        sb.table("predictions")
        .select("*, stocks(ticker, company_name), earnings_events(report_date)")
        .gte("confidence_score", min_confidence)
        .order("confidence_score", desc=True)
        .limit(limit)
    )

    if recommendation:
        query = query.eq("recommendation", recommendation)

    result = query.execute()

    predictions = []
    for pred in result.data:
        event = pred.get("earnings_events") or {}
        stock = pred.get("stocks") or {}
        report_date = event.get("report_date", "")
        # Only include if earnings date is within the next 7 days
        if report_date and report_date >= today and report_date <= next_week:
            predictions.append(PredictionResponse(
                id=pred["id"],
                ticker=stock.get("ticker"),
                company_name=stock.get("company_name"),
                earnings_date=event.get("report_date"),
                recommendation=pred["recommendation"],
                confidence_score=pred["confidence_score"],
                beat_probability=pred.get("beat_probability"),
                miss_probability=pred.get("miss_probability"),
                price_up_probability=pred.get("price_up_probability"),
                price_down_probability=pred.get("price_down_probability"),
                expected_move_pct=pred.get("expected_move_pct"),
                expected_volatility=pred.get("expected_volatility"),
                predicted_direction=pred.get("predicted_direction"),
                feature_importance=pred.get("feature_importance"),
                explanation_text=pred.get("explanation_text"),
                model_version=pred.get("model_version", ""),
                prediction_date=pred.get("prediction_date"),
            ))

    return predictions


@router.get("/watchlist", response_model=list[PredictionResponse])
async def get_watchlist(limit: int = Query(3, le=10)):
    """
    Top picks for the next 30 days.
    Returns the highest-conviction, highest-expected-move BUY predictions
    reporting in the next month. These are stocks to watch and position in early.
    """
    sb = get_supabase()
    from datetime import timedelta
    today = date.today().isoformat()
    next_month = (date.today() + timedelta(days=30)).isoformat()

    result = (
        sb.table("predictions")
        .select("*, stocks(ticker, company_name), earnings_events(report_date)")
        .eq("recommendation", "buy")
        .order("confidence_score", desc=True)
        .limit(50)
        .execute()
    )

    # Filter to next 30 days, sort by score * expected_move
    candidates = []
    for pred in result.data:
        event = pred.get("earnings_events") or {}
        stock = pred.get("stocks") or {}
        report_date = event.get("report_date", "")
        if not report_date or report_date < today or report_date > next_month:
            continue
        # Skip this week (those are in Top Trades already)
        next_week = (date.today() + timedelta(days=7)).isoformat()
        if report_date <= next_week:
            continue

        score = pred.get("confidence_score", 0)
        move = pred.get("expected_move_pct", 0) or 0
        opportunity_score = score * max(move, 0.5)  # Rank by combined signal

        candidates.append((opportunity_score, pred, stock, event))

    # Sort by opportunity and take top N
    candidates.sort(key=lambda x: x[0], reverse=True)

    return [
        PredictionResponse(
            id=pred["id"],
            ticker=stock.get("ticker"),
            company_name=stock.get("company_name"),
            earnings_date=event.get("report_date"),
            recommendation=pred["recommendation"],
            confidence_score=pred["confidence_score"],
            beat_probability=pred.get("beat_probability"),
            miss_probability=pred.get("miss_probability"),
            price_up_probability=pred.get("price_up_probability"),
            price_down_probability=pred.get("price_down_probability"),
            expected_move_pct=pred.get("expected_move_pct"),
            expected_volatility=pred.get("expected_volatility"),
            predicted_direction=pred.get("predicted_direction"),
            feature_importance=pred.get("feature_importance"),
            explanation_text=pred.get("explanation_text"),
            model_version=pred.get("model_version", ""),
            prediction_date=pred.get("prediction_date"),
        )
        for _, pred, stock, event in candidates[:limit]
    ]


@router.post("/analyze/{ticker}")
async def analyze_stock(ticker: str, mode: Optional[str] = Query("trader")):
    """
    On-demand analysis: generate a fresh prediction for any ticker.
    Fetches live data from Finnhub (including historical earnings if missing)
    and runs the ML model. ~2-3 seconds per stock.
    """
    import httpx
    from app.ml.predict_with_model import predict_stock, load_models
    from app.db.supabase_client import get_supabase
    from app.core.config import get_settings

    settings_local = get_settings()
    sb = get_supabase()

    # Find or create the stock
    stock_result = sb.table("stocks").select("id, ticker, company_name").eq("ticker", ticker.upper()).execute()
    if not stock_result.data:
        new_stock = sb.table("stocks").insert({"ticker": ticker.upper(), "company_name": ticker.upper(), "is_active": True})
        if not new_stock.data:
            raise HTTPException(status_code=404, detail="Could not find or create stock")
        stock = new_stock.data[0]
    else:
        stock = stock_result.data[0]

    # Find upcoming earnings event
    from datetime import date as d
    event_result = (
        sb.table("earnings_events")
        .select("id, report_date")
        .eq("stock_id", stock["id"])
        .gte("report_date", d.today().isoformat())
        .order("report_date")
        .limit(1)
        .execute()
    )

    if not event_result.data:
        # No upcoming earnings in DB — try fetching next earnings date from Finnhub
        async with httpx.AsyncClient(timeout=15.0) as client:
            params = {"symbol": ticker.upper(), "token": settings_local.finnhub_api_key}
            resp = await client.get("https://finnhub.io/api/v1/calendar/earnings", params={
                **params,
                "from": d.today().isoformat(),
                "to": (d.today() + __import__('datetime').timedelta(days=90)).isoformat(),
            })
            if resp.status_code == 200:
                cal = resp.json().get("earningsCalendar", [])
                match = next((e for e in cal if e.get("symbol") == ticker.upper()), None)
                if match:
                    # Store it
                    earnings_data = {
                        "stock_id": stock["id"],
                        "report_date": match.get("date"),
                        "fiscal_quarter": f"Q{match.get('quarter', '?')} {match.get('year', '')}",
                        "report_time": "before_market" if match.get("hour") == "bmo" else "after_market",
                        "eps_estimate": match.get("epsEstimate"),
                        "revenue_estimate": match.get("revenueEstimate"),
                        "is_confirmed": True,
                    }
                    try:
                        sb.table("earnings_events").upsert(earnings_data, on_conflict="stock_id,report_date")
                    except Exception:
                        pass

                    return {
                        "ticker": ticker.upper(),
                        "company_name": stock.get("company_name", ticker),
                        "has_upcoming_earnings": True,
                        "earnings_date": match.get("date"),
                        "message": f"Next earnings: {match.get('date')}. Not enough recent data to generate a full prediction yet — check back closer to the date.",
                    }

        return {
            "ticker": ticker.upper(),
            "company_name": stock.get("company_name", ticker),
            "has_upcoming_earnings": False,
            "message": "No upcoming earnings event found. Check back closer to their reporting date.",
        }

    event = event_result.data[0]

    # Check if we have historical earnings — if not, fetch them from Finnhub
    history_result = (
        sb.table("earnings_events")
        .select("id")
        .eq("stock_id", stock["id"])
        .lte("report_date", d.today().isoformat())
        .limit(1)
        .execute()
    )

    if not history_result.data:
        # Fetch historical earnings from Finnhub on-demand
        async with httpx.AsyncClient(timeout=30.0) as client:
            params = {"symbol": ticker.upper(), "limit": 8, "token": settings_local.finnhub_api_key}
            resp = await client.get("https://finnhub.io/api/v1/stock/earnings", params=params)
            if resp.status_code == 200:
                earnings = resp.json()
                if isinstance(earnings, list):
                    for e in earnings:
                        if not e.get("period"):
                            continue
                        earnings_data = {
                            "stock_id": stock["id"],
                            "report_date": e.get("period"),
                            "fiscal_quarter": f"Q{e.get('quarter', '?')} {e.get('year', '')}",
                            "fiscal_year": e.get("year"),
                            "eps_estimate": e.get("estimate"),
                            "eps_actual": e.get("actual"),
                            "is_confirmed": True,
                        }
                        if e.get("actual") is not None and e.get("estimate") and e["estimate"] != 0:
                            surprise = e["actual"] - e["estimate"]
                            earnings_data["eps_surprise"] = surprise
                            earnings_data["eps_surprise_pct"] = (surprise / abs(e["estimate"])) * 100
                        try:
                            sb.table("earnings_events").upsert(earnings_data, on_conflict="stock_id,report_date")
                        except Exception:
                            pass

    # Check if models are loaded
    beat_model, _, _, _ = load_models()
    if beat_model is None:
        raise HTTPException(status_code=503, detail="ML models not trained yet")

    # Generate prediction
    async with httpx.AsyncClient(timeout=30.0) as client:
        pred = await predict_stock(client, ticker.upper(), stock["id"], event["id"], mode or "trader")

    if pred is None:
        return {
            "ticker": ticker.upper(),
            "company_name": stock.get("company_name", ticker),
            "earnings_date": event["report_date"],
            "has_upcoming_earnings": True,
            "message": "Insufficient historical data to generate a prediction for this stock.",
        }

    # Store the prediction
    try:
        sb.table("predictions").upsert(pred, on_conflict="stock_id,earnings_event_id")
    except Exception:
        pass

    return PredictionResponse(
        id=0,
        ticker=ticker.upper(),
        company_name=stock.get("company_name", ticker),
        earnings_date=event["report_date"],
        recommendation=pred["recommendation"],
        confidence_score=pred["confidence_score"],
        beat_probability=pred.get("beat_probability"),
        miss_probability=pred.get("miss_probability"),
        price_up_probability=pred.get("price_up_probability"),
        price_down_probability=pred.get("price_down_probability"),
        expected_move_pct=pred.get("expected_move_pct"),
        expected_volatility=pred.get("expected_volatility"),
        predicted_direction=pred.get("predicted_direction"),
        feature_importance=pred.get("feature_importance"),
        explanation_text=pred.get("explanation_text"),
        model_version=pred.get("model_version", ""),
        prediction_date=None,
    )
