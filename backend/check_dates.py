import httpx
from app.core.config import get_settings
s = get_settings()

# Check Polygon financials for filing dates
r = httpx.get(
    "https://api.polygon.io/vX/reference/financials",
    params={"ticker": "NVDA", "limit": 4, "timeframe": "quarterly", "apiKey": s.polygon_api_key},
    timeout=10,
)
if r.status_code == 200:
    for f in r.json().get("results", []):
        print(f"Filing: {f.get('filing_date')}  Period: {f.get('fiscal_period')} {f.get('fiscal_year')}  Start: {f.get('start_date')}  End: {f.get('end_date')}")
else:
    print(f"Polygon status: {r.status_code}")
