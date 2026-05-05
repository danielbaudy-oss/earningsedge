"""Generate predictions for upcoming earnings using available data.

Since we don't have enough training data for a full XGBoost model yet,
this uses a rule-based scoring system based on earnings history patterns
until the model has enough data to train properly.
"""

import asyncio
from datetime import date
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

settings = get_settings()


def calculate_prediction(history: list, ticker: str) -> dict:
    """
    Generate a prediction based on earnings history patterns.

    Factors:
    - Beat rate (how often they beat estimates)
    - Surprise consistency (stable beats = higher confidence)
    - Surprise magnitude (bigger beats = more bullish)
    """
    if not history:
        return {
            "recommendation": "avoid",
            "confidence_score": 0.3,
            "beat_probability": 0.5,
            "miss_probability": 0.5,
            "price_up_probability": 0.5,
            "price_down_probability": 0.5,
            "expected_move_pct": 0.0,
            "expected_volatility": 5.0,
            "predicted_direction": "neutral",
            "explanation_text": f"Insufficient historical data for {ticker}. Recommending caution.",
            "feature_importance": {"data_availability": -0.5},
        }

    # Calculate metrics from history
    beats = [h for h in history if (h.get("eps_surprise_pct") or 0) > 0]
    beat_rate = len(beats) / len(history)

    surprises = [h.get("eps_surprise_pct") or 0 for h in history]
    avg_surprise = sum(surprises) / len(surprises) if surprises else 0

    # Trend: are recent surprises getting better or worse?
    if len(surprises) >= 2:
        recent = sum(surprises[:2]) / 2
        older = sum(surprises[2:]) / max(len(surprises[2:]), 1)
        trend = recent - older
    else:
        trend = 0

    # Beat probability
    beat_prob = min(max(beat_rate * 0.7 + (avg_surprise > 0) * 0.2 + (trend > 0) * 0.1, 0.1), 0.95)
    miss_prob = 1 - beat_prob

    # Direction probability (correlated with beat but not identical)
    price_up_prob = beat_prob * 0.8 + 0.1  # Slight discount — beating doesn't always mean stock goes up
    price_down_prob = 1 - price_up_prob

    # Expected move
    abs_moves = [abs(s) for s in surprises]
    avg_abs_move = sum(abs_moves) / len(abs_moves) if abs_moves else 3.0
    expected_move = avg_surprise * 0.5  # Dampened
    expected_vol = avg_abs_move * 1.5

    # Confidence
    consistency = 1 - (max(surprises) - min(surprises)) / max(abs(max(surprises)), abs(min(surprises)), 1)
    confidence = min(max(
        beat_rate * 0.4 + abs(beat_prob - 0.5) * 0.8 + consistency * 0.2,
        0.15
    ), 0.92)

    # Recommendation
    if beat_prob > 0.65 and price_up_prob > 0.6 and expected_move > 1.0:
        recommendation = "buy"
    elif beat_prob < 0.4 and price_up_prob < 0.45:
        recommendation = "sell"
    else:
        recommendation = "avoid"

    # Explanation
    lines = []
    if beat_prob > 0.6:
        lines.append(f"{ticker} has beaten estimates {beat_rate:.0%} of the time.")
    elif beat_prob < 0.4:
        lines.append(f"{ticker} has missed estimates frequently ({1-beat_rate:.0%} miss rate).")
    else:
        lines.append(f"{ticker} has a mixed earnings track record ({beat_rate:.0%} beat rate).")

    if trend > 2:
        lines.append("Recent earnings surprises are trending upward.")
    elif trend < -2:
        lines.append("Recent earnings surprises are trending downward.")

    if avg_surprise > 3:
        lines.append(f"Average surprise of +{avg_surprise:.1f}% suggests consistent outperformance.")
    elif avg_surprise < -2:
        lines.append(f"Average surprise of {avg_surprise:.1f}% indicates underperformance risk.")

    lines.append(f"Expected move: {expected_move:+.1f}% with {expected_vol:.1f}% volatility.")

    return {
        "recommendation": recommendation,
        "confidence_score": round(confidence, 3),
        "beat_probability": round(beat_prob, 3),
        "miss_probability": round(miss_prob, 3),
        "price_up_probability": round(price_up_prob, 3),
        "price_down_probability": round(price_down_prob, 3),
        "expected_move_pct": round(expected_move, 2),
        "expected_volatility": round(expected_vol, 2),
        "predicted_direction": "up" if price_up_prob > 0.5 else "down",
        "explanation_text": "\n".join(lines),
        "feature_importance": {
            "beat_rate": round(beat_rate, 3),
            "avg_surprise": round(avg_surprise, 3),
            "trend": round(trend, 3),
            "consistency": round(consistency, 3),
        },
    }


async def generate_all_predictions():
    """Generate predictions for all upcoming earnings events."""
    print("🤖 Generating predictions for upcoming earnings...\n")
    sb = get_supabase()

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

    generated = 0
    for event in upcoming.data:
        stock = event.get("stocks") or {}
        ticker = stock.get("ticker", "???")
        stock_id = event["stock_id"]

        # Get earnings history for this stock
        history = (
            sb.table("earnings_events")
            .select("eps_surprise_pct, price_change_pct, report_date")
            .eq("stock_id", stock_id)
            .lte("report_date", today)
            .order("report_date", desc=True)
            .limit(8)
            .execute()
        )

        # Generate prediction
        pred = calculate_prediction(history.data, ticker)

        # Store prediction
        pred_data = {
            "stock_id": stock_id,
            "earnings_event_id": event["id"],
            "model_version": "rules_v1",
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
            sb.table("predictions").insert(pred_data)
            generated += 1
            emoji = {"buy": "🟢", "sell": "🔴", "avoid": "🟡"}[pred["recommendation"]]
            print(f"  {emoji} {ticker}: {pred['recommendation'].upper()} "
                  f"(conf: {pred['confidence_score']:.0%}, beat: {pred['beat_probability']:.0%})")
        except Exception as e:
            print(f"  ❌ {ticker}: {e}")

    print(f"\n✅ Generated {generated} predictions")


if __name__ == "__main__":
    asyncio.run(generate_all_predictions())
