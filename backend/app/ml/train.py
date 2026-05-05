"""Training pipeline for the earnings prediction model.

This module handles:
1. Loading historical data from the database
2. Building feature matrices
3. Training the XGBoost model
4. Evaluating and saving the model
5. Daily retraining with new outcomes (feedback loop)
"""

import pandas as pd
import numpy as np
from datetime import datetime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.db.models import (
    EarningsEvent, FinancialMetric, SentimentData,
    MacroIndicator, Stock, ModelMetrics
)
from app.ml.model import EarningsPredictionModel
from app.ml.features import build_feature_vector
import structlog

logger = structlog.get_logger()
settings = get_settings()


def load_training_data() -> tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]:
    """
    Load and prepare training data from the database.

    Returns feature matrix X and target arrays for:
    - y_beat: 1 if EPS beat, 0 otherwise
    - y_direction: 1 if stock went up post-earnings, 0 otherwise
    - y_magnitude: actual % price change post-earnings
    """
    engine = create_engine(settings.database_url_sync)

    with Session(engine) as session:
        # Get completed earnings events with outcomes
        events = session.execute(
            select(EarningsEvent, Stock)
            .join(Stock)
            .where(
                EarningsEvent.eps_actual.isnot(None),
                EarningsEvent.price_change_pct.isnot(None),
            )
            .order_by(EarningsEvent.report_date)
        ).all()

        if not events:
            raise ValueError("No training data available. Ingest data first.")

        logger.info("training_data_loaded", num_events=len(events))

        feature_rows = []
        y_beat_list = []
        y_direction_list = []
        y_magnitude_list = []

        for event, stock in events:
            # Get financial metrics before this earnings date
            metrics = session.execute(
                select(FinancialMetric)
                .where(
                    FinancialMetric.stock_id == stock.id,
                    FinancialMetric.period_date < event.report_date,
                )
                .order_by(FinancialMetric.period_date.desc())
                .limit(1)
            ).scalar_one_or_none()

            if not metrics:
                continue

            # Get earnings history before this event
            history = session.execute(
                select(EarningsEvent)
                .where(
                    EarningsEvent.stock_id == stock.id,
                    EarningsEvent.report_date < event.report_date,
                    EarningsEvent.eps_actual.isnot(None),
                )
                .order_by(EarningsEvent.report_date.desc())
                .limit(8)
            ).scalars().all()

            # Get sentiment data
            sentiment_row = session.execute(
                select(SentimentData)
                .where(
                    SentimentData.stock_id == stock.id,
                    SentimentData.collected_at < event.report_date,
                )
                .order_by(SentimentData.collected_at.desc())
                .limit(1)
            ).scalar_one_or_none()

            # Get macro indicators
            macro_row = session.execute(
                select(MacroIndicator)
                .where(MacroIndicator.indicator_date <= event.report_date)
                .order_by(MacroIndicator.indicator_date.desc())
                .limit(1)
            ).scalar_one_or_none()

            # Build feature dict
            financial_dict = {
                "revenue_growth_yoy": metrics.revenue_growth_yoy or 0,
                "eps_growth_yoy": metrics.eps_growth_yoy or 0,
                "revenue_growth_qoq": metrics.revenue_growth_qoq or 0,
                "gross_margin": metrics.gross_margin or 0,
                "operating_margin": metrics.operating_margin or 0,
                "net_margin": metrics.net_margin or 0,
                "pe_ratio": metrics.pe_ratio or 0,
                "forward_pe": metrics.forward_pe or 0,
                "ps_ratio": metrics.ps_ratio or 0,
                "debt_to_equity": metrics.debt_to_equity or 0,
            }

            history_dicts = [
                {
                    "eps_surprise_pct": h.eps_surprise_pct or 0,
                    "price_change_pct": h.price_change_pct or 0,
                }
                for h in history
            ]

            sentiment_dict = {
                "news_sentiment": sentiment_row.sentiment_score if sentiment_row else 0,
                "reddit_sentiment": 0,
                "total_mentions": sentiment_row.total_mentions if sentiment_row else 0,
                "bullish_ratio": (
                    sentiment_row.bullish_count / max(sentiment_row.total_mentions, 1)
                    if sentiment_row else 0.5
                ),
            }

            macro_dict = {
                "vix": macro_row.vix if macro_row else 20,
                "sp500_return_30d": macro_row.sp500_return_30d if macro_row else 0,
                "treasury_10y": macro_row.treasury_10y if macro_row else 4.0,
                "sector_return_30d": 0,
            }

            analyst_dict = {
                "analyst_count": metrics.analyst_count or 0,
                "revisions_up": metrics.analyst_revision_up or 0,
                "revisions_down": metrics.analyst_revision_down or 0,
                "price_vs_target_pct": 0,
            }

            features_df = build_feature_vector(
                financial_dict, history_dicts, sentiment_dict, macro_dict, analyst_dict
            )
            feature_rows.append(features_df)

            # Targets
            y_beat_list.append(1 if (event.eps_surprise_pct or 0) > 0 else 0)
            y_direction_list.append(1 if (event.price_change_pct or 0) > 0 else 0)
            y_magnitude_list.append(event.price_change_pct or 0)

    X = pd.concat(feature_rows, ignore_index=True)
    y_beat = np.array(y_beat_list)
    y_direction = np.array(y_direction_list)
    y_magnitude = np.array(y_magnitude_list)

    logger.info("features_built", shape=X.shape)
    return X, y_beat, y_direction, y_magnitude


def train_model() -> dict:
    """Full training pipeline. Returns metrics."""
    logger.info("training_started")

    X, y_beat, y_direction, y_magnitude = load_training_data()

    model = EarningsPredictionModel()
    metrics = model.train(X, y_beat, y_direction, y_magnitude)
    model.save()

    # Save metrics to database
    engine = create_engine(settings.database_url_sync)
    with Session(engine) as session:
        # Deactivate previous models
        session.execute(
            ModelMetrics.__table__.update().values(is_active=False)
        )

        model_metrics = ModelMetrics(
            model_version=model.version,
            training_samples=len(X),
            accuracy=metrics["accuracy"],
            precision_beat=metrics["precision_beat"],
            recall_beat=metrics["recall_beat"],
            f1_score=metrics["f1_score"],
            auc_roc=metrics["auc_roc"],
            direction_accuracy=metrics["direction_accuracy"],
            mean_absolute_error_move=metrics["mean_absolute_error_move"],
            top_features=dict(
                zip(X.columns, model.beat_model.feature_importances_.tolist())
            ),
            is_active=True,
        )
        session.add(model_metrics)
        session.commit()

    logger.info("training_complete", metrics=metrics, version=model.version)
    return metrics


if __name__ == "__main__":
    metrics = train_model()
    print(f"Training complete. Metrics: {metrics}")
