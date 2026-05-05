"""Seed script: populate stocks and earnings data from Finnhub + Polygon."""

import asyncio
import httpx
from datetime import date, timedelta
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

settings = get_settings()

# Top stocks to seed (S&P 500 mega caps + popular retail investor picks)
SEED_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B",
    "JPM", "V", "UNH", "MA", "HD", "PG", "JNJ", "COST", "ABBV", "CRM",
    "NFLX", "AMD", "INTC", "DIS", "PYPL", "BA", "NKE", "SBUX", "SQ",
    "SHOP", "ROKU", "SNAP", "PLTR", "SOFI", "RIVN", "COIN", "HOOD",
    "WMT", "TGT", "KO", "PEP", "MCD", "ADBE", "ORCL", "CSCO", "QCOM",
    "AVGO", "TXN", "NOW", "UBER", "ABNB", "SNOW",
]


async def seed_stocks():
    """Seed stock master data from Polygon."""
    print("📊 Seeding stocks...")
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)
    seeded = 0

    for ticker in SEED_TICKERS:
        try:
            # Get ticker details from Polygon
            url = f"https://api.polygon.io/v3/reference/tickers/{ticker}"
            resp = await client.get(url, params={"apiKey": settings.polygon_api_key})

            if resp.status_code != 200:
                print(f"  ⚠️  {ticker}: Polygon returned {resp.status_code}")
                continue

            data = resp.json().get("results", {})
            if not data:
                continue

            stock_data = {
                "ticker": ticker,
                "company_name": data.get("name", ticker),
                "sector": data.get("sic_description", ""),
                "industry": data.get("sic_description", ""),
                "market_cap": data.get("market_cap"),
                "exchange": data.get("primary_exchange", ""),
                "is_active": data.get("active", True),
            }

            # Upsert into Supabase
            sb.table("stocks").upsert(stock_data, on_conflict="ticker")
            seeded += 1
            print(f"  ✅ {ticker}: {stock_data['company_name']}")

        except Exception as e:
            print(f"  ❌ {ticker}: {e}")

        # Rate limit: Polygon free tier = 5 calls/min
        await asyncio.sleep(13)

    await client.aclose()
    print(f"\n✅ Seeded {seeded} stocks")
    return seeded


async def seed_earnings_calendar():
    """Seed upcoming earnings from Finnhub."""
    print("\n📅 Seeding earnings calendar...")
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)

    today = date.today()
    end_date = today + timedelta(days=60)

    url = "https://finnhub.io/api/v1/calendar/earnings"
    params = {
        "from": today.isoformat(),
        "to": end_date.isoformat(),
        "token": settings.finnhub_api_key,
    }

    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        calendar = resp.json().get("earningsCalendar", [])
        print(f"  Found {len(calendar)} earnings events from Finnhub")
    except Exception as e:
        print(f"  ❌ Failed to fetch calendar: {e}")
        await client.aclose()
        return 0

    # Get our stock IDs
    stocks_result = sb.table("stocks").select("id, ticker").execute()
    stock_map = {s["ticker"]: s["id"] for s in stocks_result.data}

    seeded = 0
    for event in calendar:
        ticker = event.get("symbol", "")
        if ticker not in stock_map:
            continue

        earnings_data = {
            "stock_id": stock_map[ticker],
            "report_date": event.get("date"),
            "fiscal_quarter": f"Q{event.get('quarter', '?')} {event.get('year', '')}",
            "fiscal_year": event.get("year"),
            "report_time": "before_market" if event.get("hour") == "bmo" else "after_market",
            "eps_estimate": event.get("epsEstimate"),
            "revenue_estimate": event.get("revenueEstimate"),
            "eps_actual": event.get("epsActual"),
            "revenue_actual": event.get("revenueActual"),
            "is_confirmed": True,
        }

        # Calculate surprise if actuals exist
        if earnings_data["eps_actual"] and earnings_data["eps_estimate"]:
            surprise = earnings_data["eps_actual"] - earnings_data["eps_estimate"]
            if earnings_data["eps_estimate"] != 0:
                earnings_data["eps_surprise"] = surprise
                earnings_data["eps_surprise_pct"] = (surprise / abs(earnings_data["eps_estimate"])) * 100

        try:
            sb.table("earnings_events").insert(earnings_data)
            seeded += 1
        except Exception as e:
            # Skip duplicates
            if "duplicate" not in str(e).lower():
                print(f"  ⚠️  {ticker}: {e}")

    await client.aclose()
    print(f"✅ Seeded {seeded} earnings events")
    return seeded


async def seed_earnings_history():
    """Seed historical earnings surprises from Finnhub."""
    print("\n📈 Seeding earnings history...")
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)

    stocks_result = sb.table("stocks").select("id, ticker").execute()
    seeded = 0

    for stock in stocks_result.data:
        ticker = stock["ticker"]
        try:
            url = "https://finnhub.io/api/v1/stock/earnings"
            params = {"symbol": ticker, "limit": 8, "token": settings.finnhub_api_key}
            resp = await client.get(url, params=params)

            if resp.status_code != 200:
                continue

            earnings = resp.json()
            if not isinstance(earnings, list):
                continue

            for e in earnings:
                if not e.get("period"):
                    continue

                earnings_data = {
                    "stock_id": stock["id"],
                    "report_date": e.get("period"),
                    "fiscal_quarter": f"Q{e.get('quarter', '?')} {e.get('year', '')}",
                    "fiscal_year": e.get("year"),
                    "eps_estimate": e.get("estimate"),
                    "eps_actual": e.get("actual"),
                    "is_confirmed": True,
                }

                if e.get("actual") is not None and e.get("estimate") is not None:
                    surprise = e["actual"] - e["estimate"]
                    earnings_data["eps_surprise"] = surprise
                    if e["estimate"] != 0:
                        earnings_data["eps_surprise_pct"] = (surprise / abs(e["estimate"])) * 100

                try:
                    sb.table("earnings_events").insert(earnings_data)
                    seeded += 1
                except Exception:
                    pass  # Skip duplicates

            print(f"  ✅ {ticker}: {len(earnings)} quarters")

        except Exception as e:
            print(f"  ⚠️  {ticker}: {e}")

        # Finnhub rate limit: 60 calls/min
        await asyncio.sleep(1.1)

    await client.aclose()
    print(f"✅ Seeded {seeded} historical earnings")
    return seeded


async def main():
    """Run full seed pipeline."""
    print("🚀 EarningsEdge Data Seed\n" + "=" * 40)

    await seed_stocks()
    await seed_earnings_calendar()
    await seed_earnings_history()

    print("\n" + "=" * 40)
    print("🎉 Seed complete! Check your Supabase dashboard.")


if __name__ == "__main__":
    asyncio.run(main())
