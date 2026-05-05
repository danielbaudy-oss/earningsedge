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
    """Get predictions for all upcoming earnings, sorted by confidence."""
    sb = get_supabase()
    today = date.today().isoformat()

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
        # Only include if earnings date is in the future
        if event.get("report_date") and event["report_date"] >= today:
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
