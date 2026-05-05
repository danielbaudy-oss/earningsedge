"""SEC Edgar API client for company filings."""

import httpx
from app.core.config import get_settings

settings = get_settings()
BASE_URL = "https://data.sec.gov"
SUBMISSIONS_URL = "https://data.sec.gov/submissions"


class SECEdgarClient:
    """Client for SEC EDGAR API."""

    def __init__(self):
        self.headers = {
            "User-Agent": settings.sec_edgar_user_agent,
            "Accept-Encoding": "gzip, deflate",
        }
        self.client = httpx.AsyncClient(timeout=30.0, headers=self.headers)

    async def get_company_filings(self, cik: str) -> dict:
        """Get recent filings for a company by CIK."""
        cik_padded = cik.zfill(10)
        url = f"{SUBMISSIONS_URL}/CIK{cik_padded}.json"
        resp = await self.client.get(url)
        resp.raise_for_status()
        return resp.json()

    async def get_company_facts(self, cik: str) -> dict:
        """Get XBRL company facts (financial data)."""
        cik_padded = cik.zfill(10)
        url = f"{BASE_URL}/api/xbrl/companyfacts/CIK{cik_padded}.json"
        resp = await self.client.get(url)
        resp.raise_for_status()
        return resp.json()

    async def search_company(self, query: str) -> list:
        """Search for companies by name or ticker."""
        url = "https://efts.sec.gov/LATEST/search-index"
        params = {"q": query, "dateRange": "custom", "forms": "10-K,10-Q"}
        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json().get("hits", {}).get("hits", [])

    async def close(self):
        await self.client.aclose()
