"""EarningsEdge FastAPI Application."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.api import stocks, earnings, predictions, alerts

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="AI-powered stock earnings prediction platform",
    version="1.0.0",
)

# CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://earningsedge.vercel.app",
        "https://earningsedge-three.vercel.app",
        "https://earningsedge-pnc9.onrender.com",
        "https://*.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(stocks.router, prefix="/api/stocks", tags=["stocks"])
app.include_router(earnings.router, prefix="/api/earnings", tags=["earnings"])
app.include_router(predictions.router, prefix="/api/predictions", tags=["predictions"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["alerts"])


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": settings.app_name}


@app.post("/api/cron/daily")
async def trigger_daily_job(background_tasks: "BackgroundTasks"):
    """
    Trigger the daily job (calendar sync + feedback loop + retrain + analyze).
    Call this via external cron (cron-job.org) at 6:00 AM UTC daily.
    """
    from fastapi import BackgroundTasks
    from app.services.daily_job import run_daily_job
    import asyncio

    # Run in background so the endpoint returns immediately
    asyncio.create_task(run_daily_job())
    return {"status": "started", "message": "Daily job triggered"}


@app.get("/api/model/accuracy")
async def get_model_accuracy_endpoint():
    """Get current model accuracy metrics (feedback loop)."""
    from app.services.feedback_loop import get_model_accuracy
    return await get_model_accuracy()


@app.get("/api/model/errors")
async def get_prediction_errors():
    """Get recent prediction errors for transparency."""
    from app.db.supabase_client import get_supabase
    sb = get_supabase()

    results = (
        sb.table("predictions")
        .select("recommendation, prediction_correct, beat_probability, "
                "actual_outcome, actual_move_pct, expected_move_pct, "
                "price_up_probability, confidence_score, "
                "stocks(ticker), earnings_events(report_date)")
        .order("prediction_date", desc=True)
        .limit(50)
        .execute()
    )

    with_outcomes = [p for p in results.data if p.get("actual_outcome")]

    errors = []
    for p in with_outcomes[:20]:
        stock = p.get("stocks") or {}
        event = p.get("earnings_events") or {}
        errors.append({
            "ticker": stock.get("ticker"),
            "date": event.get("report_date"),
            "predicted": p.get("recommendation"),
            "correct": p.get("prediction_correct"),
            "beat_predicted": f"{(p.get('beat_probability', 0) * 100):.0f}%",
            "actual_outcome": p.get("actual_outcome"),
            "expected_move": f"{p.get('expected_move_pct', 0):+.1f}%",
            "actual_move": f"{p.get('actual_move_pct', 0):+.1f}%",
        })

    return {
        "recent_predictions": errors,
        "total_with_outcomes": len(with_outcomes),
    }
