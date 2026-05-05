"""Stock search and detail endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from app.db.database import get_db
from app.db.models import Stock, FinancialMetric
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()


class StockResponse(BaseModel):
    id: int
    ticker: str
    company_name: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    exchange: Optional[str] = None

    class Config:
        from_attributes = True


class StockDetailResponse(StockResponse):
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    eps_growth_yoy: Optional[float] = None
    gross_margin: Optional[float] = None
    debt_to_equity: Optional[float] = None


@router.get("/search", response_model=list[StockResponse])
async def search_stocks(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Search stocks by ticker or company name."""
    query = select(Stock).where(
        or_(
            Stock.ticker.ilike(f"%{q}%"),
            Stock.company_name.ilike(f"%{q}%"),
        ),
        Stock.is_active == True,
    ).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{ticker}", response_model=StockDetailResponse)
async def get_stock(ticker: str, db: AsyncSession = Depends(get_db)):
    """Get stock details with latest financial metrics."""
    query = select(Stock).where(Stock.ticker == ticker.upper())
    result = await db.execute(query)
    stock = result.scalar_one_or_none()
    if not stock:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Stock not found")

    # Get latest financial metrics
    metrics_query = (
        select(FinancialMetric)
        .where(FinancialMetric.stock_id == stock.id)
        .order_by(FinancialMetric.period_date.desc())
        .limit(1)
    )
    metrics_result = await db.execute(metrics_query)
    metrics = metrics_result.scalar_one_or_none()

    response = StockDetailResponse.model_validate(stock)
    if metrics:
        response.pe_ratio = metrics.pe_ratio
        response.forward_pe = metrics.forward_pe
        response.revenue_growth_yoy = metrics.revenue_growth_yoy
        response.eps_growth_yoy = metrics.eps_growth_yoy
        response.gross_margin = metrics.gross_margin
        response.debt_to_equity = metrics.debt_to_equity

    return response
