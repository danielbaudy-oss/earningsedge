"""Service layer for generating and managing predictions."""

from datetime import date, datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import (
    Stock, EarningsEvent, Prediction, FinancialMetric,
    SentimentData, MacroIndicator, RecommendationEnum
)
from app.ml.model import EarningsPredictionModel
from app.ml.features import build_feature_vector
from app.ingestion.finnhub_client import FinnhubClient
from app.ingestion.polygon_client import PolygonClient
from app.ingestion.sentiment_client import NewsAPIClient, RedditClient
import structlog

logger = structlog.get_logger()


class PredictionService:
    """Orchestrates prediction generation for upcoming earnings."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.model = EarningsPredictionModel.load()

    async def generate_prediction(self, stock_id: int, event_id: int) -> Prediction:
        """Generate a prediction for a specific earnings event."""
        # Load stock and event
        stock = await self.db.get(Stock, stock_id)
        event = await self.db.get(EarningsEvent, event_id)

        if not stock or not event:
            raise ValueError("Stock or event not found")

        # Gather features
        features = await self._gather_features(stock, event)

        # Run model inference
        result = self.model.predict(features)

        # Store prediction
        prediction = Prediction(
            stock_id=stock.id,
            earnings_event_id=event.id,
            model_version=result["model_version"],
            recommendation=RecommendationEnum(result["recommendation"]),
            confidence_score=result["confidence_score"],
            beat_probability=result["beat_probability"],
            miss_probability=result["miss_probability"],
            price_up_probability=result["price_up_probability"],
            price_down_probability=result["price_down_probability"],
            expected_move_pct=result["expected_move_pct"],
            expected_volatility=result["expected_volatility"],
            predicted_direction=result["predicted_direction"],
            feature_importance=result["feature_importance"],
            explanation_text=result["explanation_text"],
        )
        self.db.add(prediction)
        await self.db.flush()

        logger.info(
            "prediction_generated",
            ticker=stock.ticker,
            recommendation=result["recommendation"],
            confidence=result["confidence_score"],
        )
        return prediction

    async def _gather_features(self, stock: Stock, event: EarningsEvent):
        """Gather all features needed for prediction."""
        # Financial metrics
        metrics_result = await self.db.execute(
            select(FinancialMetric)
            .where(
                FinancialMetric.stock_id == stock.id,
                FinancialMetric.period_date < event.report_date,
            )
            .order_by(FinancialMetric.period_date.desc())
            .limit(1)
        )
        metrics = metrics_result.scalar_one_or_none()

        financial_dict = {
            "revenue_growth_yoy": metrics.revenue_growth_yoy if metrics else 0,
            "eps_growth_yoy": metrics.eps_growth_yoy if metrics else 0,
            "revenue_growth_qoq": metrics.revenue_growth_qoq if metrics else 0,
            "gross_margin": metrics.gross_margin if metrics else 0,
            "operating_margin": metrics.operating_margin if metrics else 0,
            "net_margin": metrics.net_margin if metrics else 0,
            "pe_ratio": metrics.pe_ratio if metrics else 0,
            "forward_pe": metrics.forward_pe if metrics else 0,
            "ps_ratio": metrics.ps_ratio if metrics else 0,
            "debt_to_equity": metrics.debt_to_equity if metrics else 0,
        }

        # Earnings history
        history_result = await self.db.execute(
            select(EarningsEvent)
            .where(
                EarningsEvent.stock_id == stock.id,
                EarningsEvent.report_date < event.report_date,
                EarningsEvent.eps_actual.isnot(None),
            )
            .order_by(EarningsEvent.report_date.desc())
            .limit(8)
        )
        history = history_result.scalars().all()
        history_dicts = [
            {
                "eps_surprise_pct": h.eps_surprise_pct or 0,
                "price_change_pct": h.price_change_pct or 0,
            }
            for h in history
        ]

        # Sentiment
        sentiment_result = await self.db.execute(
            select(SentimentData)
            .where(SentimentData.stock_id == stock.id)
            .order_by(SentimentData.collected_at.desc())
            .limit(1)
        )
        sentiment_row = sentiment_result.scalar_one_or_none()
        sentiment_dict = {
            "news_sentiment": sentiment_row.sentiment_score if sentiment_row else 0,
            "reddit_sentiment": 0,
            "total_mentions": sentiment_row.total_mentions if sentiment_row else 0,
            "bullish_ratio": (
                sentiment_row.bullish_count / max(sentiment_row.total_mentions, 1)
                if sentiment_row else 0.5
            ),
        }

        # Macro
        macro_result = await self.db.execute(
            select(MacroIndicator)
            .order_by(MacroIndicator.indicator_date.desc())
            .limit(1)
        )
        macro_row = macro_result.scalar_one_or_none()
        macro_dict = {
            "vix": macro_row.vix if macro_row else 20,
            "sp500_return_30d": macro_row.sp500_return_30d if macro_row else 0,
            "treasury_10y": macro_row.treasury_10y if macro_row else 4.0,
            "sector_return_30d": 0,
        }

        # Analyst data
        analyst_dict = {
            "analyst_count": metrics.analyst_count if metrics else 0,
            "revisions_up": metrics.analyst_revision_up if metrics else 0,
            "revisions_down": metrics.analyst_revision_down if metrics else 0,
            "price_vs_target_pct": 0,
        }

        return build_feature_vector(
            financial_dict, history_dicts, sentiment_dict, macro_dict, analyst_dict
        )

    async def update_outcome(self, prediction_id: int, actual_eps: float,
                             actual_move_pct: float, eps_estimate: float):
        """Update prediction with actual outcome (feedback loop)."""
        prediction = await self.db.get(Prediction, prediction_id)
        if not prediction:
            return

        beat = actual_eps > eps_estimate
        prediction.actual_outcome = "beat" if beat else "miss"
        prediction.actual_move_pct = actual_move_pct

        # Check if prediction was correct
        if prediction.recommendation == RecommendationEnum.BUY:
            prediction.prediction_correct = actual_move_pct > 0
        elif prediction.recommendation == RecommendationEnum.SELL:
            prediction.prediction_correct = actual_move_pct < 0
        else:  # AVOID
            prediction.prediction_correct = abs(actual_move_pct) > 5  # High vol = correct to avoid

        await self.db.flush()
        logger.info(
            "outcome_updated",
            prediction_id=prediction_id,
            correct=prediction.prediction_correct,
        )
