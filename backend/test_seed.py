"""Quick test: seed one stock to verify Polygon + Supabase work."""
import asyncio
import httpx
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

settings = get_settings()
sb = get_supabase()


async def test():
    client = httpx.AsyncClient(timeout=30.0)
    url = "https://api.polygon.io/v3/reference/tickers/AAPL"
    resp = await client.get(url, params={"apiKey": settings.polygon_api_key})
    print(f"Polygon status: {resp.status_code}")

    data = resp.json().get("results", {})
    print(f"Company: {data.get('name')}")

    stock_data = {
        "ticker": "AAPL",
        "company_name": data.get("name", "Apple Inc"),
        "sector": data.get("sic_description", ""),
        "market_cap": data.get("market_cap"),
        "exchange": data.get("primary_exchange", ""),
        "is_active": True,
    }
    result = sb.table("stocks").upsert(stock_data, on_conflict="ticker")
    print(f"Supabase upsert: {result.data}")
    await client.aclose()


asyncio.run(test())
