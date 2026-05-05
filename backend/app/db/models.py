"""SQLAlchemy database models for EarningsEdge."""

from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Date,
    Text, ForeignKey, Index, Enum as SAEnum, JSON
)
from sqlalchemy.orm import relationship
from app.db.database import Base
import enum


class RecommendationEnum(enum.Enum):
    BUY = "buy"
    SELL = "sell"
    AVOID = "avoid"


class Stock(Base):
    """Stock/company master data."""
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), unique=True, nullable=False, index=True)
    company_name = Column(String(255), nullable=False)
    sector = Column(String(100))
    industry = Column(String(100))
    market_cap = Column(Float)
    exchange = Column(String(20))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    earnings = relationship("EarningsEvent", back_populates="stock")
    financials = relationship("FinancialMetric", back_populates="stock")
    predictions = relationship("Prediction", back_populates="stock")
    alerts = relationship("Alert", back_populates="stock")

    __table_args__ = (
        Index("ix_stocks_sector", "sector"),
        Index("ix_stocks_name_search", "company_name"),
    )


class EarningsEvent(Base):
    """Earnings event calendar and results."""
    __tablename__ = "earnings_events"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    report_date = Column(Date, nullable=False)
    fiscal_quarter = Column(String(10))  # e.g., "Q1 2024"
    fiscal_year = Column(Integer)
    report_time = Column(String(20))  # "before_market", "after_market"

    # Estimates
    eps_estimate = Column(Float)
    revenue_estimate = Column(Float)

    # Actuals (filled after earnings)
    eps_actual = Column(Float)
    revenue_actual = Column(Float)
    eps_surprise = Column(Float)
    eps_surprise_pct = Column(Float)
    revenue_surprise = Column(Float)
    revenue_surprise_pct = Column(Float)

    # Stock movement (filled after earnings)
    price_before = Column(Float)
    price_after = Column(Float)
    price_change_pct = Column(Float)
    volume_change_pct = Column(Float)

    is_confirmed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    stock = relationship("Stock", back_populates="earnings")
    predictions = relationship("Prediction", back_populates="earnings_event")

    __table_args__ = (
        Index("ix_earnings_date", "report_date"),
        Index("ix_earnings_stock_date", "stock_id", "report_date"),
    )


class FinancialMetric(Base):
    """Quarterly financial metrics for ML features."""
    __tablename__ = "financial_metrics"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    period_date = Column(Date, nullable=False)
    fiscal_quarter = Column(String(10))

    # Income Statement
    revenue = Column(Float)
    net_income = Column(Float)
    eps = Column(Float)
    gross_margin = Column(Float)
    operating_margin = Column(Float)
    net_margin = Column(Float)

    # Growth Metrics
    revenue_growth_yoy = Column(Float)
    eps_growth_yoy = Column(Float)
    revenue_growth_qoq = Column(Float)

    # Balance Sheet
    total_assets = Column(Float)
    total_debt = Column(Float)
    cash_and_equivalents = Column(Float)
    debt_to_equity = Column(Float)

    # Valuation
    pe_ratio = Column(Float)
    forward_pe = Column(Float)
    ps_ratio = Column(Float)
    pb_ratio = Column(Float)

    # Analyst Data
    analyst_count = Column(Integer)
    analyst_mean_target = Column(Float)
    analyst_revision_up = Column(Integer)
    analyst_revision_down = Column(Integer)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    stock = relationship("Stock", back_populates="financials")

    __table_args__ = (
        Index("ix_financials_stock_period", "stock_id", "period_date"),
    )


class Prediction(Base):
    """ML model predictions for earnings events."""
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    earnings_event_id = Column(Integer, ForeignKey("earnings_events.id"), nullable=False)
    model_version = Column(String(50), nullable=False)
    prediction_date = Column(DateTime, default=datetime.utcnow)

    # Core Predictions
    recommendation = Column(SAEnum(RecommendationEnum), nullable=False)
    confidence_score = Column(Float, nullable=False)  # 0-1

    # Probability Predictions
    beat_probability = Column(Float)  # P(EPS beat)
    miss_probability = Column(Float)  # P(EPS miss)
    price_up_probability = Column(Float)  # P(stock goes up post-earnings)
    price_down_probability = Column(Float)  # P(stock goes down)

    # Movement Predictions
    expected_move_pct = Column(Float)  # Expected % move
    expected_volatility = Column(Float)  # Expected IV
    predicted_direction = Column(String(10))  # "up" or "down"

    # Explanation (SHAP values stored as JSON)
    feature_importance = Column(JSON)  # Top features driving prediction
    explanation_text = Column(Text)  # Human-readable explanation

    # Outcome tracking (filled after earnings)
    actual_outcome = Column(String(20))  # "beat", "miss", "meet"
    actual_move_pct = Column(Float)
    prediction_correct = Column(Boolean)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    stock = relationship("Stock", back_populates="predictions")
    earnings_event = relationship("EarningsEvent", back_populates="predictions")

    __table_args__ = (
        Index("ix_predictions_stock_event", "stock_id", "earnings_event_id"),
        Index("ix_predictions_date", "prediction_date"),
    )


class SentimentData(Base):
    """Sentiment data from news and social media."""
    __tablename__ = "sentiment_data"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    source = Column(String(50), nullable=False)  # "news", "reddit"
    collected_at = Column(DateTime, default=datetime.utcnow)

    # Sentiment scores
    sentiment_score = Column(Float)  # -1 to 1
    sentiment_magnitude = Column(Float)  # 0 to 1
    bullish_count = Column(Integer, default=0)
    bearish_count = Column(Integer, default=0)
    neutral_count = Column(Integer, default=0)
    total_mentions = Column(Integer, default=0)

    # Metadata
    sample_headlines = Column(JSON)  # Top headlines/posts

    __table_args__ = (
        Index("ix_sentiment_stock_date", "stock_id", "collected_at"),
    )


class MacroIndicator(Base):
    """Macro economic indicators for ML features."""
    __tablename__ = "macro_indicators"

    id = Column(Integer, primary_key=True, index=True)
    indicator_date = Column(Date, nullable=False)
    vix = Column(Float)
    sp500_return_30d = Column(Float)
    treasury_10y = Column(Float)
    fed_funds_rate = Column(Float)
    unemployment_rate = Column(Float)
    cpi_yoy = Column(Float)
    sector_etf_returns = Column(JSON)  # Sector-level returns

    __table_args__ = (
        Index("ix_macro_date", "indicator_date"),
    )


class Alert(Base):
    """User alerts for upcoming earnings."""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    user_email = Column(String(255), nullable=False)
    days_before = Column(Integer, default=3)
    is_active = Column(Boolean, default=True)
    last_sent_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    stock = relationship("Stock", back_populates="alerts")

    __table_args__ = (
        Index("ix_alerts_user", "user_email"),
    )


class ModelMetrics(Base):
    """Track model performance over time for feedback loop."""
    __tablename__ = "model_metrics"

    id = Column(Integer, primary_key=True, index=True)
    model_version = Column(String(50), nullable=False)
    trained_at = Column(DateTime, default=datetime.utcnow)
    training_samples = Column(Integer)

    # Performance metrics
    accuracy = Column(Float)
    precision_beat = Column(Float)
    recall_beat = Column(Float)
    f1_score = Column(Float)
    auc_roc = Column(Float)
    direction_accuracy = Column(Float)
    mean_absolute_error_move = Column(Float)

    # Feature importance snapshot
    top_features = Column(JSON)
    is_active = Column(Boolean, default=False)
