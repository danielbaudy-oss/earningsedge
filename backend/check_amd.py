import httpx
from app.core.config import get_settings
s = get_settings()
r = httpx.get("https://api.polygon.io/vX/reference/financials", params={"ticker": "AMD", "limit": 6, "timeframe": "quarterly", "apiKey": s.polygon_api_key}, timeout=10)
for f in r.json().get("results", []):
    print(f"Filing: {f.get('filing_date')}  Period end: {f.get('end_date')}  FQ: {f.get('fiscal_period')} {f.get('fiscal_year')}")
