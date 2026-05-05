"""Stock search and detail endpoints using Supabase client."""

from fastapi import APIRouter, Query, HTTPException
from app.db.supabase_client import get_supabase
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class StockResponse(BaseModel):
    id: int
    ticker: str
    company_name: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    exchange: Optional[str] = None


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
):
    """Search stocks by ticker or company name."""
    sb = get_supabase()
    result = (
        sb.table("stocks")
        .select("*")
        .or_(f"ticker.ilike.%{q}%,company_name.ilike.%{q}%")
        .eq("is_active", True)
        .limit(limit)
        .execute()
    )
    return result.data


@router.get("/{ticker}", response_model=StockDetailResponse)
async def get_stock(ticker: str):
    """Get stock details with latest financial metrics."""
    sb = get_supabase()

    # Get stock
    stock_result = sb.table("stocks").select("*").eq("ticker", ticker.upper()).execute()
    if not stock_result.data:
        raise HTTPException(status_code=404, detail="Stock not found")

    stock = stock_result.data[0]

    # Get latest financial metrics
    metrics_result = (
        sb.table("financial_metrics")
        .select("pe_ratio,forward_pe,revenue_growth_yoy,eps_growth_yoy,gross_margin,debt_to_equity")
        .eq("stock_id", stock["id"])
        .order("period_date", desc=True)
        .limit(1)
        .execute()
    )

    response = {**stock}
    if metrics_result.data:
        response.update(metrics_result.data[0])

    return response
