import httpx
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

s = get_settings()
sb = get_supabase()

r = httpx.get("https://finnhub.io/api/v1/stock/earnings", params={"symbol": "GFS", "limit": 8, "token": s.finnhub_api_key}, timeout=10)
earnings = r.json()
print(f"Finnhub returned {len(earnings)} quarters for GFS")

stock = sb.table("stocks").select("id").eq("ticker", "GFS").execute()
stock_id = stock.data[0]["id"]

stored = 0
for e in earnings:
    if not e.get("period"):
        continue
    data = {
        "stock_id": stock_id,
        "report_date": e["period"],
        "eps_estimate": e.get("estimate"),
        "eps_actual": e.get("actual"),
        "is_confirmed": True,
    }
    if e.get("actual") and e.get("estimate") and e["estimate"] != 0:
        data["eps_surprise_pct"] = ((e["actual"] - e["estimate"]) / abs(e["estimate"])) * 100
    try:
        sb.table("earnings_events").upsert(data, on_conflict="stock_id,report_date")
        stored += 1
        print(f"  {e['period']}: actual={e.get('actual')}, est={e.get('estimate')}")
    except Exception as ex:
        print(f"  Error: {ex}")

print(f"Stored {stored} events")
