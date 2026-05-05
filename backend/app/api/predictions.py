"""Prediction endpoints with explanation layer."""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import get_db
from app.db.models import Prediction, Stock, EarningsEvent
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()


class PredictionResponse(BaseModel):
    id: int
    ticker: str
    company_name: str
    earnings_date: Optional[str] = None
    recommendation: str  # "buy", "sell", "avoid"
    confidence_score: float

    # Probabilities
    beat_probability: Optional[float] = None
    miss_probability: Optional[float] = None
    price_up_probability: Optional[float] = None
    price_down_probability: Optional[float] = None

    # Movement
    expected_move_pct: Optional[float] = None
    expected_volatility: Optional[float] = None
    predicted_direction: Optional[str] = None

    # Explanation
    feature_importance: Optional[dict] = None
    explanation_text: Optional[str] = None

    # Outcome (if available)
    actual_outcome: Optional[str] = None
    actual_move_pct: Optional[float] = None
    prediction_correct: Optional[bool] = None

    model_version: str
    prediction_date: datetime

    class Config:
        from_attributes = True


@router.get("/{ticker}", response_model=PredictionResponse)
async def get_prediction(ticker: str, db: AsyncSession = Depends(get_db)):
    """Get latest prediction for a stock's upcoming earnings."""
    query = (
        select(Prediction, Stock, EarningsEvent)
        .join(Stock, Prediction.stock_id == Stock.id)
        .join(EarningsEvent, Prediction.earnings_event_id == EarningsEvent.id)
        .where(Stock.ticker == ticker.upper())
        .order_by(Prediction.prediction_date.desc())
        .limit(1)
    )
    result = await db.execute(query)
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="No prediction found for this stock")

    pred, stock, event = row
    return PredictionResponse(
        id=pred.id,
        ticker=stock.ticker,
        company_name=stock.company_name,
        earnings_date=event.report_date.isoformat() if event.report_date else None,
        recommendation=pred.recommendation.value,
        confidence_score=pred.confidence_score,
        beat_probability=pred.beat_probability,
        miss_probability=pred.miss_probability,
        price_up_probability=pred.price_up_probability,
        price_down_probability=pred.price_down_probability,
        expected_move_pct=pred.expected_move_pct,
        expected_volatility=pred.expected_volatility,
        predicted_direction=pred.predicted_direction,
        feature_importance=pred.feature_importance,
        explanation_text=pred.explanation_text,
        actual_outcome=pred.actual_outcome,
        actual_move_pct=pred.actual_move_pct,
        prediction_correct=pred.prediction_correct,
        model_version=pred.model_version,
        prediction_date=pred.prediction_date,
    )


@router.get("/upcoming/all", response_model=list[PredictionResponse])
async def get_upcoming_predictions(
    min_confidence: float = Query(0.0, ge=0, le=1),
    recommendation: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get predictions for all upcoming earnings, sorted by confidence."""
    from datetime import date

    query = (
        select(Prediction, Stock, EarningsEvent)
        .join(Stock, Prediction.stock_id == Stock.id)
        .join(EarningsEvent, Prediction.earnings_event_id == EarningsEvent.id)
        .where(
            EarningsEvent.report_date >= date.today(),
            Prediction.confidence_score >= min_confidence,
        )
        .order_by(Prediction.confidence_score.desc())
        .limit(limit)
    )

    if recommendation:
        from app.db.models import RecommendationEnum
        query = query.where(
            Prediction.recommendation == RecommendationEnum(recommendation)
        )

    result = await db.execute(query)
    rows = result.all()

    return [
        PredictionResponse(
            id=pred.id,
            ticker=stock.ticker,
            company_name=stock.company_name,
            earnings_date=event.report_date.isoformat() if event.report_date else None,
            recommendation=pred.recommendation.value,
            confidence_score=pred.confidence_score,
            beat_probability=pred.beat_probability,
            miss_probability=pred.miss_probability,
            price_up_probability=pred.price_up_probability,
            price_down_probability=pred.price_down_probability,
            expected_move_pct=pred.expected_move_pct,
            expected_volatility=pred.expected_volatility,
            predicted_direction=pred.predicted_direction,
            feature_importance=pred.feature_importance,
            explanation_text=pred.explanation_text,
            model_version=pred.model_version,
            prediction_date=pred.prediction_date,
        )
        for pred, stock, event in rows
    ]
