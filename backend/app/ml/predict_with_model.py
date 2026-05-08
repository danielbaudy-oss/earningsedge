"""
Generate predictions using the trained XGBoost model.
Combines ML predictions with the multi-factor scoring for the final output.

V2 Improvements:
- Recency-weighted beat probability (exponential decay)
- Direction decoupled from historical move direction (current signals drive it)
- Feature snapshots stored for backtesting
- IV signal integration (implied vs actual move history)

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


# ---------------------------------------------------------------------------
# IMPROVEMENT 1: Recency-weighted beat probability
# ---------------------------------------------------------------------------

def recency_weighted_beat_rate(earnings: list, decay: float = 0.80) -> float:
    """
    Calculate beat rate with exponential decay weighting.
    Most recent quarter gets weight 1.0, each prior quarter is multiplied by `decay`.
    
    decay=0.80 means:
      Q-1: weight 1.0
      Q-2: weight 0.80
      Q-3: weight 0.64
      Q-4: weight 0.51
      Q-5: weight 0.41
      ...
    
    This captures the trend — a company that beat last 3 but missed 2 years ago
    should score higher than one that missed last 2 but beat 3 years ago.
    """
    weights = []
    beats = []

    for i, e in enumerate(earnings):
        actual = e.get("eps_actual")
        estimate = e.get("eps_estimate")
        if actual is not None and estimate is not None:
            weight = decay ** i  # i=0 is most recent
            weights.append(weight)
            beats.append(1.0 if actual > estimate else 0.0)

    if not weights:
        return 0.5  # No data, assume 50/50

    total_weight = sum(weights)
    weighted_beat_rate = sum(b * w for b, w in zip(beats, weights)) / total_weight
    return weighted_beat_rate


def recency_weighted_surprise(earnings: list, decay: float = 0.80) -> float:
    """Average surprise % with recency weighting."""
    weights = []
    surprises = []

    for i, e in enumerate(earnings):
        surprise = e.get("eps_surprise_pct")
        if surprise is not None:
            weight = decay ** i
            weights.append(weight)
            surprises.append(surprise)

    if not weights:
        return 0.0

    total_weight = sum(weights)
    return sum(s * w for s, w in zip(surprises, weights)) / total_weight


def compute_beat_consistency(earnings: list) -> dict:
    """
    Analyze the consistency and magnitude of earnings beats vs consensus estimates.
    
    This is a KEY signal: if a company beat consensus EPS in the last 4 quarters,
    it's highly likely to beat again. The pattern is:
    - Management sandbagging guidance
    - Analysts being slow to revise up
    - Structural outperformance (cost cuts, pricing power, etc.)
    
    Returns a dict with:
    - consecutive_beats: how many quarters in a row they beat (0 if last was a miss)
    - avg_beat_magnitude: average % by which they beat (recency-weighted)
    - beat_trend: are beats getting bigger or smaller?
    - consistency_score: 0-1 score combining streak + magnitude + trend
    """
    beats_in_row = 0
    beat_magnitudes = []
    
    for e in earnings:
        actual = e.get("eps_actual")
        estimate = e.get("eps_estimate")
        if actual is None or estimate is None:
            continue
        
        if estimate != 0:
            surprise_pct = ((actual - estimate) / abs(estimate)) * 100
        else:
            surprise_pct = 0
        
        if actual > estimate:
            beats_in_row += 1
            beat_magnitudes.append(surprise_pct)
        else:
            break  # Streak broken
    
    # Average beat magnitude (recency-weighted)
    if beat_magnitudes:
        weights = [0.80 ** i for i in range(len(beat_magnitudes))]
        total_w = sum(weights)
        avg_magnitude = sum(m * w for m, w in zip(beat_magnitudes, weights)) / total_w
    else:
        avg_magnitude = 0
    
    # Beat trend: are recent beats bigger than older ones?
    beat_trend = 0
    if len(beat_magnitudes) >= 3:
        recent = np.mean(beat_magnitudes[:2])
        older = np.mean(beat_magnitudes[2:])
        if older != 0:
            beat_trend = (recent - older) / abs(older)  # Positive = beats growing
    
    # Consistency score (0-1):
    # - 4+ consecutive beats with avg magnitude > 5% = very high (0.85+)
    # - 3 consecutive beats = high (0.70+)
    # - 2 consecutive beats = moderate (0.55+)
    # - 1 or 0 = low
    streak_score = min(beats_in_row / 5, 1.0)  # Caps at 5 quarters
    magnitude_score = min(avg_magnitude / 20, 1.0)  # Caps at 20% avg beat
    trend_bonus = max(0, min(beat_trend * 0.1, 0.1))  # Small bonus for growing beats
    
    consistency_score = streak_score * 0.6 + magnitude_score * 0.3 + trend_bonus + 0.1
    consistency_score = max(0, min(1.0, consistency_score))
    
    return {
        "consecutive_beats": beats_in_row,
        "avg_beat_magnitude": round(avg_magnitude, 2),
        "beat_trend": round(beat_trend, 2),
        "consistency_score": round(consistency_score, 3),
    }


# ---------------------------------------------------------------------------
# IMPROVEMENT 2: Direction scoring decoupled from historical move direction
# ---------------------------------------------------------------------------

def compute_direction_from_current_signals(
    features: dict,
    ml_direction_prob: float,
    beat_prob: float,
    momentum_signal: float,
) -> float:
    """
    Compute direction probability as a blend of signals,
    with HEAVY weight on recent stock price behavior (last month).
    
    The stock's recent trajectory leading into earnings is the strongest
    short-term predictor. Closer-to-earnings price action matters more.
    
    Weights:
    - Recent price action (5d, MTD, 13w blended with recency): 45%
    - Beat probability influence: 20%
    - ML model raw output: 15%
    - Analyst revisions: 12%
    - Insider activity: 8%
    """
    # --- RECENT PRICE ACTION (45%) ---
    # Blend multiple timeframes with heavy recency weighting:
    # Last 5 days matters most (closest to earnings), then MTD, then 13w
    momentum_5d = features.get("momentum_5d", 0)
    momentum_mtd = features.get("momentum_mtd", 0)
    momentum_13w = features.get("momentum_13w", 0)
    momentum_52w = features.get("momentum_52w", 0)

    # Recency-weighted momentum: 50% last 5 days, 30% MTD, 20% 13-week
    blended_momentum = momentum_5d * 0.50 + momentum_mtd * 0.30 + momentum_13w * 0.20

    # DAMPEN momentum when long-term trend contradicts short-term
    # A stock down 50%+ in 52 weeks that bounced 20% in 13 weeks is NOT bullish —
    # it's a dead cat bounce until proven otherwise
    if momentum_52w < -40 and momentum_13w > 10:
        # Severe long-term decline + short-term bounce = dampen heavily
        blended_momentum *= 0.3
    elif momentum_52w < -25 and momentum_13w > 5:
        # Significant decline + moderate bounce = dampen
        blended_momentum *= 0.5
    elif momentum_52w < -15 and momentum_13w > 15:
        # Moderate decline + strong bounce = slight dampen
        blended_momentum *= 0.7

    # Convert momentum to probability scale (sigmoid-like mapping)
    # -20% momentum → ~0.25 prob, 0% → 0.50, +20% → ~0.75
    if blended_momentum >= 0:
        momentum_contrib = 0.50 + min(blended_momentum / 40, 0.35)
    else:
        momentum_contrib = 0.50 + max(blended_momentum / 40, -0.35)

    # --- BEAT PROBABILITY (20%) ---
    # If likely to beat, stock more likely to go up
    beat_contrib = 0.35 + beat_prob * 0.35  # Maps 0→0.35, 0.5→0.525, 1.0→0.70

    # --- ML MODEL (15%) ---
    # Dampened toward center — it captures patterns but shouldn't dominate
    ml_contrib = 0.5 + (ml_direction_prob - 0.5) * 0.5

    # --- ANALYST REVISIONS (12%) ---
    rev_signal = features.get("analyst_revision_signal", 0)
    if rev_signal >= 4:
        analyst_contrib = 0.75
    elif rev_signal >= 2:
        analyst_contrib = 0.65
    elif rev_signal >= 1:
        analyst_contrib = 0.57
    elif rev_signal <= -4:
        analyst_contrib = 0.25
    elif rev_signal <= -2:
        analyst_contrib = 0.35
    elif rev_signal <= -1:
        analyst_contrib = 0.43
    else:
        analyst_contrib = 0.50

    # --- INSIDER ACTIVITY (8%) ---
    insider = features.get("insider_signal", 0)
    if insider > 0.5:
        insider_contrib = 0.65
    elif insider > 0.2:
        insider_contrib = 0.57
    elif insider < -0.5:
        insider_contrib = 0.35
    elif insider < -0.2:
        insider_contrib = 0.43
    else:
        insider_contrib = 0.50

    # Weighted combination
    direction_prob = (
        momentum_contrib * 0.45 +
        beat_contrib * 0.20 +
        ml_contrib * 0.15 +
        analyst_contrib * 0.12 +
        insider_contrib * 0.08
    )

    # Clamp to reasonable bounds
    return max(0.10, min(0.90, direction_prob))


# ---------------------------------------------------------------------------
# IMPROVEMENT 3: IV signal — compare implied vs actual historical moves
# ---------------------------------------------------------------------------

def compute_iv_signal(earnings: list, market_implied_move: float | None) -> dict:
    """
    Analyze how this stock's actual earnings moves compare to what options implied.
    
    If actual moves consistently EXCEED implied moves → options underpricing risk
    → directional bets have positive expected value.
    
    If actual moves consistently UNDERSHOOT implied → options overpricing
    → selling premium is better than directional bets.
    
    Returns dict with:
    - iv_vs_actual_ratio: avg(actual_move / implied_move) — >1 means underpriced
    - move_exceeds_implied_rate: how often actual > implied
    - current_implied_move: what options are pricing now (if available)
    """
    # For now, we use historical actual moves as a proxy
    # Once we store implied moves at prediction time, we can compare directly
    actual_moves = [abs(e.get("price_change_pct", 0)) for e in earnings
                    if e.get("price_change_pct") is not None]

    if not actual_moves or len(actual_moves) < 2:
        return {
            "iv_vs_actual_ratio": 1.0,
            "move_exceeds_implied_rate": 0.5,
            "current_implied_move": market_implied_move,
            "avg_actual_move": 0,
        }

    avg_actual = np.mean(actual_moves)

    # If we have current implied move, compare to historical actual
    if market_implied_move and market_implied_move > 0:
        iv_ratio = avg_actual / market_implied_move
        exceeds_rate = sum(1 for m in actual_moves if m > market_implied_move) / len(actual_moves)
    else:
        iv_ratio = 1.0
        exceeds_rate = 0.5

    return {
        "iv_vs_actual_ratio": round(iv_ratio, 2),
        "move_exceeds_implied_rate": round(exceeds_rate, 2),
        "current_implied_move": market_implied_move,
        "avg_actual_move": round(avg_actual, 2),
    }


# ---------------------------------------------------------------------------
# Core scoring functions
# ---------------------------------------------------------------------------

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
    
    Key rule: NEVER recommend BUY if we think earnings will be missed.
    That's a contradiction — you don't buy into an expected miss.
    """
    if mode == "trader":
        if score >= 55 and direction_prob > 0.50 and risk_score < 75 and beat_prob > 0.45:
            return "buy"
        elif score < 35 or (direction_prob < 0.35 and risk_score > 60):
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
                      ticker: str, metrics: dict, iv_signal: dict) -> tuple[str, list[str]]:
    """Generate useful company context and key differentiators as reasons."""
    reasons = []

    # Company fundamentals context
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

    # IV signal — options market insight
    if iv_signal.get("current_implied_move") and iv_signal["current_implied_move"] > 0:
        implied = iv_signal["current_implied_move"]
        ratio = iv_signal.get("iv_vs_actual_ratio", 1.0)
        if ratio > 1.3:
            reasons.append(f"Options imply ±{implied:.1f}% move but stock historically moves MORE — underpriced risk")
        elif ratio < 0.7:
            reasons.append(f"Options imply ±{implied:.1f}% move but stock usually moves less — overpriced vol")
        else:
            reasons.append(f"Options market pricing ±{implied:.1f}% earnings move")

    # Valuation context
    if pe > 50:
        reasons.append(f"Premium valuation (PE {pe:.0f}x) — market expects strong growth")
    elif pe > 0 and pe < 12:
        reasons.append(f"Value territory (PE {pe:.0f}x) — low expectations to beat")

    # Earnings pattern (consistency signal)
    consecutive = features.get("consecutive_beats", 0)
    avg_mag = features.get("avg_beat_magnitude", 0)
    if consecutive >= 4 and avg_mag > 5:
        reasons.append(f"Beat consensus {consecutive} quarters in a row (avg +{avg_mag:.0f}%) — strong sandbagging pattern")
    elif consecutive >= 3:
        reasons.append(f"Beat estimates {consecutive} consecutive quarters — likely to beat again")
    elif consecutive >= 2 and avg_mag > 10:
        reasons.append(f"Beat by {avg_mag:.0f}% avg last {consecutive} quarters — analysts behind the curve")
    elif consecutive == 0:
        beat_rate = features.get("weighted_beat_rate", 0.5)
        if beat_rate < 0.3:
            reasons.append("Recent miss pattern — estimates may still be too high")

    # Estimate trend
    est_change = features.get("estimate_change_pct", 0)
    if est_change < -15:
        reasons.append("Analyst estimates cut significantly — low bar to beat")
    elif est_change > 15:
        reasons.append("Estimates revised up — high expectations priced in")

    # Analyst revision signal
    rev_signal = features.get("analyst_revision_signal", 0)
    if rev_signal >= 3:
        reasons.append("Multiple analyst upgrades recently — strong conviction")
    elif rev_signal <= -3:
        reasons.append("Multiple analyst downgrades recently — weakening outlook")

    # Insider activity
    insider = features.get("insider_signal", 0)
    if insider > 0.5:
        reasons.append("Insiders buying shares — management confidence")
    elif insider < -0.5:
        reasons.append("Insiders selling shares — potential caution signal")

    # Short interest context
    short_pct = features.get("short_interest_pct", 0)
    if short_pct > 15:
        reasons.append(f"High short interest ({short_pct:.0f}%) — squeeze potential on beat")
    elif short_pct > 8:
        reasons.append(f"Elevated short interest ({short_pct:.0f}%) — amplified move likely")

    # Build explanation text
    top_3 = reasons[:3]
    explanation = f"{ticker} earnings analysis:\n" + "\n".join(f"- {r}" for r in top_3)

    return explanation, top_3


# ---------------------------------------------------------------------------
# IMPROVEMENT 4: Feature snapshot storage for backtesting
# ---------------------------------------------------------------------------

def store_feature_snapshot(sb, prediction_id: int, features: dict,
                           iv_signal: dict, raw_ml_outputs: dict):
    """
    Store the complete feature vector alongside the prediction.
    This enables backtesting: we can later compare what we predicted
    vs what actually happened, with full context of WHY we predicted it.
    """
    snapshot = {
        "features": {k: float(v) if isinstance(v, (np.floating, np.integer)) else v
                     for k, v in features.items()},
        "iv_signal": iv_signal,
        "raw_ml": raw_ml_outputs,
        "snapshot_date": date.today().isoformat(),
    }

    try:
        headers = {
            "apikey": settings.supabase_service_key,
            "Authorization": f"Bearer {settings.supabase_service_key}",
            "Content-Type": "application/json",
        }
        url = f"{settings.supabase_url}/rest/v1/predictions?id=eq.{prediction_id}"
        import httpx as hx
        # Store snapshot in feature_importance JSON field (extend it)
        resp = hx.get(url, headers=headers)
        if resp.status_code == 200 and resp.json():
            existing = resp.json()[0].get("feature_importance", {}) or {}
            existing["feature_snapshot"] = snapshot
            hx.patch(url, json={"feature_importance": existing}, headers=headers)
    except Exception:
        pass  # Non-critical — don't fail prediction on snapshot storage error


# ---------------------------------------------------------------------------
# Main prediction function (refactored)
# ---------------------------------------------------------------------------

async def fetch_enrichment_data(client: httpx.AsyncClient, ticker: str,
                                stock_id: int, earnings: list) -> dict:
    """Fetch all enrichment data from external APIs."""
    sb = get_supabase()

    # Fetch Finnhub metrics
    metrics_data = await fetch_finnhub(client, "stock/metric", {"symbol": ticker, "metric": "all"})
    metrics = (metrics_data or {}).get("metric", {}) if isinstance(metrics_data, dict) else {}

    # Company profile
    profile = await fetch_finnhub(client, "stock/profile2", {"symbol": ticker})
    company_name = None
    if profile and isinstance(profile, dict) and profile.get("name"):
        company_name = profile["name"]
        # Update stock record with real name (fire and forget)
        try:
            existing_stock = sb.table("stocks").select("description").eq("id", stock_id).execute()
            has_description = existing_stock.data and existing_stock.data[0].get("description")

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

            if not has_description:
                # Try Wikipedia for description
                try:
                    wiki_resp = await client.get(
                        f"https://en.wikipedia.org/api/rest_v1/page/summary/{company_name.replace(' ', '_')}",
                        headers={"User-Agent": "EarningsEdge/1.0 (danielbaudy@gmail.com)"},
                    )
                    if wiki_resp.status_code == 200:
                        wiki_data = wiki_resp.json()
                        extract = wiki_data.get("extract", "")
                        if extract and len(extract) > 50 and ticker.lower() not in extract.lower().split("may refer to"):
                            update_data["description"] = extract[:500]
                except Exception:
                    pass

                # Fallback to Polygon
                if "description" not in update_data:
                    try:
                        await asyncio.sleep(13)
                        poly_resp = await client.get(
                            f"https://api.polygon.io/v3/reference/tickers/{ticker}",
                            params={"apiKey": settings.polygon_api_key},
                        )
                        if poly_resp.status_code == 200:
                            poly_data = poly_resp.json().get("results", {})
                            if poly_data.get("description"):
                                update_data["description"] = poly_data["description"][:500]
                    except Exception:
                        pass

            async with httpx.AsyncClient() as patch_client:
                await patch_client.patch(url, json=update_data, headers=headers)
        except Exception:
            pass

    # Short interest
    short_interest = 0
    try:
        si_data = await fetch_finnhub(client, "stock/short-interest",
                                      {"symbol": ticker, "from": "2026-01-01", "to": date.today().isoformat()})
        if si_data and isinstance(si_data, list) and si_data:
            latest_si = si_data[-1] if si_data else {}
            shares_short = latest_si.get("shortInterest", 0)
            shares_outstanding = metrics.get("shareOutstanding", 0) or 0
            if shares_outstanding > 0 and shares_short > 0:
                short_interest = (shares_short / (shares_outstanding * 1_000_000)) * 100
    except Exception:
        pass

    # Analyst revisions
    revision_signal = 0
    try:
        rec_data = await fetch_finnhub(client, "stock/recommendation", {"symbol": ticker})
        if rec_data and isinstance(rec_data, list) and len(rec_data) >= 2:
            current = rec_data[0]
            previous = rec_data[1]
            curr_buy = current.get("buy", 0) + current.get("strongBuy", 0)
            prev_buy = previous.get("buy", 0) + previous.get("strongBuy", 0)
            curr_sell = current.get("sell", 0) + current.get("strongSell", 0)
            prev_sell = previous.get("sell", 0) + previous.get("strongSell", 0)
            revision_signal = (curr_buy - prev_buy) - (curr_sell - prev_sell)
    except Exception:
        pass

    # Revenue beat rate
    revenue_beat_rate = 0.5
    try:
        rev_events = [e for e in earnings if e.get("revenue_actual") and e.get("revenue_estimate")]
        if rev_events:
            rev_beats = sum(1 for e in rev_events if e["revenue_actual"] > e["revenue_estimate"])
            revenue_beat_rate = rev_beats / len(rev_events)
    except Exception:
        pass

    # Insider transactions
    insider_signal = 0
    try:
        insider_data = await fetch_finnhub(client, "stock/insider-transactions", {"symbol": ticker})
        if insider_data and isinstance(insider_data, dict):
            transactions = insider_data.get("data", [])
            recent_buys = 0
            recent_sells = 0
            for txn in transactions[:20]:
                change = txn.get("change", 0)
                if change > 0:
                    recent_buys += 1
                elif change < 0:
                    recent_sells += 1
            if recent_buys + recent_sells > 0:
                insider_signal = (recent_buys - recent_sells) / (recent_buys + recent_sells)
    except Exception:
        pass

    return {
        "metrics": metrics,
        "company_name": company_name,
        "short_interest": min(short_interest, 50),
        "revision_signal": revision_signal,
        "revenue_beat_rate": revenue_beat_rate,
        "insider_signal": insider_signal,
    }


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

    # Build base features from earnings history
    dummy_current = {"eps_estimate": earnings[0].get("eps_estimate"), "report_date": date.today().isoformat()}
    full_list = [dummy_current] + earnings
    features = build_features_from_history(full_list, 0)
    if features is None:
        return None

    # --- IMPROVEMENT 1: Recency-weighted beat metrics + consistency ---
    features["weighted_beat_rate"] = recency_weighted_beat_rate(earnings)
    features["weighted_avg_surprise"] = recency_weighted_surprise(earnings)
    
    # Beat consistency: consecutive beats, magnitude, trend
    beat_consistency = compute_beat_consistency(earnings)
    features["consecutive_beats"] = beat_consistency["consecutive_beats"]
    features["avg_beat_magnitude"] = beat_consistency["avg_beat_magnitude"]
    features["beat_trend"] = beat_consistency["beat_trend"]
    features["beat_consistency_score"] = beat_consistency["consistency_score"]

    # Fetch enrichment data
    enrichment = await fetch_enrichment_data(client, ticker, stock_id, earnings)
    metrics = enrichment["metrics"]

    # Add enrichment features
    features["revenue_growth"] = metrics.get("revenueGrowthTTMYoy", 0) or 0
    features["eps_growth"] = metrics.get("epsGrowthTTMYoy", 0) or 0
    features["operating_margin"] = metrics.get("operatingMarginTTM", 0) or 0
    features["pe_ratio"] = metrics.get("peTTM", 0) or 0
    features["beta"] = metrics.get("beta", 1) or 1
    features["short_interest_pct"] = enrichment["short_interest"]
    features["analyst_revision_signal"] = enrichment["revision_signal"]
    features["revenue_beat_rate"] = enrichment["revenue_beat_rate"]
    features["insider_signal"] = enrichment["insider_signal"]
    features["sector_relative_perf"] = metrics.get("priceRelativeToS&P50013Week", 0) or 0

    # Momentum features
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

    # Earnings reaction patterns (used for MAGNITUDE only, not direction)
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

    # --- ML MODEL INFERENCE ---
    X = pd.DataFrame([features])
    for col in feature_names:
        if col not in X.columns:
            X[col] = 0
    X = X[feature_names].fillna(0).replace([np.inf, -np.inf], 0)

    beat_prob_raw = float(beat_model.predict_proba(X)[0][1])
    direction_prob_raw = float(direction_model.predict_proba(X)[0][1])
    raw_move = float(magnitude_model.predict(X)[0])

    # --- IMPROVEMENT 1: Blend ML beat prob with recency-weighted historical ---
    # ML model captures complex patterns, but recency-weighted history is a strong prior
    weighted_beat = features["weighted_beat_rate"]
    consistency = features["beat_consistency_score"]
    
    # Base blend: 60% ML + 40% historical
    beat_prob = beat_prob_raw * 0.6 + weighted_beat * 0.4
    
    # Consistency boost: if company has beaten 3+ quarters in a row with strong magnitude,
    # push beat_prob higher. This is the "sandbagging" signal — management consistently
    # guides low and delivers high. Very predictive.
    if features["consecutive_beats"] >= 4 and features["avg_beat_magnitude"] > 5:
        # Strong consistent beater — boost significantly
        beat_prob = beat_prob * 0.6 + 0.85 * 0.4
    elif features["consecutive_beats"] >= 3:
        # Good streak — moderate boost
        beat_prob = beat_prob * 0.7 + 0.75 * 0.3
    elif features["consecutive_beats"] >= 2 and features["avg_beat_magnitude"] > 10:
        # Short streak but big beats — moderate boost
        beat_prob = beat_prob * 0.75 + 0.70 * 0.25
    
    beat_prob = max(0.05, min(0.95, beat_prob))

    # --- IMPROVEMENT 2: Direction from current signals, not historical moves ---
    direction_prob = compute_direction_from_current_signals(
        features, direction_prob_raw, beat_prob, momentum_signal
    )

    # --- IMPROVEMENT 3: Get options-implied move ---
    market_implied_move = None
    try:
        from app.ingestion.options_iv import get_expected_move
        event_data = sb.table("earnings_events").select("report_date").eq("id", event_id).execute()
        earnings_date_str = event_data.data[0]["report_date"] if event_data.data else None
        iv_data = get_expected_move(ticker, earnings_date_str)
        if iv_data.get("available") and iv_data.get("expected_move_pct"):
            market_implied_move = iv_data["expected_move_pct"]
    except Exception:
        pass

    # Compute IV signal (historical implied vs actual comparison)
    iv_signal = compute_iv_signal(earnings, market_implied_move)

    # Store IV snapshot for future backtesting
    if market_implied_move and market_implied_move > 0:
        try:
            iv_snapshot_data = {
                "stock_id": stock_id,
                "earnings_event_id": event_id,
                "implied_move_pct": market_implied_move,
                "atm_iv": iv_data.get("atm_iv") if iv_data else None,
                "current_price": iv_data.get("current_price") if iv_data else None,
                "straddle_price": iv_data.get("straddle_price") if iv_data else None,
                "data_source": "marketdata_app",
            }
            sb.table("iv_snapshots").upsert(
                iv_snapshot_data, on_conflict="stock_id,earnings_event_id"
            )
        except Exception:
            pass  # Table might not exist yet, non-critical

    # --- EXPECTED MOVE CALCULATION ---
    # Use historical MAGNITUDE (absolute moves) — this is valid
    # Direction is handled separately above
    prior_moves = [e.get("price_change_pct", 0) for e in earnings if e.get("price_change_pct") is not None]

    if prior_moves and len(prior_moves) >= 2:
        avg_abs_move = float(np.mean([abs(m) for m in prior_moves]))
        volatility = float(np.std(prior_moves))
    else:
        beta = features.get("beta", 1)
        return_3m_std = metrics.get("3MonthADReturnStd", 0) or 0
        if return_3m_std > 0:
            daily_vol = return_3m_std / 100
            avg_abs_move = daily_vol * 2.5 * 100
        else:
            avg_abs_move = max(1.5, beta * 2.5)
        volatility = avg_abs_move * 1.2

    avg_abs_move = max(0.5, min(avg_abs_move, 20.0))

    # Blend with options-implied move if available
    if market_implied_move and market_implied_move > 0:
        if prior_moves and len(prior_moves) >= 2:
            historical_avg = float(np.mean([abs(m) for m in prior_moves]))
            if market_implied_move > historical_avg * 3:
                avg_abs_move = historical_avg * 0.6 + market_implied_move * 0.4
            elif market_implied_move > historical_avg * 2:
                avg_abs_move = historical_avg * 0.4 + market_implied_move * 0.6
            else:
                avg_abs_move = market_implied_move * 0.7 + avg_abs_move * 0.3
        else:
            avg_abs_move = market_implied_move * 0.75

    # Magnitude multiplier based on context (affects SIZE of move, not direction)
    magnitude_multiplier = 1.0

    # Oversold stocks snap back harder, overbought have muted upside
    if momentum_signal < -25:
        magnitude_multiplier = 1.5
    elif momentum_signal < -15:
        magnitude_multiplier = 1.3
    elif momentum_signal < -8:
        magnitude_multiplier = 1.1
    elif momentum_signal > 25:
        magnitude_multiplier = 0.8 if direction_prob > 0.5 else 1.3
    elif momentum_signal > 15:
        magnitude_multiplier = 0.85 if direction_prob > 0.5 else 1.2

    # Beta scaling
    beta = features.get("beta", 1)
    if beta > 1.5:
        magnitude_multiplier *= 1.15
    elif beta < 0.7:
        magnitude_multiplier *= 0.85

    # Short interest amplification
    short_pct = features.get("short_interest_pct", 0)
    if short_pct > 20:
        magnitude_multiplier *= 1.3
    elif short_pct > 10:
        magnitude_multiplier *= 1.15
    elif short_pct > 5:
        magnitude_multiplier *= 1.05

    # IV signal: if stock historically moves more than implied, scale up
    iv_ratio = iv_signal.get("iv_vs_actual_ratio", 1.0)
    if iv_ratio > 1.5:
        magnitude_multiplier *= 1.2
    elif iv_ratio > 1.2:
        magnitude_multiplier *= 1.1
    elif iv_ratio < 0.6:
        magnitude_multiplier *= 0.8

    avg_abs_move *= magnitude_multiplier

    # Expected move = the actual expected jump size in the predicted direction.
    # This is INDEPENDENT of certainty — the probability (shown separately)
    # tells you how confident we are. The move tells you "if it goes that way,
    # how big is the jump likely to be?"
    if direction_prob >= 0.5:
        # We think it goes up — show the expected upside magnitude
        expected_move = avg_abs_move
    else:
        # We think it goes down — show the expected downside magnitude
        expected_move = -avg_abs_move

    expected_move = round(expected_move, 1)

    # --- T+3 PREDICTION ---
    # T+3 captures delayed reactions (conference call digestion, analyst revisions)
    # T+3 direction tends to:
    # - Amplify T+1 if fundamentals are strong (beat + good guidance)
    # - Reverse T+1 if the initial reaction was emotional (gap fill)
    # Key insight: T+3 is more influenced by fundamentals and less by momentum
    
    # T+3 direction: more weight on fundamentals, less on short-term momentum
    fundamentals_strength = min(max((features.get("revenue_growth", 0) + 10) / 40, 0), 1)
    
    # If beat probability is high AND fundamentals are strong, T+3 tends to continue up
    # If beat probability is low OR fundamentals weak, T+3 may reverse or fade
    t3_beat_influence = 0.35 + beat_prob * 0.35
    t3_fundamentals = 0.35 + fundamentals_strength * 0.30
    t3_momentum = 0.5 + (features.get("momentum_13w", 0) / 80)  # Longer-term trend matters more for T+3
    t3_analyst = 0.5
    rev_signal = features.get("analyst_revision_signal", 0)
    if rev_signal >= 2:
        t3_analyst = 0.65
    elif rev_signal <= -2:
        t3_analyst = 0.35

    direction_prob_t3 = (
        t3_beat_influence * 0.30 +
        t3_fundamentals * 0.25 +
        t3_momentum * 0.25 +
        t3_analyst * 0.20
    )
    direction_prob_t3 = max(0.15, min(0.85, direction_prob_t3))

    # T+3 magnitude: typically slightly larger than T+1 (continuation or reversal)
    # Historical data shows T+3 moves are ~1.2-1.5x T+1 on average
    t3_magnitude_factor = 1.3
    if direction_prob_t3 >= 0.5:
        expected_move_t3 = avg_abs_move * t3_magnitude_factor
    else:
        expected_move_t3 = -avg_abs_move * t3_magnitude_factor
    expected_move_t3 = round(expected_move_t3, 1)

    # Risk score
    risk_score = calculate_risk_score(beat_prob, direction_prob, expected_move, volatility, beta)

    # --- TOTAL SCORE ---
    # Current signals (40%) + Beat probability (20%) + Direction (20%) +
    # Fundamentals (10%) + Low risk bonus (10%)
    risk_bonus = (100 - risk_score) / 100

    # Current signals composite
    signals_bonus = 0.5
    insider = features.get("insider_signal", 0)
    if rev_signal > 0:
        signals_bonus += min(rev_signal * 0.05, 0.2)
    elif rev_signal < 0:
        signals_bonus -= min(abs(rev_signal) * 0.05, 0.2)
    if insider > 0.3:
        signals_bonus += 0.15
    elif insider < -0.3:
        signals_bonus -= 0.1
    if momentum_signal > 15:
        signals_bonus += 0.1
    elif momentum_signal < -15:
        signals_bonus -= 0.15
    signals_bonus = max(0.1, min(0.9, signals_bonus))

    total_score = int(
        signals_bonus * 40 +
        beat_prob * 20 +
        direction_prob * 20 +
        fundamentals_strength * 10 +
        risk_bonus * 10
    )
    total_score = max(5, min(95, total_score))

    # Recommendation
    recommendation = generate_recommendation(total_score, mode, risk_score, beat_prob, direction_prob)

    # Explanation (now includes IV signal)
    explanation, top_3_reasons = build_explanation(
        features, beat_prob, direction_prob, expected_move, risk_score, mode, ticker, metrics, iv_signal
    )

    # Raw ML outputs for snapshot storage
    raw_ml_outputs = {
        "beat_prob_raw": round(beat_prob_raw, 4),
        "direction_prob_raw": round(direction_prob_raw, 4),
        "raw_move": round(raw_move, 2),
        "weighted_beat_rate": round(weighted_beat, 3),
        "beat_consistency": {
            "consecutive_beats": features["consecutive_beats"],
            "avg_beat_magnitude": features["avg_beat_magnitude"],
            "beat_trend": features["beat_trend"],
            "consistency_score": features["beat_consistency_score"],
        },
        "direction_prob_final": round(direction_prob, 4),
        "direction_prob_t3": round(direction_prob_t3, 4),
        "beat_prob_final": round(beat_prob, 4),
        "momentum_signal": round(momentum_signal, 2),
        "magnitude_multiplier": round(magnitude_multiplier, 2),
        "avg_abs_move": round(avg_abs_move, 2),
    }

    result = {
        "stock_id": stock_id,
        "earnings_event_id": event_id,
        "model_version": "xgboost_v3",
        "recommendation": recommendation,
        "confidence_score": total_score / 100,
        "beat_probability": round(beat_prob, 3),
        "miss_probability": round(1 - beat_prob, 3),
        # T+1 (primary — next trading day reaction)
        "price_up_probability": round(direction_prob, 3),
        "price_down_probability": round(1 - direction_prob, 3),
        "expected_move_pct": round(expected_move, 2),
        # T+3 and implied move stored in feature_importance JSON
        # (until schema migration is run, these can't be top-level columns)
        "expected_volatility": round(volatility, 2),
        "predicted_direction": "up" if direction_prob > 0.5 else "down",
        "feature_importance": {
            "total_score": total_score,
            "risk_score": risk_score,
            "top_reasons": top_3_reasons,
            "mode": mode,
            "iv_signal": iv_signal,
            "raw_ml": raw_ml_outputs,
            # T+1 / T+3 split data
            "t1": {
                "direction_prob": round(direction_prob, 3),
                "expected_move_pct": round(expected_move, 2),
            },
            "t3": {
                "direction_prob": round(direction_prob_t3, 3),
                "expected_move_pct": round(expected_move_t3, 2),
            },
            "implied_move_pct": round(market_implied_move, 2) if market_implied_move else None,
        },
        "explanation_text": explanation,
    }

    return result


async def generate_all_ml_predictions(mode: str = "trader"):
    """Generate ML predictions for all upcoming earnings."""
    print(f"🤖 Generating XGBoost predictions v2 (mode: {mode})...\n")
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
                  f"Beat:{pred['beat_probability']:.0%} Up:{pred['price_up_probability']:.0%} "
                  f"Move:{pred['expected_move_pct']:+.1f}%")

            # Store feature snapshot for backtesting
            # (non-blocking, best-effort)
            try:
                store_feature_snapshot(
                    sb, pred.get("id"), 
                    {"momentum_signal": pred["feature_importance"]["raw_ml"]["momentum_signal"]},
                    pred["feature_importance"].get("iv_signal", {}),
                    pred["feature_importance"]["raw_ml"],
                )
            except Exception:
                pass

        except Exception as e:
            print(f"  ❌ {ticker}: {e}")

        await asyncio.sleep(1.5)  # Finnhub rate limit

    await client.aclose()
    print(f"\n✅ Generated {generated} ML predictions (v2)")


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "trader"
    asyncio.run(generate_all_ml_predictions(mode))
