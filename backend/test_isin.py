import httpx

# OpenFIGI - free, maps ticker to ISIN/FIGI
r = httpx.post(
    "https://api.openfigi.com/v3/mapping",
    json=[{"idType": "TICKER", "idValue": "NVDA", "exchCode": "US"}],
    headers={"Content-Type": "application/json"},
    timeout=10,
)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    if data and data[0].get("data"):
        for item in data[0]["data"][:5]:
            print(f"  Name: {item.get('name')}")
            print(f"  FIGI: {item.get('figi')}")
            print(f"  Exchange: {item.get('exchCode')}")
            print(f"  Market: {item.get('marketSector')}")
            print(f"  Security Type: {item.get('securityType')}")
            print(f"  ---")
