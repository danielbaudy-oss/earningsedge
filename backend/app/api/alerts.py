"""Alert management endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import get_db
from app.db.models import Alert, Stock
from pydantic import BaseModel, EmailStr
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

    class Config:
        from_attributes = True


@router.post("/", response_model=AlertResponse)
async def create_alert(alert: AlertCreate, db: AsyncSession = Depends(get_db)):
    """Create an earnings alert for a stock."""
    stock_query = select(Stock).where(Stock.ticker == alert.ticker.upper())
    result = await db.execute(stock_query)
    stock = result.scalar_one_or_none()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    new_alert = Alert(
        stock_id=stock.id,
        user_email=alert.email,
        days_before=alert.days_before,
    )
    db.add(new_alert)
    await db.flush()

    return AlertResponse(
        id=new_alert.id,
        ticker=stock.ticker,
        company_name=stock.company_name,
        email=alert.email,
        days_before=alert.days_before,
        is_active=True,
    )


@router.get("/user/{email}", response_model=list[AlertResponse])
async def get_user_alerts(email: str, db: AsyncSession = Depends(get_db)):
    """Get all alerts for a user."""
    query = (
        select(Alert, Stock)
        .join(Stock, Alert.stock_id == Stock.id)
        .where(Alert.user_email == email, Alert.is_active == True)
    )
    result = await db.execute(query)
    rows = result.all()

    return [
        AlertResponse(
            id=alert.id,
            ticker=stock.ticker,
            company_name=stock.company_name,
            email=alert.user_email,
            days_before=alert.days_before,
            is_active=alert.is_active,
        )
        for alert, stock in rows
    ]
