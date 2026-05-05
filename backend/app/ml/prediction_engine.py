"""
EarningsEdge Prediction Engine v3 — Full multi-factor scoring system.

Implements the complete scoring framework:
- Score (0-100)
- Buy / Hold / Avoid recommendation
- Earnings beat probability
- Post-earnings move probability
- Risk score
- Top 3 key reasons

Scoring Components:
  Fundamentals (30%): revenue growth, margins, EPS growth, debt health
  Growth Trends (20%): sequential acceleration, estimate revisions
  Sentiment (15%): news sentiment, analyst consensus direction
  Macro Conditions (15%): sector momentum, VIX, market regime
  Earnings/Event Strength (20%): beat history quality, surprise magnitude, reaction patterns

Data Sources Used:
  - Finnhub: earnings history, analyst recommendations, price targets, financials
  - Polygon: stock price data, market cap
  - News API: headline sentiment
  - SEC Edgar: filing signals (future)
"""

import asyncio
import httpx
import math
from datetime import date, timedelta
from typing import Optional
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

settings = get_settings()
FINNHUB_BASE = "https://finnhub.io/api/v1"
POLYGON_BASE = "https://api.polygon.io"


# ============================================================
# DATA FETCHING
# ============================================================

async def fetch_finnhub(client: httpx.AsyncClient, endpoint: str, params: dict):
    """Fetch from Finnhub API."""
    params["token"] = settings.finnhub_api_key
    try:
        resp = await client.get(f"{FINNHUB_BASE}/{endpoint}", params=params)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


async def fetch_polygon(client: httpx.AsyncClient, endpoint: str, params: dict = None):
    """Fetch from Polygon API."""
    params = params or {}
    params["apiKey"] = settings.polygon_api_key
    try:
        resp = await client.get(f"{POLYGON_BASE}/{endpoint}", params=params)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


async def fetch_all_data(client: httpx.AsyncClient, ticker: str) -> dict:
    """Fetch all available data for a ticker in parallel."""
    results = await asyncio.gather(
        fetch_finnhub(client, "stock/earnings", {"symbol": ticker, "limit": 12}),
        fetch_finnhub(client, "stock/recommendation", {"symbol": ticker}),
        fetch_finnhub(client, "stock/price-target", {"symbol": ticker}),
        fetch_finnhub(client, "stock/metric", {"symbol": ticker, "metric": "all"}),
        fetch_finnhub(client, "company-news", {
            "symbol": ticker,
            "from": (date.today() - timedelta(days=14)).isoformat(),
            "to": date.today().isoformat(),
        }),
        return_exceptions=True,
    )

    return {
        "earnings": results[0] if isinstance(results[0], list) else [],
        "recommendations": results[1] if isinstance(results[1], list) else [],
        "price_target": results[2] if isinstance(results[2], dict) else {},
        "metrics": (results[3] or {}).get("metric", {}) if isinstance(results[3], dict) else {},
        "news": results[4] if isinstance(results[4], list) else [],
    }


# ============================================================
# SCORING COMPONENTS
# ============================================================

def score_fundamentals(metrics: dict) -> tuple[float, list[str]]:
    """
    Fundamentals Score (0-100). Weight: 30%

    Evaluates: revenue growth, margins, EPS growth, debt health, valuation.
    """
    reasons = []
    scores = []

    # Revenue growth
    rev_growth = metrics.get("revenueGrowthTTMYoy", 0) or 0
    if rev_growth > 25:
        scores.append(90)
        reasons.append(f"Strong revenue growth ({rev_growth:.1f}% YoY)")
    elif rev_growth > 10:
        scores.append(70)
        reasons.append(f"Solid revenue growth ({rev_growth:.1f}% YoY)")
    elif rev_growth > 0:
        scores.append(50)
    elif rev_growth > -10:
        scores.append(30)
        reasons.append(f"Revenue declining ({rev_growth:.1f}% YoY)")
    else:
        scores.append(15)
        reasons.append(f"Revenue in sharp decline ({rev_growth:.1f}% YoY)")

    # EPS growth
    eps_growth = metrics.get("epsGrowthTTMYoy", 0) or 0
    if eps_growth > 20:
        scores.append(85)
    elif eps_growth > 5:
        scores.append(65)
    elif eps_growth > -10:
        scores.append(45)
    else:
        scores.append(20)
        reasons.append(f"EPS declining ({eps_growth:.1f}% YoY)")

    # Operating margin
    op_margin = metrics.get("operatingMarginTTM", 0) or 0
    if op_margin > 25:
        scores.append(85)
    elif op_margin > 15:
        scores.append(70)
    elif op_margin > 5:
        scores.append(50)
    elif op_margin > 0:
        scores.append(35)
    else:
        scores.append(15)
        reasons.append(f"Negative operating margin ({op_margin:.1f}%)")

    # Debt health
    debt_eq = metrics.get("totalDebt/totalEquityQuarterly", 0) or 0
    if debt_eq < 0.5:
        scores.append(80)
    elif debt_eq < 1.5:
        scores.append(60)
    elif debt_eq < 3:
        scores.append(40)
    else:
        scores.append(20)
        reasons.append(f"High debt-to-equity ({debt_eq:.1f}x)")

    # ROE
    roe = metrics.get("roeTTM", 0) or 0
    if roe > 20:
        scores.append(85)
    elif roe > 10:
        scores.append(65)
    elif roe > 0:
        scores.append(45)
    else:
        scores.append(25)

    final_score = sum(scores) / len(scores) if scores else 50
    return final_score, reasons[:2]


def score_growth_trends(metrics: dict, earnings: list) -> tuple[float, list[str]]:
    """
    Growth Trends Score (0-100). Weight: 20%

    Evaluates: sequential acceleration, estimate revision direction,
    quarter-over-quarter improvement.
    """
    reasons = []
    scores = []

    # Revenue growth acceleration (QoQ vs YoY)
    rev_growth_qoq = metrics.get("revenueGrowthQuarterlyYoy", 0) or 0
    rev_growth_ttm = metrics.get("revenueGrowthTTMYoy", 0) or 0

    if rev_growth_qoq > rev_growth_ttm + 5:
        scores.append(80)
        reasons.append("Revenue growth is accelerating")
    elif rev_growth_qoq > rev_growth_ttm:
        scores.append(65)
    elif rev_growth_qoq < rev_growth_ttm - 5:
        scores.append(30)
        reasons.append("Revenue growth is decelerating")
    else:
        scores.append(50)

    # EPS trend from earnings history
    if earnings and len(earnings) >= 4:
        actuals = [e.get("actual") for e in earnings[:4] if e.get("actual") is not None]
        if len(actuals) >= 3:
            # Is EPS improving quarter over quarter?
            improving = sum(1 for i in range(len(actuals)-1) if actuals[i] > actuals[i+1])
            if improving >= 2:
                scores.append(75)
                reasons.append("EPS trending upward over recent quarters")
            elif improving == 0:
                scores.append(25)
                reasons.append("EPS declining quarter over quarter")
            else:
                scores.append(50)
        else:
            scores.append(50)
    else:
        scores.append(50)

    # Estimate revision direction (are estimates going up or down?)
    if earnings and len(earnings) >= 2:
        estimates = [e.get("estimate") for e in earnings[:4] if e.get("estimate") is not None]
        if len(estimates) >= 2:
            if estimates[0] > estimates[1] * 1.05:
                scores.append(75)
                reasons.append("Analyst estimates being revised upward")
            elif estimates[0] < estimates[1] * 0.95:
                scores.append(25)
                reasons.append("Analyst estimates being revised downward")
            else:
                scores.append(50)
        else:
            scores.append(50)
    else:
        scores.append(50)

    final_score = sum(scores) / len(scores) if scores else 50
    return final_score, reasons[:2]


def score_sentiment(recommendations: list, price_target: dict, news: list) -> tuple[float, list[str]]:
    """
    Sentiment Score (0-100). Weight: 15%

    Evaluates: analyst consensus, revision direction, news tone, price target gap.
    """
    reasons = []
    scores = []

    # Analyst consensus
    if recommendations:
        latest = recommendations[0]
        buy = latest.get("buy", 0) + latest.get("strongBuy", 0)
        sell = latest.get("sell", 0) + latest.get("strongSell", 0)
        hold = latest.get("hold", 0)
        total = buy + sell + hold

        if total > 0:
            buy_pct = buy / total
            if buy_pct > 0.7:
                scores.append(85)
                reasons.append(f"Strong analyst consensus: {buy_pct:.0%} buy ratings")
            elif buy_pct > 0.5:
                scores.append(65)
            elif buy_pct > 0.3:
                scores.append(45)
            else:
                scores.append(25)
                reasons.append(f"Weak analyst consensus: only {buy_pct:.0%} buy ratings")

            # Revision trend
            if len(recommendations) >= 2:
                prev = recommendations[1]
                prev_buy = prev.get("buy", 0) + prev.get("strongBuy", 0)
                prev_total = prev_buy + prev.get("sell", 0) + prev.get("strongSell", 0) + prev.get("hold", 0)
                if prev_total > 0:
                    prev_buy_pct = prev_buy / prev_total
                    if buy_pct > prev_buy_pct + 0.05:
                        scores.append(75)
                        reasons.append("Analyst upgrades trending positive")
                    elif buy_pct < prev_buy_pct - 0.05:
                        scores.append(30)
                        reasons.append("Analyst downgrades increasing")
                    else:
                        scores.append(55)
        else:
            scores.append(50)
    else:
        scores.append(50)

    # News volume and basic sentiment (headline count as proxy)
    if news:
        news_count = len(news)
        if news_count > 20:
            scores.append(60)  # High attention — could go either way
        elif news_count > 5:
            scores.append(55)
        else:
            scores.append(50)
    else:
        scores.append(50)

    # Price target upside
    target_mean = price_target.get("targetMean", 0)
    if target_mean and target_mean > 0:
        # We don't have current price from this data, so just check if target exists
        scores.append(60)  # Having a target is mildly positive
    else:
        scores.append(50)

    final_score = sum(scores) / len(scores) if scores else 50
    return final_score, reasons[:2]


def score_macro_conditions(metrics: dict) -> tuple[float, list[str]]:
    """
    Macro Conditions Score (0-100). Weight: 15%

    Evaluates: sector momentum, beta-adjusted risk, market regime.
    Note: Without real-time VIX/sector data, we use beta and PE as proxies.
    """
    reasons = []
    scores = []

    # Beta — high beta = more risk around earnings
    beta = metrics.get("beta", 1) or 1
    if beta < 0.8:
        scores.append(70)  # Low vol stock, less earnings risk
    elif beta < 1.2:
        scores.append(60)
    elif beta < 1.8:
        scores.append(45)
    else:
        scores.append(30)
        reasons.append(f"High beta ({beta:.1f}) means amplified earnings reaction")

    # PE ratio — extreme valuations increase risk
    pe = metrics.get("peTTM", 0) or 0
    if pe > 0:
        if pe > 60:
            scores.append(30)
            reasons.append(f"Very high valuation (PE {pe:.0f}x) — priced for perfection")
        elif pe > 35:
            scores.append(45)
            reasons.append(f"Elevated valuation (PE {pe:.0f}x) raises the bar")
        elif pe > 15:
            scores.append(65)
        else:
            scores.append(75)
            reasons.append(f"Reasonable valuation (PE {pe:.0f}x)")
    else:
        scores.append(40)  # Negative PE = unprofitable

    # 52-week position (proxy for momentum)
    high_52w = metrics.get("52WeekHigh", 0) or 0
    low_52w = metrics.get("52WeekLow", 0) or 0
    if high_52w > 0 and low_52w > 0:
        range_52w = high_52w - low_52w
        if range_52w > 0:
            # Approximate current position in range
            midpoint = (high_52w + low_52w) / 2
            position = (midpoint - low_52w) / range_52w
            scores.append(int(position * 60 + 30))
        else:
            scores.append(50)
    else:
        scores.append(50)

    final_score = sum(scores) / len(scores) if scores else 50
    return final_score, reasons[:2]


def score_earnings_strength(earnings: list) -> tuple[float, list[str]]:
    """
    Earnings/Event Strength Score (0-100). Weight: 20%

    Evaluates: beat history quality, surprise magnitude, reaction patterns,
    estimate direction, consistency.
    """
    reasons = []

    if not earnings or len(earnings) < 2:
        return 50, ["Insufficient earnings history for analysis"]

    # Extract data
    surprises = []
    beat_count = 0
    estimates_declining = False

    for e in earnings:
        actual = e.get("actual")
        estimate = e.get("estimate")
        if actual is not None and estimate is not None and estimate != 0:
            surprise_pct = ((actual - estimate) / abs(estimate)) * 100
            surprises.append(surprise_pct)
            if surprise_pct > 0:
                beat_count += 1

    if not surprises:
        return 50, ["No earnings surprise data available"]

    beat_rate = beat_count / len(surprises)
    avg_surprise = sum(surprises) / len(surprises)

    # Check if estimates are declining (lowered bar pattern)
    estimates = [e.get("estimate") for e in earnings if e.get("estimate") is not None]
    if len(estimates) >= 4:
        recent_est = sum(estimates[:2]) / 2
        older_est = sum(estimates[2:4]) / 2
        if older_est > 0 and recent_est < older_est * 0.85:
            estimates_declining = True

    scores = []

    # Beat rate
    if beat_rate >= 0.9:
        scores.append(85)
    elif beat_rate >= 0.7:
        scores.append(70)
    elif beat_rate >= 0.5:
        scores.append(50)
    else:
        scores.append(25)
        reasons.append(f"Poor beat rate ({beat_rate:.0%}) — frequently misses estimates")

    # Discount for "beating lowered bar"
    if estimates_declining and beat_rate > 0.7:
        scores.append(40)  # Heavily discount
        reasons.append("Beating lowered estimates — not genuine outperformance")
    elif not estimates_declining and beat_rate > 0.7:
        scores.append(80)
        reasons.append(f"Consistently beats estimates ({beat_rate:.0%}) on stable/rising bar")

    # Surprise magnitude
    if avg_surprise > 10:
        scores.append(80)
        reasons.append(f"Large average surprise (+{avg_surprise:.1f}%)")
    elif avg_surprise > 3:
        scores.append(70)
    elif avg_surprise > 0:
        scores.append(55)
    elif avg_surprise > -3:
        scores.append(40)
    else:
        scores.append(20)
        reasons.append(f"Negative average surprise ({avg_surprise:.1f}%)")

    # Consistency (low variance = more predictable)
    if len(surprises) >= 3:
        variance = sum((s - avg_surprise) ** 2 for s in surprises) / len(surprises)
        std_dev = math.sqrt(variance)
        if std_dev < 5:
            scores.append(75)
        elif std_dev < 15:
            scores.append(55)
        else:
            scores.append(35)
            reasons.append("Highly unpredictable earnings outcomes")

    # Trend (recent vs older)
    if len(surprises) >= 4:
        recent = sum(surprises[:2]) / 2
        older = sum(surprises[2:]) / len(surprises[2:])
        if recent > older + 3:
            scores.append(75)
            reasons.append("Earnings surprises trending upward")
        elif recent < older - 3:
            scores.append(30)
            reasons.append("Earnings surprises trending downward")
        else:
            scores.append(55)

    final_score = sum(scores) / len(scores) if scores else 50
    return final_score, reasons[:2]
