"""Polygon.io API client for stock data and financials."""

import httpx
from datetime import date, timedelta
from app.core.config import get_settings

settings = get_settings()
BASE_URL = "https://api.polygon.io"


class PolygonClient:
    """Client for Polygon.io REST API."""

    def __init__(self):
        self.api_key = settings.polygon_api_key
        self.client = httpx.AsyncClient(timeout=30.0)

    async def get_ticker_details(self, ticker: str) -> dict:
        """Get company details for a ticker."""
        url = f"{BASE_URL}/v3/reference/tickers/{ticker}"
        resp = await self.client.get(url, params={"apiKey": self.api_key})
        resp.raise_for_status()
        return resp.json().get("results", {})

    async def get_stock_financials(self, ticker: str, limit: int = 8) -> list:
        """Get quarterly financial data."""
        url = f"{BASE_URL}/vX/reference/financials"
        params = {
            "ticker": ticker,
            "timeframe": "quarterly",
            "limit": limit,
            "apiKey": self.api_key,
        }
        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json().get("results", [])

    async def get_stock_price(self, ticker: str, date_str: str) -> dict:
        """Get stock price for a specific date."""
        url = f"{BASE_URL}/v1/open-close/{ticker}/{date_str}"
        resp = await self.client.get(url, params={"apiKey": self.api_key})
        resp.raise_for_status()
        return resp.json()

    async def get_aggregates(
        self, ticker: str, from_date: str, to_date: str
    ) -> list:
        """Get daily OHLCV bars."""
        url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day/{from_date}/{to_date}"
        params = {"adjusted": "true", "sort": "asc", "apiKey": self.api_key}
        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json().get("results", [])

    async def close(self):
        await self.client.aclose()
