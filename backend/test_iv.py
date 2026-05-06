import httpx
import json

# Test marketdata.app free options chain
r = httpx.get("https://api.marketdata.app/v1/options/chain/AAPL/", timeout=10)
data = r.json()
print(f"Status: {r.status_code}")
print(f"Keys: {list(data.keys())}")

if "iv" in data:
    ivs = data["iv"][:5]
    print(f"IV values: {ivs}")

if "strike" in data:
    print(f"Strikes: {data['strike'][:5]}")

if "mid" in data:
    print(f"Mid prices: {data['mid'][:5]}")

if "side" in data:
    print(f"Sides: {data['side'][:5]}")

# Now try NVDA
print("\n--- NVDA ---")
r2 = httpx.get("https://api.marketdata.app/v1/options/chain/NVDA/", timeout=10)
print(f"NVDA status: {r2.status_code}")
if r2.status_code == 200:
    d2 = r2.json()
    if "iv" in d2:
        print(f"NVDA IV available! First 3: {d2['iv'][:3]}")
    print(f"NVDA keys: {list(d2.keys())}")
else:
    print(r2.text[:200])
