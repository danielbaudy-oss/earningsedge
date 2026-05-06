"""
Fetch implied volatility and market-expected earnings move from marketdata.app.

The expected move is calculated from the ATM straddle:
Expected Move = (ATM Call Mid + ATM Put Mid) / Current Price * 100

This tells us what the options market is pricing in for the next expiration.
"""

import httpx
from datetime import date, timedelta
from app.core.config import get_settings

settings = get_settings()
BASE_URL = "https://api.marketdata.app/v1"


def get_expected_move(ticker: str, earnings_date: str = None) -> dict:
    """
    Get the market's implied expected move for a stock using options data.

    Returns:
        - expected_move_pct: market-implied % move (from straddle)
        - atm_iv: at-the-money implied volatility (annualized)
        - current_price: current stock price
    """
    try:
        headers = {"Authorization": f"Token {settings.marketdata_api_key}"}

        # Fetch options chain
        params = {}
        if earnings_date:
            # Get options expiring just after earnings
            params["expiration"] = earnings_date

        resp = httpx.get(
            f"{BASE_URL}/options/chain/{ticker}/",
            headers=headers,
            params=params,
            timeout=15.0,
        )

        if resp.status_code != 200:
            return {"available": False, "error": f"HTTP {resp.status_code}"}

        data = resp.json()
        if data.get("s") != "ok":
            return {"available": False, "error": "No data"}

        strikes = data.get("strike", [])
        ivs = data.get("iv", [])
        sides = data.get("side", [])
        mids = data.get("mid", [])
        prices = data.get("underlyingPrice", [])

        if not strikes or not prices:
            return {"available": False}

        current_price = prices[0]

        # Find ATM call and put
        atm_call_mid = None
        atm_call_iv = None
        atm_put_mid = None
        atm_put_iv = None
        min_call_dist = float("inf")
        min_put_dist = float("inf")

        for i in range(len(strikes)):
            dist = abs(strikes[i] - current_price)
            side = sides[i] if i < len(sides) else ""
            mid = mids[i] if i < len(mids) else 0
            iv = ivs[i] if i < len(ivs) else 0

            if side == "call" and dist < min_call_dist and mid > 0:
                min_call_dist = dist
                atm_call_mid = mid
                atm_call_iv = iv
            elif side == "put" and dist < min_put_dist and mid > 0:
                min_put_dist = dist
                atm_put_mid = mid
                atm_put_iv = iv

        # Calculate expected move from straddle
        if atm_call_mid and atm_put_mid and current_price > 0:
            straddle = atm_call_mid + atm_put_mid
            expected_move_pct = (straddle / current_price) * 100

            # ATM IV (average of call and put)
            atm_iv = 0
            if atm_call_iv and atm_put_iv:
                atm_iv = (atm_call_iv + atm_put_iv) / 2
            elif atm_call_iv:
                atm_iv = atm_call_iv
            elif atm_put_iv:
                atm_iv = atm_put_iv

            return {
                "available": True,
                "expected_move_pct": round(expected_move_pct, 2),
                "atm_iv": round(atm_iv * 100, 1),  # As percentage
                "current_price": round(current_price, 2),
                "straddle_price": round(straddle, 2),
            }

        return {"available": False, "error": "Could not find ATM options"}

    except Exception as e:
        return {"available": False, "error": str(e)}
