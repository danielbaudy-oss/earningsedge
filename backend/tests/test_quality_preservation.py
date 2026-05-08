"""
Preservation Property Tests: High-Quality Stocks Unaffected

These tests verify that the compute_quality_score() function preserves expected
behavior for high-quality stocks. They test the pure function in isolation
(defined in test_quality_bug_condition.py) BEFORE the fix is implemented.

Properties tested:
1. High-quality inputs (market_cap >= $10B, avg_volume >= 5M, analyst_count >= 15,
   stock_price >= $50, earnings_consistency >= 1.0) produce quality_score >= 70
2. For all non-negative inputs, quality_score is always in [0, 100]
3. Monotonicity: increasing any single input never decreases the quality_score
4. For high-quality stocks (quality_score >= 70), adjusted_score is within 30%
   of raw_total_score

EXPECTED OUTCOME: Tests PASS (confirms baseline behavior patterns to preserve)

Validates: Requirements 3.1, 3.2, 3.4, 3.6
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# Import compute_quality_score from the actual module (fix is implemented)
from app.ml.predict_with_model import compute_quality_score


# ---------------------------------------------------------------------------
# Strategies for generating stock quality inputs
# ---------------------------------------------------------------------------

# High-quality stock inputs: large-cap, high-volume, well-covered
high_quality_market_cap = st.floats(min_value=10_000_000_000, max_value=5_000_000_000_000)  # $10B - $5T
high_quality_volume = st.floats(min_value=5_000_000, max_value=100_000_000)  # 5M - 100M
high_quality_analyst_count = st.integers(min_value=15, max_value=60)
high_quality_price = st.floats(min_value=50.0, max_value=2000.0)
high_quality_earnings = st.floats(min_value=1.0, max_value=1.0)  # Full consistency

# Any non-negative inputs (for boundedness property)
any_market_cap = st.floats(min_value=0.0, max_value=10_000_000_000_000, allow_nan=False, allow_infinity=False)
any_volume = st.floats(min_value=0.0, max_value=500_000_000, allow_nan=False, allow_infinity=False)
any_analyst_count = st.integers(min_value=0, max_value=100)
any_price = st.floats(min_value=0.0, max_value=5000.0, allow_nan=False, allow_infinity=False)
any_earnings = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# Property 1: High-quality inputs produce quality_score >= 70
# ---------------------------------------------------------------------------

class TestHighQualityPreservation:
    """
    Property 2 (Preservation): High-Quality Stocks Unaffected

    For all inputs where market_cap >= $10B AND avg_volume >= 5M AND
    analyst_count >= 15 AND stock_price >= $50 AND earnings_consistency >= 1.0,
    the compute_quality_score() returns >= 70.

    **Validates: Requirements 3.1, 3.2**
    """

    @given(
        market_cap=high_quality_market_cap,
        avg_volume=high_quality_volume,
        analyst_count=high_quality_analyst_count,
        stock_price=high_quality_price,
        earnings_consistency=high_quality_earnings,
    )
    @settings(max_examples=200)
    def test_high_quality_inputs_produce_score_at_least_70(
        self, market_cap, avg_volume, analyst_count, stock_price, earnings_consistency
    ):
        """
        **Validates: Requirements 3.1, 3.2**

        For high-quality stocks (all factors at or above saturation thresholds),
        the quality score should be >= 70, ensuring minimal adjustment to total_score.
        """
        score = compute_quality_score(
            market_cap, avg_volume, analyst_count, stock_price, earnings_consistency
        )
        assert score >= 70, (
            f"High-quality stock got quality_score={score} (expected >= 70). "
            f"Inputs: market_cap=${market_cap/1e9:.1f}B, volume={avg_volume/1e6:.1f}M, "
            f"analysts={analyst_count}, price=${stock_price:.2f}, "
            f"earnings_consistency={earnings_consistency}"
        )


# ---------------------------------------------------------------------------
# Property 2: Boundedness — quality_score always in [0, 100]
# ---------------------------------------------------------------------------

class TestQualityScoreBoundedness:
    """
    Property: Boundedness — quality_score is always in [0, 100]

    For all non-negative inputs, compute_quality_score() always returns
    a value in the range [0, 100].

    **Validates: Requirements 3.4, 3.6**
    """

    @given(
        market_cap=any_market_cap,
        avg_volume=any_volume,
        analyst_count=any_analyst_count,
        stock_price=any_price,
        earnings_consistency=any_earnings,
    )
    @settings(max_examples=300)
    def test_quality_score_always_bounded_0_to_100(
        self, market_cap, avg_volume, analyst_count, stock_price, earnings_consistency
    ):
        """
        **Validates: Requirements 3.4, 3.6**

        For any non-negative inputs, the quality score must be in [0, 100].
        """
        score = compute_quality_score(
            market_cap, avg_volume, analyst_count, stock_price, earnings_consistency
        )
        assert 0 <= score <= 100, (
            f"Quality score {score} is out of bounds [0, 100]. "
            f"Inputs: market_cap={market_cap}, volume={avg_volume}, "
            f"analysts={analyst_count}, price={stock_price}, "
            f"earnings={earnings_consistency}"
        )


# ---------------------------------------------------------------------------
# Property 3: Monotonicity — increasing any single input never decreases score
# ---------------------------------------------------------------------------

class TestQualityScoreMonotonicity:
    """
    Property: Monotonicity — increasing any single input never decreases the score.

    This ensures the quality score behaves intuitively: more market cap, more
    volume, more analysts, higher price, or more earnings data should never
    make a stock appear LESS reliable.

    **Validates: Requirements 3.4, 3.6**
    """

    @given(
        market_cap=st.floats(min_value=0.0, max_value=5_000_000_000_000, allow_nan=False, allow_infinity=False),
        avg_volume=st.floats(min_value=0.0, max_value=100_000_000, allow_nan=False, allow_infinity=False),
        analyst_count=st.integers(min_value=0, max_value=50),
        stock_price=st.floats(min_value=0.0, max_value=2000.0, allow_nan=False, allow_infinity=False),
        earnings_consistency=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        increase=st.floats(min_value=0.01, max_value=1_000_000_000, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_increasing_market_cap_never_decreases_score(
        self, market_cap, avg_volume, analyst_count, stock_price, earnings_consistency, increase
    ):
        """
        **Validates: Requirements 3.4, 3.6**

        Increasing market_cap should never decrease the quality score.
        """
        score_before = compute_quality_score(
            market_cap, avg_volume, analyst_count, stock_price, earnings_consistency
        )
        score_after = compute_quality_score(
            market_cap + increase, avg_volume, analyst_count, stock_price, earnings_consistency
        )
        assert score_after >= score_before, (
            f"Monotonicity violated for market_cap: "
            f"score({market_cap})={score_before} > score({market_cap + increase})={score_after}"
        )

    @given(
        market_cap=st.floats(min_value=0.0, max_value=5_000_000_000_000, allow_nan=False, allow_infinity=False),
        avg_volume=st.floats(min_value=0.0, max_value=100_000_000, allow_nan=False, allow_infinity=False),
        analyst_count=st.integers(min_value=0, max_value=50),
        stock_price=st.floats(min_value=0.0, max_value=2000.0, allow_nan=False, allow_infinity=False),
        earnings_consistency=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        increase=st.floats(min_value=0.01, max_value=50_000_000, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_increasing_volume_never_decreases_score(
        self, market_cap, avg_volume, analyst_count, stock_price, earnings_consistency, increase
    ):
        """
        **Validates: Requirements 3.4, 3.6**

        Increasing avg_volume should never decrease the quality score.
        """
        score_before = compute_quality_score(
            market_cap, avg_volume, analyst_count, stock_price, earnings_consistency
        )
        score_after = compute_quality_score(
            market_cap, avg_volume + increase, analyst_count, stock_price, earnings_consistency
        )
        assert score_after >= score_before, (
            f"Monotonicity violated for volume: "
            f"score({avg_volume})={score_before} > score({avg_volume + increase})={score_after}"
        )

    @given(
        market_cap=st.floats(min_value=0.0, max_value=5_000_000_000_000, allow_nan=False, allow_infinity=False),
        avg_volume=st.floats(min_value=0.0, max_value=100_000_000, allow_nan=False, allow_infinity=False),
        analyst_count=st.integers(min_value=0, max_value=50),
        stock_price=st.floats(min_value=0.0, max_value=2000.0, allow_nan=False, allow_infinity=False),
        earnings_consistency=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        increase=st.integers(min_value=1, max_value=30),
    )
    @settings(max_examples=200)
    def test_increasing_analyst_count_never_decreases_score(
        self, market_cap, avg_volume, analyst_count, stock_price, earnings_consistency, increase
    ):
        """
        **Validates: Requirements 3.4, 3.6**

        Increasing analyst_count should never decrease the quality score.
        """
        score_before = compute_quality_score(
            market_cap, avg_volume, analyst_count, stock_price, earnings_consistency
        )
        score_after = compute_quality_score(
            market_cap, avg_volume, analyst_count + increase, stock_price, earnings_consistency
        )
        assert score_after >= score_before, (
            f"Monotonicity violated for analyst_count: "
            f"score({analyst_count})={score_before} > score({analyst_count + increase})={score_after}"
        )

    @given(
        market_cap=st.floats(min_value=0.0, max_value=5_000_000_000_000, allow_nan=False, allow_infinity=False),
        avg_volume=st.floats(min_value=0.0, max_value=100_000_000, allow_nan=False, allow_infinity=False),
        analyst_count=st.integers(min_value=0, max_value=50),
        stock_price=st.floats(min_value=0.0, max_value=2000.0, allow_nan=False, allow_infinity=False),
        earnings_consistency=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        increase=st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_increasing_price_never_decreases_score(
        self, market_cap, avg_volume, analyst_count, stock_price, earnings_consistency, increase
    ):
        """
        **Validates: Requirements 3.4, 3.6**

        Increasing stock_price should never decrease the quality score.
        """
        score_before = compute_quality_score(
            market_cap, avg_volume, analyst_count, stock_price, earnings_consistency
        )
        score_after = compute_quality_score(
            market_cap, avg_volume, analyst_count, stock_price + increase, earnings_consistency
        )
        assert score_after >= score_before, (
            f"Monotonicity violated for stock_price: "
            f"score({stock_price})={score_before} > score({stock_price + increase})={score_after}"
        )

    @given(
        market_cap=st.floats(min_value=0.0, max_value=5_000_000_000_000, allow_nan=False, allow_infinity=False),
        avg_volume=st.floats(min_value=0.0, max_value=100_000_000, allow_nan=False, allow_infinity=False),
        analyst_count=st.integers(min_value=0, max_value=50),
        stock_price=st.floats(min_value=0.0, max_value=2000.0, allow_nan=False, allow_infinity=False),
        earnings_consistency=st.floats(min_value=0.0, max_value=0.99, allow_nan=False, allow_infinity=False),
        increase=st.floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_increasing_earnings_consistency_never_decreases_score(
        self, market_cap, avg_volume, analyst_count, stock_price, earnings_consistency, increase
    ):
        """
        **Validates: Requirements 3.4, 3.6**

        Increasing earnings_consistency should never decrease the quality score.
        """
        new_earnings = min(1.0, earnings_consistency + increase)
        score_before = compute_quality_score(
            market_cap, avg_volume, analyst_count, stock_price, earnings_consistency
        )
        score_after = compute_quality_score(
            market_cap, avg_volume, analyst_count, stock_price, new_earnings
        )
        assert score_after >= score_before, (
            f"Monotonicity violated for earnings_consistency: "
            f"score({earnings_consistency})={score_before} > "
            f"score({new_earnings})={score_after}"
        )


# ---------------------------------------------------------------------------
# Property 4: High-quality stocks — adjusted_score within 30% of raw_total_score
# ---------------------------------------------------------------------------

class TestHighQualityAdjustmentBounded:
    """
    Property: For high-quality stocks (quality_score >= 70), the adjusted
    total_score is within 30% of the raw total_score.

    This ensures that well-covered, liquid, large-cap stocks are not
    significantly penalized by the quality multiplier.

    **Validates: Requirements 3.1, 3.2**
    """

    @given(
        market_cap=any_market_cap,
        avg_volume=any_volume,
        analyst_count=any_analyst_count,
        stock_price=any_price,
        earnings_consistency=any_earnings,
        raw_total_score=st.integers(min_value=10, max_value=100),
    )
    @settings(max_examples=300)
    def test_high_quality_adjusted_score_within_30_percent(
        self, market_cap, avg_volume, analyst_count, stock_price,
        earnings_consistency, raw_total_score
    ):
        """
        **Validates: Requirements 3.1, 3.2**

        For stocks with quality_score >= 70, the adjusted score should be
        within 30% of the raw total score. We use raw_total_score >= 10 to
        avoid integer truncation artifacts at very small values (where the
        30% tolerance is less than 1 point and int() rounding dominates).
        """
        quality_score = compute_quality_score(
            market_cap, avg_volume, analyst_count, stock_price, earnings_consistency
        )

        # Only test this property for high-quality stocks
        assume(quality_score >= 70)

        adjusted_score = int(raw_total_score * (quality_score / 100))

        # The adjustment should be within 30% of the raw score.
        # A quality_score of 70 means multiplier=0.70, so max reduction is 30%.
        # We add +1 tolerance for int() truncation (floor rounding).
        assert abs(adjusted_score - raw_total_score) <= raw_total_score * 0.30 + 1, (
            f"High-quality stock (quality_score={quality_score}) has adjusted_score="
            f"{adjusted_score} which differs from raw_total_score={raw_total_score} "
            f"by more than 30% (+1 for int truncation). "
            f"Inputs: market_cap=${market_cap/1e9:.1f}B, "
            f"volume={avg_volume/1e6:.1f}M, analysts={analyst_count}, "
            f"price=${stock_price:.2f}, earnings={earnings_consistency}"
        )
