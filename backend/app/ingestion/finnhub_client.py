"""Finnhub API client for earnings calendar and estimates."""

import httpx
from datetime import date, timedelta
from app.core.config import get_settings

settings = get_settings()
BASE_URL = "https://finnhub.io/api/v1"


class FinnhubClient:
    """Client for Finnhub REST API."""

    def __init__(self):
        self.api_key = settings.finnhub_api_key
        self.client = httpx.AsyncClient(timeout=30.0)

    def _params(self, **kwargs) -> dict:
        return {"token": self.api_key, **kwargs}

    async def get_earnings_calendar(
        self, from_date: date, to_date: date
    ) -> list:
        """Get earnings calendar for date range."""
        url = f"{BASE_URL}/calendar/earnings"
        params = self._params(
            **{"from": from_date.isoformat(), "to": to_date.isoformat()}
        )
        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json().get("earningsCalendar", [])

    async def get_earnings_surprises(self, ticker: str, limit: int = 12) -> list:
        """Get historical earnings surprises."""
        url = f"{BASE_URL}/stock/earnings"
        params = self._params(symbol=ticker, limit=limit)
        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_recommendation_trends(self, ticker: str) -> list:
        """Get analyst recommendation trends."""
        url = f"{BASE_URL}/stock/recommendation"
        params = self._params(symbol=ticker)
        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_price_target(self, ticker: str) -> dict:
        """Get analyst price target consensus."""
        url = f"{BASE_URL}/stock/price-target"
        params = self._params(symbol=ticker)
        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_eps_estimates(self, ticker: str) -> list:
        """Get EPS estimates."""
        url = f"{BASE_URL}/stock/eps-estimate"
        params = self._params(symbol=ticker, freq="quarterly")
        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json().get("data", [])

    async def close(self):
        await self.client.aclose()
