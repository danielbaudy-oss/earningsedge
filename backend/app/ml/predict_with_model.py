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
        # Check if we already have description stored
        existing_stock = sb.table("stocks").select("description").eq("id", stock_id).execute()
        has_description = existing_stock.data and existing_stock.data[0].get("description")

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

            # Only fetch description if we don't have one yet
            if not has_description:
                # Try Wikipedia first (free, no rate limit, good coverage)
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

                # Fallback to Polygon if Wikipedia didn't work
                if "description" not in update_data:
                    try:
                        import asyncio as _asyncio
                        await _asyncio.sleep(13)
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

            async with hx.AsyncClient() as patch_client:
                await patch_client.patch(url, json=update_data, headers=headers)
        except Exception:
            pass

    features["revenue_growth"] = metrics.get("revenueGrowthTTMYoy", 0) or 0
    features["eps_growth"] = metrics.get("epsGrowthTTMYoy", 0) or 0
    features["operating_margin"] = metrics.get("operatingMarginTTM", 0) or 0
    features["pe_ratio"] = metrics.get("peTTM", 0) or 0
    features["beta"] = metrics.get("beta", 1) or 1

    # Short interest — high short interest + beat = potential squeeze
    short_interest = 0
    try:
        si_data = await fetch_finnhub(client, "stock/short-interest", {"symbol": ticker, "from": "2026-01-01", "to": date.today().isoformat()})
        if si_data and isinstance(si_data, list) and si_data:
            # Get most recent short interest as % of float
            latest_si = si_data[-1] if si_data else {}
            shares_short = latest_si.get("shortInterest", 0)
            # Finnhub gives absolute shares short, we need % — estimate from market cap
            shares_outstanding = metrics.get("shareOutstanding", 0) or 0
            if shares_outstanding > 0 and shares_short > 0:
                short_interest = (shares_short / (shares_outstanding * 1_000_000)) * 100
    except Exception:
        pass
    features["short_interest_pct"] = min(short_interest, 50)  # Cap at 50%

    # --- HIGH IMPACT INDICATOR 1: Analyst Estimate Revisions ---
    # If analysts raised estimates recently, company likely beats
    revision_signal = 0
    try:
        rec_data = await fetch_finnhub(client, "stock/recommendation", {"symbol": ticker})
        if rec_data and isinstance(rec_data, list) and len(rec_data) >= 2:
            current = rec_data[0]
            previous = rec_data[1]
            # Count upgrades vs downgrades
            curr_buy = current.get("buy", 0) + current.get("strongBuy", 0)
            prev_buy = previous.get("buy", 0) + previous.get("strongBuy", 0)
            curr_sell = current.get("sell", 0) + current.get("strongSell", 0)
            prev_sell = previous.get("sell", 0) + previous.get("strongSell", 0)
            # Net revision direction
            revision_signal = (curr_buy - prev_buy) - (curr_sell - prev_sell)
    except Exception:
        pass
    features["analyst_revision_signal"] = revision_signal

    # --- HIGH IMPACT INDICATOR 2: Revenue Surprise History ---
    # Companies that beat on revenue AND EPS have stronger reactions
    revenue_beat_rate = 0.5
    try:
        # Check if earnings events have revenue data
        rev_events = [e for e in earnings if e.get("revenue_actual") and e.get("revenue_estimate")]
        if rev_events:
            rev_beats = sum(1 for e in rev_events if e["revenue_actual"] > e["revenue_estimate"])
            revenue_beat_rate = rev_beats / len(rev_events)
    except Exception:
        pass
    features["revenue_beat_rate"] = revenue_beat_rate

    # --- HIGH IMPACT INDICATOR 3: Insider Transactions ---
    # Net insider buying before earnings = bullish signal
    insider_signal = 0
    try:
        insider_data = await fetch_finnhub(client, "stock/insider-transactions", {"symbol": ticker})
        if insider_data and isinstance(insider_data, dict):
            transactions = insider_data.get("data", [])
            # Look at last 90 days of insider activity
            recent_buys = 0
            recent_sells = 0
            for txn in transactions[:20]:  # Last 20 transactions
                change = txn.get("change", 0)
                if change > 0:
                    recent_buys += 1
                elif change < 0:
                    recent_sells += 1
            if recent_buys + recent_sells > 0:
                insider_signal = (recent_buys - recent_sells) / (recent_buys + recent_sells)
    except Exception:
        pass
    features["insider_signal"] = insider_signal  # -1 (all selling) to +1 (all buying)

    # --- HIGH IMPACT INDICATOR 4: Sector Peer Performance ---
    # If peers in same sector already beat, this stock likely will too
    # Use the stock's sector return relative to S&P 500 as proxy
    features["sector_relative_perf"] = metrics.get("priceRelativeToS&P50013Week", 0) or 0

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

    # --- SANITY CHECK: beat probability should influence direction ---
    # If likely to miss earnings, stock is unlikely to go up (regardless of momentum)
    # If likely to beat, that supports upward direction
    if beat_prob < 0.35 and direction_prob > 0.6:
        # Strong contradiction: likely miss but model says up — cap direction
        direction_prob = min(direction_prob, 0.35 + beat_prob * 0.5)
    elif beat_prob < 0.45 and direction_prob > 0.7:
        # Mild contradiction
        direction_prob = min(direction_prob, 0.45 + beat_prob * 0.4)
    elif beat_prob > 0.75 and direction_prob < 0.4:
        # Likely beat but model says down — slight boost
        direction_prob = max(direction_prob, 0.3 + beat_prob * 0.2)

    # Adjust expected move: use stock-specific volatility, not a flat default
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

    # Cap at reasonable bounds
    avg_abs_move = max(0.5, min(avg_abs_move, 20.0))

    # --- TRY TO GET MARKET-IMPLIED EXPECTED MOVE FROM OPTIONS ---
    # This is the gold standard — what the options market actually prices in
    market_implied_move = None
    try:
        from app.ingestion.options_iv import get_expected_move
        # Find earnings date for this event
        event_data = sb.table("earnings_events").select("report_date").eq("id", event_id).execute()
        earnings_date_str = event_data.data[0]["report_date"] if event_data.data else None
        iv_data = get_expected_move(ticker, earnings_date_str)
        if iv_data.get("available") and iv_data.get("expected_move_pct"):
            market_implied_move = iv_data["expected_move_pct"]
    except Exception:
        pass

    # If we have market-implied move, blend it with our estimate
    if market_implied_move and market_implied_move > 0:
        # Reality check: if options-implied move is much larger than historical,
        # the options might be illiquid (wide spreads inflate the straddle)
        # Blend more toward historical when there's a big discrepancy
        if prior_moves and len(prior_moves) >= 2:
            historical_avg = float(np.mean([abs(m) for m in prior_moves]))
            if market_implied_move > historical_avg * 3:
                # Options likely illiquid — trust historical more
                avg_abs_move = historical_avg * 0.6 + market_implied_move * 0.4
            elif market_implied_move > historical_avg * 2:
                # Moderate discrepancy — balanced blend
                avg_abs_move = historical_avg * 0.4 + market_implied_move * 0.6
            else:
                # Reasonable agreement — trust options more
                avg_abs_move = market_implied_move * 0.7 + avg_abs_move * 0.3
        else:
            # No historical data — use options but dampen slightly
            avg_abs_move = market_implied_move * 0.75

    # --- MAGNITUDE ADJUSTMENT BASED ON CURRENT BEHAVIOR ---
    # Stocks that have sold off hard may snap back bigger on a beat
    # Stocks that have run up may have muted upside (already priced in)
    magnitude_multiplier = 1.0

    if momentum_signal < -25:
        # Heavily oversold — potential for big snap-back on beat, or continued drop on miss
        magnitude_multiplier = 1.6
    elif momentum_signal < -15:
        # Significant downtrend — amplified reaction expected
        magnitude_multiplier = 1.35
    elif momentum_signal < -8:
        # Moderate downtrend — slightly bigger moves
        magnitude_multiplier = 1.15
    elif momentum_signal > 25:
        # Heavily overbought — upside may be priced in, but downside risk is bigger
        if direction_prob > 0.5:
            magnitude_multiplier = 0.7  # Muted upside
        else:
            magnitude_multiplier = 1.4  # Amplified downside
    elif momentum_signal > 15:
        # Strong uptrend — less room to run up, more room to fall
        if direction_prob > 0.5:
            magnitude_multiplier = 0.8
        else:
            magnitude_multiplier = 1.25
    elif momentum_signal > 8:
        if direction_prob > 0.5:
            magnitude_multiplier = 0.9
        else:
            magnitude_multiplier = 1.1

    # Apply beta scaling — high beta stocks move more
    beta = features.get("beta", 1)
    if beta > 1.5:
        magnitude_multiplier *= 1.15
    elif beta < 0.7:
        magnitude_multiplier *= 0.85

    # Apply short interest scaling — high short interest amplifies moves
    short_pct = features.get("short_interest_pct", 0)
    if short_pct > 20:
        # Very high short interest — potential squeeze on beat, crash on miss
        magnitude_multiplier *= 1.3
    elif short_pct > 10:
        magnitude_multiplier *= 1.15
    elif short_pct > 5:
        magnitude_multiplier *= 1.05

    avg_abs_move *= magnitude_multiplier

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
    # Weighted: beat_prob (25%) + direction_prob (25%) + fundamentals (15%) + low_risk (15%) + signals (20%)
    fundamentals_signal = min(max((features.get("revenue_growth", 0) + 10) / 40, 0), 1)
    risk_bonus = (100 - risk_score) / 100

    # New signals bonus (analyst revisions + insider buying)
    signals_bonus = 0.5  # Neutral baseline
    rev_signal = features.get("analyst_revision_signal", 0)
    insider = features.get("insider_signal", 0)
    if rev_signal > 0:
        signals_bonus += min(rev_signal * 0.05, 0.2)
    elif rev_signal < 0:
        signals_bonus -= min(abs(rev_signal) * 0.05, 0.2)
    if insider > 0.3:
        signals_bonus += 0.15
    elif insider < -0.3:
        signals_bonus -= 0.1
    signals_bonus = max(0.1, min(0.9, signals_bonus))

    total_score = int(
        beat_prob * 25 +
        direction_prob * 25 +
        fundamentals_signal * 15 +
        risk_bonus * 15 +
        signals_bonus * 20
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
