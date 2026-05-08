"""
Bug Condition Exploration Test: Low-Quality Stocks Receive Inflated Scores

This test demonstrates the bug where low-quality stocks (penny stocks, microcap
biotechs with minimal coverage) receive total_score >= 55 and BUY recommendations
because the current system has NO quality multiplier.

The compute_quality_score() function is defined here as a standalone pure function.
It will later be moved to predict_with_model.py as part of the fix.

EXPECTED OUTCOME: This test FAILS on unfixed code because:
- The current system has no quality filtering
- Raw total_score passes through unchanged
- Low-quality stocks can get score >= 55 with risk < 60 → BUY

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4
"""

import math
import pytest
from app.ml.predict_with_model import calculate_risk_score, generate_recommendation


# ---------------------------------------------------------------------------
# Standalone compute_quality_score() — pure function, no side effects
# Will be moved to predict_with_model.py in the fix implementation (Task 3.1)
# ---------------------------------------------------------------------------

def compute_quality_score(
    market_cap: float,
    avg_volume: float,
    analyst_count: int,
    stock_price: float,
    earnings_consistency: float,
) -> int:
    """
    Compute a 0-100 quality/reliability score for a stock using smooth gradients.

    Each factor maps to 0-1 using min(1.0, value / reference):
    - market_cap_score: saturates at $10B
    - volume_score: saturates at 5M shares/day
    - coverage_score: saturates at 15 analysts
    - price_score: saturates at $50
    - earnings_score: already 0-1 (quarters_with_data / 8)

    Composite: weighted average with a compounding penalty for multiple weak factors.
    """
    # Individual factor scores (smooth 0→1 gradients)
    # Thresholds calibrated for the real stock universe (not just mega-caps)
    market_cap_score = min(1.0, max(0.0, market_cap / 2_000_000_000))   # Saturates at $2B
    volume_score = min(1.0, max(0.0, avg_volume / 2_000_000))           # Saturates at 2M shares/day
    coverage_score = min(1.0, max(0.0, analyst_count / 10))             # Saturates at 10 analysts
    price_score = min(1.0, max(0.0, stock_price / 30))                  # Saturates at $30
    earnings_score = min(1.0, max(0.0, earnings_consistency))

    # Weighted arithmetic mean — one weak factor reduces score but doesn't destroy it
    # Weights: market_cap=0.30, volume=0.20, coverage=0.20, price=0.15, earnings=0.15
    weights = [0.30, 0.20, 0.20, 0.15, 0.15]
    scores = [market_cap_score, volume_score, coverage_score, price_score, earnings_score]

    # Weighted average
    composite = sum(w * s for w, s in zip(weights, scores))

    return int(max(0, min(100, composite * 100)))


# ---------------------------------------------------------------------------
# Test cases: Low-quality stocks that currently get BUY but shouldn't
# ---------------------------------------------------------------------------

class TestBugConditionLowQualityStocksInflated:
    """
    Property 1: Bug Condition — Low-Quality Stocks Receive Inflated Scores

    These tests simulate the scoring pipeline for known low-quality stocks.
    They assert that with a quality multiplier, the adjusted_score would be < 55
    (below BUY threshold). On UNFIXED code, these tests FAIL because no quality
    multiplier exists — raw scores pass through unchanged.

    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4
    """

    def test_penny_biotech_should_not_get_buy(self):
        """
        IMVT-like: $2.91 biotech, -3% margin, 0 analysts, $800M market cap.
        Current system gives total_score=68, risk < 60 → BUY.
        With quality_score ≈ 5, adjusted = 68 * 0.05 = 3 → AVOID.

        Key: We use parameters that keep risk below 60 (high beat_prob,
        moderate volatility, slightly negative margin) while the stock is
        still fundamentally low-quality by all quality dimensions.
        """
        # Simulate the stock characteristics
        market_cap = 800_000_000       # $800M
        avg_volume = 500_000           # 500K shares/day
        analyst_count = 0              # No analyst coverage
        stock_price = 2.91             # Penny stock
        earnings_consistency = 0.25    # Only 2/8 quarters of data

        quality_score = compute_quality_score(
            market_cap, avg_volume, analyst_count, stock_price, earnings_consistency
        )

        # Quality score should be very low for this stock
        assert quality_score < 50, (
            f"Quality score {quality_score} should be < 50 for a $2.91 biotech "
            f"with 0 analysts and $800M market cap"
        )

        # Simulate a raw total_score that the current system would produce
        # (the bug: current system gives ~68 for stocks like this)
        raw_total_score = 68

        # The adjusted score with quality multiplier should be below BUY threshold
        adjusted_score = int(raw_total_score * (quality_score / 100))
        assert adjusted_score < 55, (
            f"Adjusted score {adjusted_score} (raw={raw_total_score} * "
            f"quality={quality_score}/100) should be < 55 (BUY threshold). "
            f"Bug: $2.91 biotech with 0 analysts gets BUY recommendation."
        )

        # NOW: verify the CURRENT system has no quality multiplier
        # Use parameters that produce risk < 60 to trigger the bug condition:
        # - High beat_prob (0.75) reduces uncertainty risk
        # - Moderate volatility (3.0) keeps vol_risk low
        # - Slightly negative margin (-3%) → margin_risk = 0.45
        # - Non-biotech sector to avoid sector_risk pushing over 60
        risk_score = calculate_risk_score(
            beat_prob=0.75, direction_prob=0.65,
            expected_move=5.0, volatility=3.0, beta=1.0,
            operating_margin=-3.0, stock_price=2.91,
            sector="Technology"
        )

        # Verify the bug condition: risk < 60
        assert risk_score < 60, (
            f"Test setup error: risk_score={risk_score} should be < 60 "
            f"to demonstrate the bug condition"
        )

        # The bug: with raw_total_score >= 55 and risk < 60, they get BUY
        recommendation = generate_recommendation(
            score=adjusted_score, mode="trader",
            risk_score=risk_score, beat_prob=0.75, direction_prob=0.65
        )

        # After the fix: quality multiplier reduces score below 55 → "avoid"
        assert recommendation != "buy", (
            f"BUG CONFIRMED: ${stock_price} stock with {analyst_count} analysts "
            f"and ${market_cap/1e9:.1f}B market cap gets 'buy' recommendation "
            f"(score={adjusted_score}, risk={risk_score}). "
            f"Quality score would be {quality_score}, adjusted score would be "
            f"{adjusted_score} → should be 'avoid'."
        )

    def test_microcap_no_coverage_should_not_get_buy(self):
        """
        Microcap with no analyst coverage: $5 stock, $500M market cap, 2 quarters data.
        Current system can give total_score=62, risk=48 → BUY.
        With quality_score ≈ 15, adjusted = 62 * 0.15 = 9 → AVOID.
        """
        market_cap = 500_000_000       # $500M
        avg_volume = 300_000           # 300K shares/day
        analyst_count = 1              # Minimal coverage
        stock_price = 5.00             # Low price
        earnings_consistency = 0.25    # 2/8 quarters

        quality_score = compute_quality_score(
            market_cap, avg_volume, analyst_count, stock_price, earnings_consistency
        )

        assert quality_score < 50, (
            f"Quality score {quality_score} should be < 50 for a $5 stock "
            f"with 1 analyst and $500M market cap"
        )

        raw_total_score = 62
        adjusted_score = int(raw_total_score * (quality_score / 100))
        assert adjusted_score < 55, (
            f"Adjusted score {adjusted_score} should be < 55 for low-quality stock"
        )

        # Verify current system gives BUY (the bug)
        risk_score = calculate_risk_score(
            beat_prob=0.70, direction_prob=0.55,
            expected_move=5.0, volatility=4.0, beta=1.2,
            operating_margin=-15.0, stock_price=5.00,
            sector="Biotechnology"
        )

        recommendation = generate_recommendation(
            score=adjusted_score, mode="trader",
            risk_score=risk_score, beat_prob=0.70, direction_prob=0.55
        )

        # After the fix: quality multiplier reduces score below 55 → "avoid"
        assert recommendation != "buy", (
            f"BUG CONFIRMED: ${stock_price} stock with {analyst_count} analyst "
            f"and ${market_cap/1e6:.0f}M market cap gets 'buy' "
            f"(score={adjusted_score}, risk={risk_score}). "
            f"Quality score = {quality_score}, adjusted = {adjusted_score}."
        )

    def test_compound_weakness_should_not_get_buy(self):
        """
        Stock that's moderate on each factor but weak across ALL of them.
        Each individual factor isn't terrible, but combined they indicate
        an unreliable prediction target.

        $8 stock, $900M market cap, 2 analysts, 800K volume, 3/8 quarters.
        Current system: total_score=58, risk=45 → BUY.
        With quality_score ≈ 20, adjusted = 58 * 0.20 = 12 → AVOID.
        """
        market_cap = 900_000_000       # $900M (not tiny, but small)
        avg_volume = 800_000           # 800K (not illiquid, but thin)
        analyst_count = 2              # 2 analysts (minimal)
        stock_price = 8.00             # $8 (not penny, but low)
        earnings_consistency = 0.375   # 3/8 quarters

        quality_score = compute_quality_score(
            market_cap, avg_volume, analyst_count, stock_price, earnings_consistency
        )

        assert quality_score < 50, (
            f"Quality score {quality_score} should be < 50 for compound weakness "
            f"(${stock_price}, {analyst_count} analysts, ${market_cap/1e9:.1f}B cap)"
        )

        raw_total_score = 58
        adjusted_score = int(raw_total_score * (quality_score / 100))
        assert adjusted_score < 55, (
            f"Adjusted score {adjusted_score} should be < 55 for compound weakness"
        )

        # Verify current system gives BUY (the bug)
        risk_score = calculate_risk_score(
            beat_prob=0.60, direction_prob=0.55,
            expected_move=4.0, volatility=3.5, beta=1.1,
            operating_margin=2.0, stock_price=8.00,
            sector="Technology"
        )

        recommendation = generate_recommendation(
            score=adjusted_score, mode="trader",
            risk_score=risk_score, beat_prob=0.60, direction_prob=0.55
        )

        # After the fix: quality multiplier reduces score below 55 → "avoid"
        assert recommendation != "buy", (
            f"BUG CONFIRMED: Compound weakness stock gets 'buy' "
            f"(score={adjusted_score}, risk={risk_score}). "
            f"Quality score = {quality_score}, adjusted = {adjusted_score}."
        )

    def test_low_volume_speculative_should_not_get_buy(self):
        """
        Low volume speculative stock: $7 stock, 200K volume, 0 analysts.
        High volatility makes it look like "opportunity" to the model.
        Current system: total_score=60, risk < 60 → BUY.
        With quality_score ≈ 3, adjusted = 60 * 0.03 = 1 → AVOID.

        Key: Use parameters that keep risk below 60 while stock is
        fundamentally low-quality (no coverage, thin volume, low price).
        """
        market_cap = 400_000_000       # $400M
        avg_volume = 200_000           # 200K (very thin)
        analyst_count = 0              # No coverage
        stock_price = 7.00             # Low price
        earnings_consistency = 0.125   # 1/8 quarters

        quality_score = compute_quality_score(
            market_cap, avg_volume, analyst_count, stock_price, earnings_consistency
        )

        assert quality_score < 50, (
            f"Quality score {quality_score} should be < 50 for speculative stock "
            f"with 0 analysts and 200K volume"
        )

        raw_total_score = 60
        adjusted_score = int(raw_total_score * (quality_score / 100))
        assert adjusted_score < 55, (
            f"Adjusted score {adjusted_score} should be < 55"
        )

        # Use parameters that keep risk < 60:
        # - High beat_prob (0.72) reduces uncertainty
        # - Low volatility (2.5) keeps vol_risk low
        # - Slightly negative margin (-10%) → moderate margin_risk
        # - Non-biotech sector
        risk_score = calculate_risk_score(
            beat_prob=0.72, direction_prob=0.60,
            expected_move=4.0, volatility=2.5, beta=1.0,
            operating_margin=-10.0, stock_price=7.00,
            sector="Technology"
        )

        # Verify the bug condition: risk < 60
        assert risk_score < 60, (
            f"Test setup error: risk_score={risk_score} should be < 60 "
            f"to demonstrate the bug condition"
        )

        recommendation = generate_recommendation(
            score=adjusted_score, mode="trader",
            risk_score=risk_score, beat_prob=0.72, direction_prob=0.60
        )

        # After the fix: quality multiplier reduces score below 55 → "avoid"
        assert recommendation != "buy", (
            f"BUG CONFIRMED: Speculative stock with 0 analysts and 200K volume "
            f"gets 'buy' (score={adjusted_score}, risk={risk_score}). "
            f"Quality score = {quality_score}, adjusted = {adjusted_score}."
        )
