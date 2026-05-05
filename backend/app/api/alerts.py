"""Alert management endpoints using Supabase client."""

from fastapi import APIRouter, HTTPException
from app.db.supabase_client import get_supabase
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class AlertCreate(BaseModel):
    ticker: str
    email: str
    days_before: int = 3


class AlertResponse(BaseModel):
    id: int
    ticker: str
    company_name: str
    email: str
    days_before: int
    is_active: bool


@router.post("/", response_model=AlertResponse)
async def create_alert(alert: AlertCreate):
    """Create an earnings alert for a stock."""
    sb = get_supabase()

    # Find stock
    stock_result = sb.table("stocks").select("id,ticker,company_name").eq("ticker", alert.ticker.upper()).execute()
    if not stock_result.data:
        raise HTTPException(status_code=404, detail="Stock not found")

    stock = stock_result.data[0]

    # Create alert
    new_alert = (
        sb.table("alerts")
        .insert({
            "stock_id": stock["id"],
            "user_email": alert.email,
            "days_before": alert.days_before,
            "is_active": True,
        })
        .execute()
    )

    return AlertResponse(
        id=new_alert.data[0]["id"],
        ticker=stock["ticker"],
        company_name=stock["company_name"],
        email=alert.email,
        days_before=alert.days_before,
        is_active=True,
    )


@router.get("/user/{email}", response_model=list[AlertResponse])
async def get_user_alerts(email: str):
    """Get all alerts for a user."""
    sb = get_supabase()

    result = (
        sb.table("alerts")
        .select("*, stocks(ticker, company_name)")
        .eq("user_email", email)
        .eq("is_active", True)
        .execute()
    )

    return [
        AlertResponse(
            id=row["id"],
            ticker=(row.get("stocks") or {}).get("ticker", ""),
            company_name=(row.get("stocks") or {}).get("company_name", ""),
            email=row["user_email"],
            days_before=row["days_before"],
            is_active=row["is_active"],
        )
        for row in result.data
    ]
