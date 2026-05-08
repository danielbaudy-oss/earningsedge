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


@router.get("/{ticker}/chart")
async def get_stock_chart(ticker: str):
    """Get YTD price history for a stock chart. Tries marketdata.app first, Polygon as fallback.
    Also returns past earnings report dates for chart annotations."""
    import httpx
    from datetime import date, timedelta
    from app.core.config import get_settings
    settings = get_settings()

    today = date.today()
    from_date = (today - timedelta(days=365)).isoformat()
    to_date = today.isoformat()

    # Get earnings dates for this stock (within chart range)
    sb = get_supabase()
    earnings_dates = []
    try:
        stock_result = sb.table("stocks").select("id").eq("ticker", ticker.upper()).execute()
        if stock_result.data:
            stock_id = stock_result.data[0]["id"]
            events = (
                sb.table("earnings_events")
                .select("report_date")
                .eq("stock_id", stock_id)
                .gte("report_date", from_date)
                .lte("report_date", to_date)
                .order("report_date")
                .execute()
            )
            if events.data:
                earnings_dates = [e["report_date"] for e in events.data]
    except Exception:
        pass

    # Try marketdata.app first (higher rate limit)
    if settings.marketdata_api_key:
        try:
            headers = {"Authorization": f"Token {settings.marketdata_api_key}"}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"https://api.marketdata.app/v1/stocks/candles/D/{ticker.upper()}/",
                    headers=headers,
                    params={"from": from_date, "to": to_date},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    closes = data.get("c", [])
                    timestamps = data.get("t", [])
                    if closes and timestamps:
                        prices = [
                            {"date": t * 1000, "price": round(c, 2)}
                            for t, c in zip(timestamps, closes)
                        ]
                        return {"prices": prices, "ticker": ticker.upper(), "earnings_dates": earnings_dates}
        except Exception:
            pass

    # Fallback to Polygon
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker.upper()}/range/1/day/{from_date}/{to_date}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params={
            "adjusted": "true",
            "sort": "asc",
            "apiKey": settings.polygon_api_key,
        })

    if resp.status_code != 200:
        return {"prices": [], "earnings_dates": earnings_dates}

    data = resp.json()
    results = data.get("results", [])
    if not results:
        return {"prices": [], "earnings_dates": earnings_dates}

    prices = [
        {"date": bar["t"], "price": round(bar["c"], 2)}
        for bar in results
    ]

    return {"prices": prices, "ticker": ticker.upper(), "earnings_dates": earnings_dates}
