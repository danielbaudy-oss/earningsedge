"""
Prediction Engine v2 — Uses richer data for better predictions.

Improvements over v1:
- Fetches real-time financial data from Finnhub (recommendations, price targets)
- Considers revenue trends, not just EPS beats
- Weighs analyst revision direction
- Accounts for "beat on lowered estimates" pattern
- Uses price momentum as a signal
- More nuanced confidence scoring
"""

import asyncio
import httpx
from datetime import date, timedelta
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

settings = get_settings()
FINNHUB_BASE = "https://finnhub.io/api/v1"


async def fetch_finnhub(client: httpx.AsyncClient, endpoint: str, params: dict) -> dict | list:
    """Fetch from Finnhub with error handling."""
    params["token"] = settings.finnhub_api_key
    try:
        resp = await client.get(f"{FINNHUB_BASE}/{endpoint}", params=params)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {}


async def get_enriched_data(client: httpx.AsyncClient, ticker: str) -> dict:
    """Fetch all enrichment data for a ticker from Finnhub."""
    # Parallel requests
    recommendations, price_target, earnings, basic_financials = await asyncio.gather(
        fetch_finnhub(client, "stock/recommendation", {"symbol": ticker}),
        fetch_finnhub(client, "stock/price-target", {"symbol": ticker}),
        fetch_finnhub(client, "stock/earnings", {"symbol": ticker, "limit": 12}),
        fetch_finnhub(client, "stock/metric", {"symbol": ticker, "metric": "all"}),
    )

    return {
        "recommendations": recommendations if isinstance(recommendations, list) else [],
        "price_target": price_target if isinstance(price_target, dict) else {},
        "earnings": earnings if isinstance(earnings, list) else [],
        "metrics": basic_financials.get("metric", {}) if isinstance(basic_financials, dict) else {},
    }


def analyze_earnings_quality(earnings: list) -> dict:
    """
    Analyze earnings beyond simple beat/miss.
    Detects patterns like 'beating lowered estimates' vs 'genuine outperformance'.
    """
    if not earnings:
        return {"beat_rate": 0.5, "quality": "unknown", "trend": 0, "avg_surprise": 0}

    beats = []
    surprises = []
    for e in earnings:
        actual = e.get("actual")
        estimate = e.get("estimate")
        if actual is not None and estimate is not None and estimate != 0:
            surprise_pct = ((actual - estimate) / abs(estimate)) * 100
            surprises.append(surprise_pct)
            beats.append(1 if surprise_pct > 0 else 0)

    if not surprises:
        return {"beat_rate": 0.5, "quality": "unknown", "trend": 0, "avg_surprise": 0}

    beat_rate = sum(beats) / len(beats)
    avg_surprise = sum(surprises) / len(surprises)

    # Detect "beating lowered estimates" pattern:
    # If estimates are declining quarter over quarter, beats are less meaningful
    estimates = [e.get("estimate") for e in earnings if e.get("estimate") is not None]
    estimate_declining = False
    if len(estimates) >= 3:
        recent_avg = sum(estimates[:2]) / 2
        older_avg = sum(estimates[2:4]) / min(len(estimates[2:4]), 2)
        if older_avg > 0 and recent_avg < older_avg * 0.85:
            estimate_declining = True

    # Trend in surprises
    if len(surprises) >= 4:
        recent = sum(surprises[:2]) / 2
        older = sum(surprises[2:]) / len(surprises[2:])
        trend = recent - older
    else:
        trend = 0

    # Quality assessment
    if beat_rate > 0.7 and not estimate_declining and avg_surprise > 3:
        quality = "strong_beater"
    elif beat_rate > 0.7 and estimate_declining:
        quality = "beating_lowered_bar"  # NKE pattern
    elif beat_rate < 0.4:
        quality = "chronic_misser"
    else:
        quality = "mixed"

    return {
        "beat_rate": beat_rate,
        "quality": quality,
        "trend": trend,
        "avg_surprise": avg_surprise,
        "estimate_declining": estimate_declining,
        "num_quarters": len(surprises),
    }


def analyze_analyst_sentiment(recommendations: list, price_target: dict) -> dict:
    """Analyze analyst recommendation trends and price targets."""
    if not recommendations:
        return {"consensus": "neutral", "revision_trend": 0, "buy_pct": 0.5}

    # Most recent recommendation period
    latest = recommendations[0] if recommendations else {}
    buy = latest.get("buy", 0) + latest.get("strongBuy", 0)
    sell = latest.get("sell", 0) + latest.get("strongSell", 0)
    hold = latest.get("hold", 0)
    total = buy + sell + hold

    if total == 0:
        return {"consensus": "neutral", "revision_trend": 0, "buy_pct": 0.5}

    buy_pct = buy / total
    sell_pct = sell / total

    # Revision trend: compare current vs 2 months ago
    if len(recommendations) >= 2:
        prev = recommendations[1]
        prev_buy = prev.get("buy", 0) + prev.get("strongBuy", 0)
        prev_total = prev_buy + prev.get("sell", 0) + prev.get("strongSell", 0) + prev.get("hold", 0)
        prev_buy_pct = prev_buy / max(prev_total, 1)
        revision_trend = buy_pct - prev_buy_pct  # Positive = upgrades
    else:
        revision_trend = 0

    # Consensus
    if buy_pct > 0.6:
        consensus = "bullish"
    elif sell_pct > 0.3:
        consensus = "bearish"
    else:
        consensus = "neutral"

    # Price target upside
    target_mean = price_target.get("targetMean", 0)
    target_high = price_target.get("targetHigh", 0)
    target_low = price_target.get("targetLow", 0)

    return {
        "consensus": consensus,
        "revision_trend": round(revision_trend, 3),
        "buy_pct": round(buy_pct, 3),
        "sell_pct": round(sell_pct, 3),
        "target_mean": target_mean,
        "target_high": target_high,
        "target_low": target_low,
        "num_analysts": total,
    }


def analyze_fundamentals(metrics: dict) -> dict:
    """Extract key fundamental signals from Finnhub metrics."""
    return {
        "revenue_growth_ttm": metrics.get("revenueGrowthTTMYoy", 0) or 0,
        "eps_growth_ttm": metrics.get("epsGrowthTTMYoy", 0) or 0,
        "gross_margin": metrics.get("grossMarginTTM", 0) or 0,
        "operating_margin": metrics.get("operatingMarginTTM", 0) or 0,
        "roe": metrics.get("roeTTM", 0) or 0,
        "debt_equity": metrics.get("totalDebt/totalEquityQuarterly", 0) or 0,
        "pe_ratio": metrics.get("peTTM", 0) or 0,
        "ps_ratio": metrics.get("psTTM", 0) or 0,
        "52w_high_pct": metrics.get("52WeekHighDate", 0) or 0,
        "beta": metrics.get("beta", 1) or 1,
    }


def generate_prediction_v2(
    ticker: str,
    earnings_analysis: dict,
    analyst_sentiment: dict,
    fundamentals: dict,
) -> dict:
    """
    Generate prediction using multi-factor model.

    Factors and weights:
    - Earnings quality (30%): beat rate adjusted for estimate direction
    - Analyst sentiment (25%): consensus + revision direction
    - Fundamentals (25%): growth, margins, valuation
    - Momentum (20%): implied from analyst revisions + earnings trend
    """

    # --- Factor 1: Earnings Quality Score (0-1) ---
    quality = earnings_analysis.get("quality", "unknown")
    beat_rate = earnings_analysis.get("beat_rate", 0.5)

    if quality == "strong_beater":
        earnings_score = 0.85
    elif quality == "beating_lowered_bar":
        # Discount heavily — beating lowered estimates is not bullish
        earnings_score = 0.45
    elif quality == "chronic_misser":
        earnings_score = 0.15
    elif quality == "mixed":
        earnings_score = beat_rate * 0.6 + 0.2
    else:
        earnings_score = 0.5

    # --- Factor 2: Analyst Sentiment Score (0-1) ---
    consensus = analyst_sentiment.get("consensus", "neutral")
    revision_trend = analyst_sentiment.get("revision_trend", 0)

    if consensus == "bullish":
        analyst_score = 0.7 + min(revision_trend * 2, 0.2)
    elif consensus == "bearish":
        analyst_score = 0.25 + max(revision_trend * 2, -0.15)
    else:
        analyst_score = 0.5 + revision_trend * 3

    analyst_score = max(0.1, min(0.95, analyst_score))

    # --- Factor 3: Fundamentals Score (0-1) ---
    rev_growth = fundamentals.get("revenue_growth_ttm", 0)
    eps_growth = fundamentals.get("eps_growth_ttm", 0)
    margin = fundamentals.get("operating_margin", 0)

    growth_signal = 0.5
    if rev_growth > 15:
        growth_signal = 0.8
    elif rev_growth > 5:
        growth_signal = 0.65
    elif rev_growth < -5:
        growth_signal = 0.3
    elif rev_growth < -15:
        growth_signal = 0.15

    margin_signal = min(max(margin / 30, 0.2), 0.9) if margin > 0 else 0.2
    fundamentals_score = growth_signal * 0.6 + margin_signal * 0.4

    # --- Factor 4: Momentum Score (0-1) ---
    # Derived from revision trend + earnings trend
    earnings_trend = earnings_analysis.get("trend", 0)
    momentum_score = 0.5 + (revision_trend * 5) + (earnings_trend * 0.02)
    momentum_score = max(0.1, min(0.9, momentum_score))

    # --- Weighted Composite ---
    composite = (
        earnings_score * 0.30 +
        analyst_score * 0.25 +
        fundamentals_score * 0.25 +
        momentum_score * 0.20
    )

    # --- Beat Probability ---
    beat_prob = earnings_score * 0.5 + analyst_score * 0.3 + 0.2 * (1 if earnings_trend > 0 else 0.3)
    beat_prob = max(0.1, min(0.95, beat_prob))

    # --- Price Direction ---
    price_up_prob = composite * 0.85 + 0.08  # Slight upward bias (market tends up)
    price_up_prob = max(0.1, min(0.9, price_up_prob))

    # --- Expected Move ---
    avg_surprise = earnings_analysis.get("avg_surprise", 0)
    expected_move = avg_surprise * 0.3 * (1 if composite > 0.5 else -0.5)
    expected_vol = abs(avg_surprise) * 1.2 + 3.0

    # --- Confidence ---
    data_quality = min(earnings_analysis.get("num_quarters", 0) / 8, 1.0)
    signal_strength = abs(composite - 0.5) * 2
    confidence = signal_strength * 0.6 + data_quality * 0.3 + (analyst_sentiment.get("num_analysts", 0) > 5) * 0.1
    confidence = max(0.15, min(0.92, confidence))

    # --- Recommendation ---
    if composite > 0.62 and confidence > 0.4:
        recommendation = "buy"
    elif composite < 0.38 and confidence > 0.3:
        recommendation = "sell"
    else:
        recommendation = "avoid"

    # --- Explanation ---
    explanation_lines = []

    if quality == "beating_lowered_bar":
        explanation_lines.append(
            f"{ticker} has beaten estimates {beat_rate:.0%} of the time, but estimates have been declining — "
            f"these are beats on a lowered bar, not genuine outperformance."
        )
    elif quality == "strong_beater":
        explanation_lines.append(f"{ticker} consistently beats estimates with strong surprise magnitude.")
    elif quality == "chronic_misser":
        explanation_lines.append(f"{ticker} has a history of missing estimates.")
    else:
        explanation_lines.append(f"{ticker} has a mixed earnings track record ({beat_rate:.0%} beat rate).")

    if consensus == "bullish":
        explanation_lines.append(f"Analysts are bullish ({analyst_sentiment['buy_pct']:.0%} buy ratings).")
    elif consensus == "bearish":
        explanation_lines.append(f"Analysts are cautious ({analyst_sentiment.get('sell_pct', 0):.0%} sell ratings).")

    if revision_trend > 0.05:
        explanation_lines.append("Analyst estimates have been revised upward recently.")
    elif revision_trend < -0.05:
        explanation_lines.append("Analyst estimates have been revised downward recently.")

    if rev_growth < -5:
        explanation_lines.append(f"Revenue is declining ({rev_growth:.1f}% YoY) — a headwind for the stock.")
    elif rev_growth > 15:
        explanation_lines.append(f"Strong revenue growth ({rev_growth:.1f}% YoY) supports the thesis.")

    explanation_lines.append(f"Expected move: {expected_move:+.1f}% with {expected_vol:.1f}% volatility.")

    return {
        "recommendation": recommendation,
        "confidence_score": round(confidence, 3),
        "beat_probability": round(beat_prob, 3),
        "miss_probability": round(1 - beat_prob, 3),
        "price_up_probability": round(price_up_prob, 3),
        "price_down_probability": round(1 - price_up_prob, 3),
        "expected_move_pct": round(expected_move, 2),
        "expected_volatility": round(expected_vol, 2),
        "predicted_direction": "up" if price_up_prob > 0.5 else "down",
        "explanation_text": "\n".join(explanation_lines),
        "feature_importance": {
            "earnings_quality": round(earnings_score, 3),
            "analyst_sentiment": round(analyst_score, 3),
            "fundamentals": round(fundamentals_score, 3),
            "momentum": round(momentum_score, 3),
            "composite": round(composite, 3),
        },
    }


async def generate_all_predictions_v2():
    """Generate v2 predictions for all upcoming earnings."""
    print("🤖 Generating v2 predictions (multi-factor model)...\n")
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)

    # Get upcoming earnings
    today = date.today().isoformat()
    upcoming = (
        sb.table("earnings_events")
        .select("id, stock_id, report_date, stocks(id, ticker, company_name)")
        .gte("report_date", today)
        .order("report_date")
        .execute()
    )

    if not upcoming.data:
        print("No upcoming earnings found.")
        return

    # Delete old predictions first (unique constraint)
    for event in upcoming.data:
        try:
            # Delete via REST API PATCH isn't available, use service key direct
            import httpx as hx
            headers = {
                "apikey": settings.supabase_service_key,
                "Authorization": f"Bearer {settings.supabase_service_key}",
            }
            url = f"{settings.supabase_url}/rest/v1/predictions?earnings_event_id=eq.{event['id']}"
            async with hx.AsyncClient() as c:
                await c.delete(url, headers=headers)
        except Exception:
            pass

    generated = 0
    for event in upcoming.data:
        stock = event.get("stocks") or {}
        ticker = stock.get("ticker", "???")

        print(f"  Analyzing {ticker}...")

        # Fetch enriched data from Finnhub
        data = await get_enriched_data(client, ticker)

        # Analyze each dimension
        earnings_analysis = analyze_earnings_quality(data["earnings"])
        analyst_sentiment = analyze_analyst_sentiment(data["recommendations"], data["price_target"])
        fundamentals = analyze_fundamentals(data["metrics"])

        # Generate prediction
        pred = generate_prediction_v2(ticker, earnings_analysis, analyst_sentiment, fundamentals)

        # Store
        pred_data = {
            "stock_id": event["stock_id"],
            "earnings_event_id": event["id"],
            "model_version": "multifactor_v2",
            "recommendation": pred["recommendation"],
            "confidence_score": pred["confidence_score"],
            "beat_probability": pred["beat_probability"],
            "miss_probability": pred["miss_probability"],
            "price_up_probability": pred["price_up_probability"],
            "price_down_probability": pred["price_down_probability"],
            "expected_move_pct": pred["expected_move_pct"],
            "expected_volatility": pred["expected_volatility"],
            "predicted_direction": pred["predicted_direction"],
            "feature_importance": pred["feature_importance"],
            "explanation_text": pred["explanation_text"],
        }

        try:
            sb.table("predictions").upsert(pred_data, on_conflict="stock_id,earnings_event_id")
            generated += 1
            emoji = {"buy": "🟢", "sell": "🔴", "avoid": "🟡"}[pred["recommendation"]]
            print(f"    {emoji} {pred['recommendation'].upper()} "
                  f"(conf: {pred['confidence_score']:.0%}, beat: {pred['beat_probability']:.0%})")
            print(f"    Factors: earnings={earnings_analysis['quality']}, "
                  f"analysts={analyst_sentiment['consensus']}, "
                  f"rev_growth={fundamentals['revenue_growth_ttm']:.1f}%")
        except Exception as e:
            print(f"    ❌ {e}")

        # Rate limit
        await asyncio.sleep(1.5)

    await client.aclose()
    print(f"\n✅ Generated {generated} v2 predictions")


if __name__ == "__main__":
    asyncio.run(generate_all_predictions_v2())
