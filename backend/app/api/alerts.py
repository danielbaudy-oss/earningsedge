"""Alert management endpoints — supports email and Telegram."""

from fastapi import APIRouter, HTTPException
from app.db.supabase_client import get_supabase
from app.services.telegram_service import TelegramService
from pydantic import BaseModel
from typing import Optional, Literal

router = APIRouter()


class AlertCreate(BaseModel):
    ticker: str
    alert_method: Literal["email", "telegram"] = "email"
    email: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    days_before: int = 3


class AlertResponse(BaseModel):
    id: int
    ticker: str
    company_name: str
    alert_method: str
    email: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    days_before: int
    is_active: bool


@router.post("/", response_model=AlertResponse)
async def create_alert(alert: AlertCreate):
    """Create an earnings alert (email or Telegram)."""
    sb = get_supabase()

    # Validate input
    if alert.alert_method == "email" and not alert.email:
        raise HTTPException(status_code=400, detail="Email required for email alerts")
    if alert.alert_method == "telegram" and not alert.telegram_chat_id:
        raise HTTPException(status_code=400, detail="Telegram chat ID required")

    # Find stock
    stock_result = sb.table("stocks").select("id,ticker,company_name").eq("ticker", alert.ticker.upper()).execute()
    if not stock_result.data:
        raise HTTPException(status_code=404, detail="Stock not found")

    stock = stock_result.data[0]

    # Verify Telegram chat if applicable
    if alert.alert_method == "telegram":
        tg = TelegramService()
        if tg.enabled:
            success = await tg.verify_chat(alert.telegram_chat_id)
            if not success:
                raise HTTPException(
                    status_code=400,
                    detail="Could not reach Telegram chat. Make sure you started the bot first."
                )

    # Create alert
    alert_data = {
        "stock_id": stock["id"],
        "alert_method": alert.alert_method,
        "user_email": alert.email or "",
        "telegram_chat_id": alert.telegram_chat_id,
        "days_before": alert.days_before,
        "is_active": True,
    }
    new_alert = sb.table("alerts").insert(alert_data)

    return AlertResponse(
        id=new_alert.data[0]["id"],
        ticker=stock["ticker"],
        company_name=stock["company_name"],
        alert_method=alert.alert_method,
        email=alert.email,
        telegram_chat_id=alert.telegram_chat_id,
        days_before=alert.days_before,
        is_active=True,
    )


@router.get("/user/{identifier}", response_model=list[AlertResponse])
async def get_user_alerts(identifier: str):
    """Get all alerts for a user (by email or telegram chat ID)."""
    sb = get_supabase()

    # Try email first, then telegram
    result = (
        sb.table("alerts")
        .select("*, stocks(ticker, company_name)")
        .eq("user_email", identifier)
        .eq("is_active", True)
        .execute()
    )

    if not result.data:
        result = (
            sb.table("alerts")
            .select("*, stocks(ticker, company_name)")
            .eq("telegram_chat_id", identifier)
            .eq("is_active", True)
            .execute()
        )

    return [
        AlertResponse(
            id=row["id"],
            ticker=(row.get("stocks") or {}).get("ticker", ""),
            company_name=(row.get("stocks") or {}).get("company_name", ""),
            alert_method=row.get("alert_method", "email"),
            email=row.get("user_email") or None,
            telegram_chat_id=row.get("telegram_chat_id"),
            days_before=row["days_before"],
            is_active=row["is_active"],
        )
        for row in result.data
    ]


@router.delete("/{alert_id}")
async def delete_alert(alert_id: int):
    """Deactivate an alert."""
    sb = get_supabase()
    # Use PostgREST PATCH via custom request
    import httpx
    from app.core.config import get_settings
    settings = get_settings()
    headers = {
        "apikey": settings.supabase_service_key,
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    url = f"{settings.supabase_url}/rest/v1/alerts?id=eq.{alert_id}"
    async with httpx.AsyncClient() as client:
        resp = await client.patch(url, json={"is_active": False}, headers=headers)
    return {"status": "deleted", "id": alert_id}
