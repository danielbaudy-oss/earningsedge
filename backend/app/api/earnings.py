"""Earnings calendar and event endpoints using Supabase client."""

from fastapi import APIRouter, Query, HTTPException
from app.db.supabase_client import get_supabase
from pydantic import BaseModel
from typing import Optional
from datetime import date

router = APIRouter()


class EarningsEventResponse(BaseModel):
    id: int
    ticker: Optional[str] = None
    company_name: Optional[str] = None
    report_date: str
    fiscal_quarter: Optional[str] = None
    report_time: Optional[str] = None
    eps_estimate: Optional[float] = None
    revenue_estimate: Optional[float] = None
    eps_actual: Optional[float] = None
    revenue_actual: Optional[float] = None
    eps_surprise_pct: Optional[float] = None
    price_change_pct: Optional[float] = None
    is_confirmed: bool = False


@router.get("/calendar", response_model=list[EarningsEventResponse])
async def get_earnings_calendar(
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    sector: Optional[str] = Query(None),
):
    """Get earnings calendar for a date range."""
    sb = get_supabase()
    query = (
        sb.table("earnings_events")
        .select("*, stocks(ticker, company_name, sector)")
        .gte("report_date", start_date.isoformat())
        .lte("report_date", end_date.isoformat())
        .order("report_date")
    )
    result = query.execute()

    events = []
    for row in result.data:
        stock = row.get("stocks", {}) or {}
        if sector and stock.get("sector") != sector:
            continue
        events.append(EarningsEventResponse(
            id=row["id"],
            ticker=stock.get("ticker"),
            company_name=stock.get("company_name"),
            report_date=row["report_date"],
            fiscal_quarter=row.get("fiscal_quarter"),
            report_time=row.get("report_time"),
            eps_estimate=row.get("eps_estimate"),
            revenue_estimate=row.get("revenue_estimate"),
            eps_actual=row.get("eps_actual"),
            revenue_actual=row.get("revenue_actual"),
            eps_surprise_pct=row.get("eps_surprise_pct"),
            price_change_pct=row.get("price_change_pct"),
            is_confirmed=row.get("is_confirmed", False),
        ))
    return events


@router.get("/upcoming", response_model=list[EarningsEventResponse])
async def get_upcoming_earnings(limit: int = Query(20, le=100)):
    """Get upcoming earnings events."""
    sb = get_supabase()
    today = date.today().isoformat()
    result = (
        sb.table("earnings_events")
        .select("*, stocks(ticker, company_name)")
        .gte("report_date", today)
        .order("report_date")
        .limit(limit)
        .execute()
    )

    return [
        EarningsEventResponse(
            id=row["id"],
            ticker=(row.get("stocks") or {}).get("ticker"),
            company_name=(row.get("stocks") or {}).get("company_name"),
            report_date=row["report_date"],
            fiscal_quarter=row.get("fiscal_quarter"),
            report_time=row.get("report_time"),
            eps_estimate=row.get("eps_estimate"),
            revenue_estimate=row.get("revenue_estimate"),
            is_confirmed=row.get("is_confirmed", False),
        )
        for row in result.data
    ]


@router.get("/history/{ticker}", response_model=list[EarningsEventResponse])
async def get_earnings_history(ticker: str, limit: int = Query(12, le=40)):
    """Get earnings history for a stock."""
    sb = get_supabase()

    # Get stock id first
    stock_result = sb.table("stocks").select("id").eq("ticker", ticker.upper()).execute()
    if not stock_result.data:
        raise HTTPException(status_code=404, detail="Stock not found")

    stock_id = stock_result.data[0]["id"]
    result = (
        sb.table("earnings_events")
        .select("*, stocks(ticker, company_name)")
        .eq("stock_id", stock_id)
        .order("report_date", desc=True)
        .limit(limit)
        .execute()
    )

    return [
        EarningsEventResponse(
            id=row["id"],
            ticker=ticker.upper(),
            company_name=(row.get("stocks") or {}).get("company_name"),
            report_date=row["report_date"],
            fiscal_quarter=row.get("fiscal_quarter"),
            report_time=row.get("report_time"),
            eps_estimate=row.get("eps_estimate"),
            revenue_estimate=row.get("revenue_estimate"),
            eps_actual=row.get("eps_actual"),
            revenue_actual=row.get("revenue_actual"),
            eps_surprise_pct=row.get("eps_surprise_pct"),
            price_change_pct=row.get("price_change_pct"),
            is_confirmed=row.get("is_confirmed", False),
        )
        for row in result.data
    ]
