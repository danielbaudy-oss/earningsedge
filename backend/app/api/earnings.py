"""Earnings calendar and event endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import get_db
from app.db.models import EarningsEvent, Stock
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime

router = APIRouter()


class EarningsEventResponse(BaseModel):
    id: int
    ticker: str
    company_name: str
    report_date: date
    fiscal_quarter: Optional[str] = None
    report_time: Optional[str] = None
    eps_estimate: Optional[float] = None
    revenue_estimate: Optional[float] = None
    eps_actual: Optional[float] = None
    revenue_actual: Optional[float] = None
    eps_surprise_pct: Optional[float] = None
    price_change_pct: Optional[float] = None
    is_confirmed: bool = False

    class Config:
        from_attributes = True


@router.get("/calendar", response_model=list[EarningsEventResponse])
async def get_earnings_calendar(
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    sector: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get earnings calendar for a date range."""
    query = (
        select(EarningsEvent, Stock)
        .join(Stock, EarningsEvent.stock_id == Stock.id)
        .where(
            EarningsEvent.report_date >= start_date,
            EarningsEvent.report_date <= end_date,
        )
        .order_by(EarningsEvent.report_date)
    )
    if sector:
        query = query.where(Stock.sector == sector)

    result = await db.execute(query)
    rows = result.all()

    return [
        EarningsEventResponse(
            id=event.id,
            ticker=stock.ticker,
            company_name=stock.company_name,
            report_date=event.report_date,
            fiscal_quarter=event.fiscal_quarter,
            report_time=event.report_time,
            eps_estimate=event.eps_estimate,
            revenue_estimate=event.revenue_estimate,
            eps_actual=event.eps_actual,
            revenue_actual=event.revenue_actual,
            eps_surprise_pct=event.eps_surprise_pct,
            price_change_pct=event.price_change_pct,
            is_confirmed=event.is_confirmed,
        )
        for event, stock in rows
    ]


@router.get("/upcoming", response_model=list[EarningsEventResponse])
async def get_upcoming_earnings(
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get upcoming earnings events."""
    today = date.today()
    query = (
        select(EarningsEvent, Stock)
        .join(Stock, EarningsEvent.stock_id == Stock.id)
        .where(EarningsEvent.report_date >= today)
        .order_by(EarningsEvent.report_date)
        .limit(limit)
    )
    result = await db.execute(query)
    rows = result.all()

    return [
        EarningsEventResponse(
            id=event.id,
            ticker=stock.ticker,
            company_name=stock.company_name,
            report_date=event.report_date,
            fiscal_quarter=event.fiscal_quarter,
            report_time=event.report_time,
            eps_estimate=event.eps_estimate,
            revenue_estimate=event.revenue_estimate,
            is_confirmed=event.is_confirmed,
        )
        for event, stock in rows
    ]


@router.get("/history/{ticker}", response_model=list[EarningsEventResponse])
async def get_earnings_history(
    ticker: str,
    limit: int = Query(12, le=40),
    db: AsyncSession = Depends(get_db),
):
    """Get earnings history for a stock."""
    query = (
        select(EarningsEvent, Stock)
        .join(Stock, EarningsEvent.stock_id == Stock.id)
        .where(Stock.ticker == ticker.upper())
        .order_by(EarningsEvent.report_date.desc())
        .limit(limit)
    )
    result = await db.execute(query)
    rows = result.all()

    return [
        EarningsEventResponse(
            id=event.id,
            ticker=stock.ticker,
            company_name=stock.company_name,
            report_date=event.report_date,
            fiscal_quarter=event.fiscal_quarter,
            report_time=event.report_time,
            eps_estimate=event.eps_estimate,
            revenue_estimate=event.revenue_estimate,
            eps_actual=event.eps_actual,
            revenue_actual=event.revenue_actual,
            eps_surprise_pct=event.eps_surprise_pct,
            price_change_pct=event.price_change_pct,
            is_confirmed=event.is_confirmed,
        )
        for event, stock in rows
    ]
