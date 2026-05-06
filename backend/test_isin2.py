import httpx, time
time.sleep(13)
from app.core.config import get_settings
s = get_settings()
r = httpx.get(f"https://api.polygon.io/v3/reference/tickers/NVDA", params={"apiKey": s.polygon_api_key}, timeout=10)
if r.status_code == 200:
    data = r.json().get("results", {})
    print(f"Name: {data.get('name')}")
    print(f"CIK: {data.get('cik')}")
    print(f"Exchange: {data.get('primary_exchange')}")
    print(f"Composite FIGI: {data.get('composite_figi')}")
    print(f"Share Class FIGI: {data.get('share_class_figi')}")
    # Print all keys
    print(f"\nAll keys: {list(data.keys())}")
