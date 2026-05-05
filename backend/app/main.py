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
    allow_origins=["http://localhost:3000"],
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
