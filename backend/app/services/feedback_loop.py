"""
Feedback Learning System

Tracks predictions vs actual outcomes and stores error metrics
for continuous model improvement.

Daily workflow:
1. Check for earnings that have reported since last check
2. Fetch actual EPS and post-earnings price move
3. Compare to our prediction
4. Store prediction accuracy metrics
5. When enough new data accumulates, trigger retraining
"""

import asyncio
import httpx
from datetime import date, timedelta
from app.core.config import get_settings
from app.db.supabase_client import get_supabase

settings = get_settings()


async def update_prediction_outcomes():
    """
    Check recent earnings and update predictions with actual outcomes.
    This is the core of the feedback loop.
    """
    print("🔄 Feedback Loop: Checking prediction outcomes...\n")
    sb = get_supabase()

    # Get predictions that don't have outcomes yet
    # where the earnings date has passed
    today = date.today().isoformat()

    headers = {
        "apikey": settings.supabase_service_key,
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    # Find predictions needing outcome updates
    predictions = (
        sb.table("predictions")
        .select("id, stock_id, earnings_event_id, recommendation, beat_probability, "
                "price_up_probability, expected_move_pct, "
                "earnings_events(report_date, eps_actual, eps_estimate, price_change_pct), "
                "stocks(ticker)")
        .execute()
    )

    updated = 0
    for pred in predictions.data:
        # Skip if already has outcome
        if pred.get("actual_outcome"):
            continue

        event = pred.get("earnings_events") or {}
        stock = pred.get("stocks") or {}
        ticker = stock.get("ticker", "?")

        # Skip if earnings haven't happened yet
        report_date = event.get("report_date")
        if not report_date or report_date >= today:
            continue

        # Skip if no actual data yet
        eps_actual = event.get("eps_actual")
        eps_estimate = event.get("eps_estimate")
        price_change = event.get("price_change_pct")

        if eps_actual is None:
            continue

        # Determine outcome
        if eps_estimate and eps_estimate != 0:
            beat = eps_actual > eps_estimate
            outcome = "beat" if beat else "miss"
        else:
            outcome = "unknown"

        # Determine if prediction was correct
        rec = pred.get("recommendation")
        prediction_correct = None
        if rec == "buy" and price_change is not None:
            prediction_correct = price_change > 0
        elif rec == "sell" and price_change is not None:
            prediction_correct = price_change < 0
        elif rec == "avoid" and price_change is not None:
            prediction_correct = abs(price_change) > 5  # Volatile = correct to avoid

        # Calculate prediction errors
        beat_prob = pred.get("beat_probability", 0.5)
        beat_error = abs((1 if outcome == "beat" else 0) - beat_prob)

        price_up_prob = pred.get("price_up_probability", 0.5)
        actual_up = 1 if (price_change or 0) > 0 else 0
        direction_error = abs(actual_up - price_up_prob)

        move_error = abs((pred.get("expected_move_pct") or 0) - (price_change or 0))

        # Update prediction record
        update_data = {
            "actual_outcome": outcome,
            "actual_move_pct": price_change,
            "prediction_correct": prediction_correct,
        }

        url = f"{settings.supabase_url}/rest/v1/predictions?id=eq.{pred['id']}"
        async with httpx.AsyncClient() as client:
            resp = await client.patch(url, json=update_data, headers=headers)

        if resp.status_code < 300:
            updated += 1
            correct_str = "✅" if prediction_correct else "❌"
            print(f"  {correct_str} {ticker}: predicted {rec}, "
                  f"actual {outcome} ({price_change:+.1f}% move), "
                  f"beat_error={beat_error:.2f}, dir_error={direction_error:.2f}")

    print(f"\n📊 Updated {updated} prediction outcomes")
    return updated


async def get_model_accuracy():
    """Calculate current model accuracy metrics from stored outcomes."""
    sb = get_supabase()

    # Get all predictions with outcomes
    results = (
        sb.table("predictions")
        .select("recommendation, prediction_correct, beat_probability, "
                "actual_outcome, actual_move_pct, expected_move_pct, "
                "price_up_probability, model_version")
        .execute()
    )

    predictions_with_outcomes = [p for p in results.data if p.get("actual_outcome")]

    if not predictions_with_outcomes:
        return {"status": "no_outcomes_yet", "total_predictions": len(results.data)}

    total = len(predictions_with_outcomes)
    correct = sum(1 for p in predictions_with_outcomes if p.get("prediction_correct"))

    # Beat prediction accuracy
    beat_predictions = [p for p in predictions_with_outcomes if p.get("actual_outcome") in ("beat", "miss")]
    beat_correct = sum(
        1 for p in beat_predictions
        if (p["beat_probability"] > 0.5 and p["actual_outcome"] == "beat") or
           (p["beat_probability"] <= 0.5 and p["actual_outcome"] == "miss")
    )

    # Direction accuracy
    direction_predictions = [p for p in predictions_with_outcomes if p.get("actual_move_pct") is not None]
    direction_correct = sum(
        1 for p in direction_predictions
        if (p["price_up_probability"] > 0.5 and p["actual_move_pct"] > 0) or
           (p["price_up_probability"] <= 0.5 and p["actual_move_pct"] <= 0)
    )

    # Average move prediction error
    move_errors = [
        abs((p.get("expected_move_pct") or 0) - (p.get("actual_move_pct") or 0))
        for p in direction_predictions
    ]

    return {
        "total_predictions": len(results.data),
        "predictions_with_outcomes": total,
        "recommendation_accuracy": correct / total if total > 0 else 0,
        "beat_prediction_accuracy": beat_correct / len(beat_predictions) if beat_predictions else 0,
        "direction_accuracy": direction_correct / len(direction_predictions) if direction_predictions else 0,
        "avg_move_error_pct": sum(move_errors) / len(move_errors) if move_errors else 0,
        "needs_retraining": total >= 20,  # Retrain after 20 outcomes
    }


async def should_retrain() -> bool:
    """Check if we have enough new outcomes to justify retraining."""
    metrics = await get_model_accuracy()
    return metrics.get("needs_retraining", False)


if __name__ == "__main__":
    async def main():
        await update_prediction_outcomes()
        metrics = await get_model_accuracy()
        print(f"\n📈 Model Performance:")
        for k, v in metrics.items():
            if isinstance(v, float):
                print(f"  {k}: {v:.2%}")
            else:
                print(f"  {k}: {v}")

    asyncio.run(main())
