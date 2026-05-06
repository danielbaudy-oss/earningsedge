"""
Generate predictions using the trained XGBoost model.
Combines ML predictions with the multi-factor scoring for the final output.

Output format per spec:
- Score (0-100)
- Buy / Hold / Avoid
- Earnings beat probability
- Post-earnings move probability
- Expected move %
- Risk score
- Top 3 key reasons
- Mode: trader vs longterm
"""

import asyncio
import httpx
import numpy as np
import pandas as pd
import joblib
from pathlib import Path
from datetime import date, timedelta
from app.core.config import get_settings
from app.db.supabase_client import get_supabase
from app.ml.train_xgboost import build_features_from_history, fetch_finnhub

settings = get_settings()
FINNHUB_BASE = "https://finnhub.io/api/v1"


def load_models():
    """Load trained XGBoost models."""
    model_dir = Path(settings.model_path)
    if not (model_dir / "beat_model.joblib").exists():
        return None, None, None, None

    beat_model = joblib.load(model_dir / "beat_model.joblib")
    direction_model = joblib.load(model_dir / "direction_model.joblib")
    magnitude_model = joblib.load(model_dir / "magnitude_model.joblib")
    feature_names = joblib.load(model_dir / "feature_names.joblib")
    return beat_model, direction_model, magnitude_model, feature_names


def calculate_risk_score(beat_prob: float, direction_prob: float,
                         expected_move: float, volatility: float, beta: float) -> int:
    """
    Risk score 0-100 (higher = riskier).
    Considers uncertainty, volatility, and downside potential.
    """
    # Uncertainty: how close to 50/50 are the predictions?
    beat_uncertainty = 1 - abs(beat_prob - 0.5) * 2  # 0 at extremes, 1 at 50%
    dir_uncertainty = 1 - abs(direction_prob - 0.5) * 2

    # Volatility component
    vol_risk = min(volatility / 10, 1.0)  # Normalize to 0-1

    # Beta component
    beta_risk = min(max((beta - 0.5) / 2, 0), 1.0)

    # Downside potential
    downside = max(-expected_move / 10, 0)  # Negative expected move = risk

    risk = (
        beat_uncertainty * 25 +
        dir_uncertainty * 25 +
        vol_risk * 20 +
        beta_risk * 15 +
        downside * 15
    )

    return int(max(5, min(95, risk)))


def generate_recommendation(score: int, mode: str, risk_score: int,
                            beat_prob: float, direction_prob: float) -> str:
    """
    Generate Buy/Hold/Avoid based on score and mode.

    Trader mode: more aggressive, lower threshold for buy
    Long-term mode: more conservative, needs stronger fundamentals
    """
    if mode == "trader":
        if score >= 60 and direction_prob > 0.55 and risk_score < 70:
            return "buy"
        elif score < 35 or (direction_prob < 0.4 and risk_score > 60):
            return "sell"
        else:
            return "avoid"
    else:  # longterm
        if score >= 70 and beat_prob > 0.6 and risk_score < 55:
            return "buy"
        elif score < 30 or beat_prob < 0.35:
            return "sell"
        else:
            return "avoid"


def build_explanation(features: dict, beat_prob: float, direction_prob: float,
                      expected_move: float, risk_score: int, mode: str,
                      ticker: str, metrics: dict) -> tuple[str, list[str]]:
    """Generate useful company context and key differentiators as reasons."""
    reasons = []

    # Company fundamentals context (useful info, not repeating probabilities)
    rev_growth = metrics.get("revenueGrowthTTMYoy", 0) or 0
    op_margin = metrics.get("operatingMarginTTM", 0) or 0
    pe = metrics.get("peTTM", 0) or 0
    beta = features.get("beta", 1)
    momentum_13w = features.get("momentum_13w", 0)

    # Revenue story
    if rev_growth > 25:
        reasons.append(f"Revenue growing {rev_growth:.0f}% YoY — strong top-line momentum")
    elif rev_growth > 10:
        reasons.append(f"Solid revenue growth at {rev_growth:.0f}% YoY")
    elif rev_growth > 0:
        reasons.append(f"Modest revenue growth ({rev_growth:.0f}% YoY)")
    elif rev_growth > -10:
        reasons.append(f"Revenue declining {rev_growth:.0f}% YoY — watch for turnaround signals")
    else:
        reasons.append(f"Revenue in sharp decline ({rev_growth:.0f}% YoY) — significant headwind")

    # Margin story
    if op_margin > 25:
        reasons.append(f"High-margin business ({op_margin:.0f}% operating margin)")
    elif op_margin > 10:
        reasons.append(f"Healthy margins ({op_margin:.0f}% operating margin)")
    elif op_margin > 0:
        reasons.append(f"Thin margins ({op_margin:.0f}%) — less room for error")
    else:
        reasons.append(f"Currently unprofitable ({op_margin:.0f}% operating margin)")

    # Price trend context
    if momentum_13w < -20:
        reasons.append(f"Stock down {momentum_13w:.0f}% in 13 weeks — heavy selling pressure")
    elif momentum_13w < -10:
        reasons.append(f"Stock in downtrend ({momentum_13w:.0f}% over 13 weeks)")
    elif momentum_13w > 20:
        reasons.append(f"Strong uptrend (+{momentum_13w:.0f}% in 13 weeks) — momentum tailwind")
    elif momentum_13w > 10:
        reasons.append(f"Stock trending up (+{momentum_13w:.0f}% over 13 weeks)")

    # Valuation context
    if pe > 50:
        reasons.append(f"Premium valuation (PE {pe:.0f}x) — market expects strong growth")
    elif pe > 0 and pe < 12:
        reasons.append(f"Value territory (PE {pe:.0f}x) — low expectations to beat")

    # Earnings pattern
    beat_rate = features.get("beat_rate_prior", 0)
    beat_up_rate = features.get("beat_leads_to_up_rate", 0.5)
    if beat_rate > 0.8 and beat_up_rate < 0.5:
        reasons.append("Beats estimates often but stock doesn't always react positively")
    elif beat_rate > 0.8 and beat_up_rate > 0.7:
        reasons.append("Consistent beater AND stock typically rallies after earnings")

    # Estimate trend
    est_change = features.get("estimate_change_pct", 0)
    if est_change < -15:
        reasons.append("Analyst estimates cut significantly — low bar to beat")
    elif est_change > 15:
        reasons.append("Estimates revised up — high expectations priced in")

    # Build explanation text
    top_3 = reasons[:3]
    explanation = f"{ticker} earnings analysis:\n" + "\n".join(f"- {r}" for r in top_3)

    return explanation, top_3


async def predict_stock(client: httpx.AsyncClient, ticker: str, stock_id: int,
                        event_id: int, mode: str = "trader") -> dict | None:
    """Generate full prediction for a single stock."""
    sb = get_supabase()

    # Load models
    beat_model, direction_model, magnitude_model, feature_names = load_models()
    if beat_model is None:
        return None

    # Get earnings history
    events = (
        sb.table("earnings_events")
        .select("report_date, eps_actual, eps_estimate, eps_surprise_pct, price_change_pct")
        .eq("stock_id", stock_id)
        .lte("report_date", date.today().isoformat())
        .order("report_date", desc=True)
        .limit(12)
        .execute()
    )

    earnings = events.data
    if len(earnings) < 2:
        return None

    # Build features (predicting next event, so use index -1 trick)
    # Insert a dummy "current" event at position 0
    dummy_current = {"eps_estimate": earnings[0].get("eps_estimate"), "report_date": date.today().isoformat()}
    full_list = [dummy_current] + earnings
    features = build_features_from_history(full_list, 0)
    if features is None:
        return None

    # Fetch Finnhub metrics for enrichment
    metrics_data = await fetch_finnhub(client, "stock/metric", {"symbol": ticker, "metric": "all"})
    metrics = (metrics_data or {}).get("metric", {}) if isinstance(metrics_data, dict) else {}

    # Also fetch company profile to get the real name (if we only have ticker as name)
    profile = await fetch_finnhub(client, "stock/profile2", {"symbol": ticker})
    if profile and isinstance(profile, dict) and profile.get("name"):
        company_name = profile["name"]
        # Update stock record with real name
        try:
            import httpx as hx
            headers = {
                "apikey": settings.supabase_service_key,
                "Authorization": f"Bearer {settings.supabase_service_key}",
                "Content-Type": "application/json",
            }
            url = f"{settings.supabase_url}/rest/v1/stocks?id=eq.{stock_id}"
            update_data = {
                "company_name": company_name,
                "sector": profile.get("finnhubIndustry", ""),
            }

            # Also try to get description from Polygon
            poly_resp = await client.get(
                f"{POLYGON_BASE}/v3/reference/tickers/{ticker}",
                params={"apiKey": settings.polygon_api_key},
            )
            if poly_resp.status_code == 200:
                poly_data = poly_resp.json().get("results", {})
                if poly_data.get("description"):
                    update_data["description"] = poly_data["description"][:500]

            async with hx.AsyncClient() as patch_client:
                await patch_client.patch(url, json=update_data, headers=headers)
        except Exception:
            pass

    features["revenue_growth"] = metrics.get("revenueGrowthTTMYoy", 0) or 0
    features["eps_growth"] = metrics.get("epsGrowthTTMYoy", 0) or 0
    features["operating_margin"] = metrics.get("operatingMarginTTM", 0) or 0
    features["pe_ratio"] = metrics.get("peTTM", 0) or 0
    features["beta"] = metrics.get("beta", 1) or 1

    # Price momentum / trend from Finnhub
    momentum_13w = metrics.get("13WeekPriceReturnDaily", 0) or 0
    momentum_mtd = metrics.get("monthToDatePriceReturnDaily", 0) or 0
    momentum_signal = momentum_13w if abs(momentum_13w) > abs(momentum_mtd) else momentum_mtd

    features["momentum_13w"] = momentum_13w
    features["momentum_26w"] = metrics.get("26WeekPriceReturnDaily", 0) or 0
    features["momentum_52w"] = metrics.get("52WeekPriceReturnDaily", 0) or 0
    features["momentum_mtd"] = momentum_mtd
    features["momentum_5d"] = metrics.get("5DayPriceReturnDaily", 0) or 0
    features["price_vs_sp500_13w"] = metrics.get("priceRelativeToS&P50013Week", 0) or 0
    features["ytd_return"] = metrics.get("yearToDatePriceReturnDaily", 0) or 0

    # 52-week range position
    high_52w = metrics.get("52WeekHigh", 0) or 0
    low_52w = metrics.get("52WeekLow", 0) or 0
    if high_52w > 0 and low_52w > 0 and high_52w != low_52w:
        features["range_position_52w"] = max(0, min(1, (high_52w - low_52w * 1.1) / (high_52w - low_52w)))
    else:
        features["range_position_52w"] = 0.5

    # Earnings target hit patterns (beat → stock up correlation)
    beat_and_up = 0
    beat_and_down = 0
    miss_and_down = 0
    miss_and_up = 0
    for p in earnings[:6]:
        surprise = p.get("eps_surprise_pct", 0) or 0
        move = p.get("price_change_pct")
        if move is not None:
            if surprise > 0 and move > 0:
                beat_and_up += 1
            elif surprise > 0 and move <= 0:
                beat_and_down += 1
            elif surprise <= 0 and move < 0:
                miss_and_down += 1
            elif surprise <= 0 and move >= 0:
                miss_and_up += 1

    total_with_moves = beat_and_up + beat_and_down + miss_and_down + miss_and_up
    if total_with_moves > 0:
        features["beat_leads_to_up_rate"] = beat_and_up / max(beat_and_up + beat_and_down, 1)
        features["miss_leads_to_down_rate"] = miss_and_down / max(miss_and_down + miss_and_up, 1)
        features["reaction_predictability"] = (beat_and_up + miss_and_down) / total_with_moves
    else:
        features["beat_leads_to_up_rate"] = 0.5
        features["miss_leads_to_down_rate"] = 0.5
        features["reaction_predictability"] = 0.5

    # Create DataFrame with correct feature order
    X = pd.DataFrame([features])
    for col in feature_names:
        if col not in X.columns:
            X[col] = 0
    X = X[feature_names].fillna(0).replace([np.inf, -np.inf], 0)

    # ML predictions
    beat_prob = float(beat_model.predict_proba(X)[0][1])
    direction_prob_raw = float(direction_model.predict_proba(X)[0][1])
    raw_move = float(magnitude_model.predict(X)[0])

    # --- MOMENTUM ADJUSTMENT ---
    # Stock in downtrend? Discount "goes up" probability.
    # Stock in uptrend? Slight boost.
    momentum_adj = 0.0
    if momentum_signal < -15:
        momentum_adj = -0.20
    elif momentum_signal < -8:
        momentum_adj = -0.12
    elif momentum_signal < -3:
        momentum_adj = -0.06
    elif momentum_signal > 15:
        momentum_adj = 0.10
    elif momentum_signal > 5:
        momentum_adj = 0.05

    direction_prob = max(0.05, min(0.95, direction_prob_raw + momentum_adj))

    # Adjust expected move: use stock-specific volatility, not a flat default
    prior_moves = [e.get("price_change_pct", 0) for e in earnings if e.get("price_change_pct") is not None]

    if prior_moves and len(prior_moves) >= 2:
        # Best case: we have actual historical earnings reactions
        avg_abs_move = float(np.mean([abs(m) for m in prior_moves]))
        volatility = float(np.std(prior_moves))
    else:
        # Fallback: estimate from beta and 3-month return volatility
        beta = features.get("beta", 1)
        return_3m_std = metrics.get("3MonthADReturnStd", 0) or 0

        if return_3m_std > 0:
            # Daily std * sqrt(1) for 1-day earnings move estimate
            # Typical earnings move is ~2-3x a normal daily move
            daily_vol = return_3m_std / 100  # Convert from percentage
            avg_abs_move = daily_vol * 2.5 * 100  # Back to percentage, scaled for earnings
        else:
            # Last resort: use beta as proxy (higher beta = bigger moves)
            avg_abs_move = max(1.5, beta * 2.5)

        volatility = avg_abs_move * 1.2

    # Cap at reasonable bounds
    avg_abs_move = max(0.5, min(avg_abs_move, 20.0))

    if direction_prob > 0.55:
        expected_move = avg_abs_move * (direction_prob - 0.5) * 2
    elif direction_prob < 0.45:
        expected_move = -avg_abs_move * (0.5 - direction_prob) * 2
    else:
        expected_move = raw_move + (momentum_signal * 0.03)

    # Round to avoid false precision
    expected_move = round(expected_move, 1)

    # Risk score
    beta = features.get("beta", 1)
    risk_score = calculate_risk_score(beat_prob, direction_prob, expected_move, volatility, beta)

    # Total score (0-100)
    # Weighted: beat_prob (30%) + direction_prob (30%) + fundamentals (20%) + low_risk (20%)
    fundamentals_signal = min(max((features.get("revenue_growth", 0) + 10) / 40, 0), 1)
    risk_bonus = (100 - risk_score) / 100

    total_score = int(
        beat_prob * 30 +
        direction_prob * 30 +
        fundamentals_signal * 20 +
        risk_bonus * 20
    )
    total_score = max(5, min(95, total_score))

    # Recommendation
    recommendation = generate_recommendation(total_score, mode, risk_score, beat_prob, direction_prob)

    # Explanation
    explanation, top_3_reasons = build_explanation(
        features, beat_prob, direction_prob, expected_move, risk_score, mode, ticker, metrics
    )

    return {
        "stock_id": stock_id,
        "earnings_event_id": event_id,
        "model_version": "xgboost_v1",
        "recommendation": recommendation,
        "confidence_score": total_score / 100,  # Normalize to 0-1 for DB
        "beat_probability": round(beat_prob, 3),
        "miss_probability": round(1 - beat_prob, 3),
        "price_up_probability": round(direction_prob, 3),
        "price_down_probability": round(1 - direction_prob, 3),
        "expected_move_pct": round(expected_move, 2),
        "expected_volatility": round(volatility, 2),
        "predicted_direction": "up" if direction_prob > 0.5 else "down",
        "feature_importance": {
            "total_score": total_score,
            "risk_score": risk_score,
            "top_reasons": top_3_reasons,
            "mode": mode,
        },
        "explanation_text": explanation,
    }


async def generate_all_ml_predictions(mode: str = "trader"):
    """Generate ML predictions for all upcoming earnings."""
    print(f"🤖 Generating XGBoost predictions (mode: {mode})...\n")
    sb = get_supabase()
    client = httpx.AsyncClient(timeout=30.0)

    # Get upcoming earnings
    today = date.today().isoformat()
    upcoming = (
        sb.table("earnings_events")
        .select("id, stock_id, report_date, stocks(ticker, company_name)")
        .gte("report_date", today)
        .order("report_date")
        .execute()
    )

    if not upcoming.data:
        print("No upcoming earnings found.")
        return

    generated = 0
    for event in upcoming.data:
        stock = event.get("stocks") or {}
        ticker = stock.get("ticker", "???")

        pred = await predict_stock(client, ticker, event["stock_id"], event["id"], mode)
        if pred is None:
            print(f"  ⚠️  {ticker}: insufficient data for ML prediction")
            continue

        # Upsert prediction
        try:
            sb.table("predictions").upsert(pred, on_conflict="stock_id,earnings_event_id")
            generated += 1
            score = pred["feature_importance"]["total_score"]
            risk = pred["feature_importance"]["risk_score"]
            emoji = {"buy": "🟢", "sell": "🔴", "avoid": "🟡"}[pred["recommendation"]]
            print(f"  {emoji} {ticker}: {pred['recommendation'].upper()} "
                  f"Score:{score}/100 Risk:{risk}/100 "
                  f"Beat:{pred['beat_probability']:.0%} Up:{pred['price_up_probability']:.0%}")
        except Exception as e:
            print(f"  ❌ {ticker}: {e}")

        await asyncio.sleep(1.5)  # Finnhub rate limit

    await client.aclose()
    print(f"\n✅ Generated {generated} ML predictions")


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "trader"
    asyncio.run(generate_all_ml_predictions(mode))
