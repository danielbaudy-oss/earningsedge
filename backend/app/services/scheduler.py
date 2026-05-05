"""Scheduled tasks: daily retraining, data ingestion, alert sending."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.config import get_settings
import structlog

logger = structlog.get_logger()
settings = get_settings()

scheduler = AsyncIOScheduler()


async def daily_retrain():
    """Retrain model daily with latest outcomes (feedback loop)."""
    from app.ml.train import train_model
    try:
        logger.info("daily_retrain_started")
        metrics = train_model()
        logger.info("daily_retrain_complete", metrics=metrics)
    except Exception as e:
        logger.error("daily_retrain_failed", error=str(e))


async def ingest_earnings_calendar():
    """Fetch upcoming earnings calendar daily."""
    from app.ingestion.finnhub_client import FinnhubClient
    from datetime import date, timedelta

    try:
        client = FinnhubClient()
        today = date.today()
        calendar = await client.get_earnings_calendar(
            today, today + timedelta(days=30)
        )
        logger.info("earnings_calendar_ingested", count=len(calendar))
        await client.close()
    except Exception as e:
        logger.error("earnings_ingestion_failed", error=str(e))


async def update_outcomes():
    """Update actual outcomes for past earnings events."""
    logger.info("outcome_update_started")
    # Fetch actual EPS and price movements for recent earnings
    # This feeds the feedback loop for model retraining


async def send_alerts():
    """Send alerts for upcoming earnings."""
    logger.info("alert_check_started")
    # Check for earnings happening within alert windows
    # Send email notifications


def setup_scheduler():
    """Configure and start the scheduler."""
    # Daily model retraining at configured hour
    scheduler.add_job(
        daily_retrain,
        CronTrigger(hour=settings.retrain_hour, minute=0),
        id="daily_retrain",
        name="Daily Model Retrain",
    )

    # Earnings calendar update every 6 hours
    scheduler.add_job(
        ingest_earnings_calendar,
        CronTrigger(hour="*/6", minute=15),
        id="ingest_calendar",
        name="Ingest Earnings Calendar",
    )

    # Update outcomes every 2 hours during market hours
    scheduler.add_job(
        update_outcomes,
        CronTrigger(hour="10-18", minute=30),
        id="update_outcomes",
        name="Update Earnings Outcomes",
    )

    # Check alerts daily at 8am
    scheduler.add_job(
        send_alerts,
        CronTrigger(hour=8, minute=0),
        id="send_alerts",
        name="Send Earnings Alerts",
    )

    scheduler.start()
    logger.info("scheduler_started")
