"""
Daily scheduled job — runs once per day.

1. Sync earnings calendar (next 7 days)
2. Update outcomes for past predictions (feedback loop)
3. Batch analyze stocks reporting this week
4. Retrain model if enough new outcomes accumulated
"""

import asyncio
from datetime import date
from app.ingestion.sync_calendar import sync_earnings_calendar
from app.services.feedback_loop import update_prediction_outcomes, get_model_accuracy, should_retrain
from app.ml.batch_analyze_week import batch_analyze
from app.ml.train_xgboost import main as train_model
import structlog

logger = structlog.get_logger()


async def run_daily_job():
    """Full daily pipeline."""
    print("=" * 60)
    print(f"🕐 Daily Job — {date.today().isoformat()}")
    print("=" * 60)

    # Step 1: Sync calendar
    print("\n📅 Step 1: Syncing earnings calendar...")
    try:
        await sync_earnings_calendar(7)
    except Exception as e:
        print(f"  ⚠️ Calendar sync failed: {e}")

    # Step 2: Update outcomes (feedback loop)
    print("\n🔄 Step 2: Updating prediction outcomes...")
    try:
        updated = await update_prediction_outcomes()
        print(f"  Updated {updated} outcomes")
    except Exception as e:
        print(f"  ⚠️ Outcome update failed: {e}")

    # Step 3: Check if retraining is needed
    print("\n📊 Step 3: Checking model accuracy...")
    try:
        metrics = await get_model_accuracy()
        print(f"  Predictions with outcomes: {metrics.get('predictions_with_outcomes', 0)}")
        print(f"  Recommendation accuracy: {metrics.get('recommendation_accuracy', 0):.1%}")
        print(f"  Direction accuracy: {metrics.get('direction_accuracy', 0):.1%}")
        print(f"  Avg move error: {metrics.get('avg_move_error_pct', 0):.2f}%")

        if metrics.get("needs_retraining"):
            print("\n🤖 Step 3b: Retraining model (enough new data)...")
            try:
                await train_model()
                print("  ✅ Model retrained!")
            except Exception as e:
                print(f"  ⚠️ Retraining failed: {e}")
        else:
            print(f"  Model OK — retraining after 20+ outcomes")
    except Exception as e:
        print(f"  ⚠️ Accuracy check failed: {e}")

    # Step 4: Batch analyze this week
    print("\n🤖 Step 4: Analyzing stocks reporting this week...")
    try:
        await batch_analyze()
    except Exception as e:
        print(f"  ⚠️ Batch analysis failed: {e}")

    print("\n" + "=" * 60)
    print("✅ Daily job complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_daily_job())
