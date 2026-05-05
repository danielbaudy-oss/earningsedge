import asyncio, httpx
from app.ml.predict_with_model import predict_stock, load_models
from app.db.supabase_client import get_supabase
from datetime import date

async def test():
    sb = get_supabase()
    stock = sb.table("stocks").select("id").eq("ticker", "AMD").execute()
    stock_id = stock.data[0]["id"]
    print(f"AMD stock_id: {stock_id}")

    event = sb.table("earnings_events").select("id, report_date").eq("stock_id", stock_id).gte("report_date", date.today().isoformat()).order("report_date").limit(1).execute()
    print(f"Event: {event.data}")

    if event.data:
        client = httpx.AsyncClient(timeout=30.0)
        pred = await predict_stock(client, "AMD", stock_id, event.data[0]["id"], "trader")
        if pred:
            print(f"OK: {pred['recommendation']} Score:{pred['feature_importance']['total_score']}%")
        else:
            print("predict_stock returned None - insufficient data")
        await client.aclose()

asyncio.run(test())
