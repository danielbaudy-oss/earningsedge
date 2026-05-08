# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Low-Quality Stocks Receive Inflated Scores
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate low-quality stocks get BUY recommendations they shouldn't
  - **Scoped PBT Approach**: Scope the property to concrete failing cases — penny stocks/microcap biotechs with quality_score < 50, risk < 60, and raw total_score >= 55
  - Test file: `backend/tests/test_quality_bug_condition.py`
  - Write `compute_quality_score()` as a standalone testable function first (pure function, no side effects)
  - Generate inputs where: market_cap < $1B, avg_volume < 1M, analyst_count < 3, stock_price < $10, earnings_consistency < 0.5
  - Assert that for these low-quality inputs, the adjusted total_score (raw_total_score * quality_score / 100) is strictly less than 55 (BUY threshold)
  - The bug condition from design: `quality_score < 50 AND current_risk_score < 60 AND current_raw_total_score >= 55`
  - Expected behavior: `adjusted_score = int(raw_total_score * (quality_score / 100))` should be < raw_total_score
  - Run test on UNFIXED code — the current code has no quality multiplier, so raw scores pass through unchanged
  - **EXPECTED OUTCOME**: Test FAILS (this is correct — it proves the bug exists because no quality filtering is applied)
  - Document counterexamples found (e.g., "$3 biotech with 0 analysts gets total_score=68 and BUY")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - High-Quality Stocks Unaffected
  - **IMPORTANT**: Follow observation-first methodology
  - Test file: `backend/tests/test_quality_preservation.py`
  - Observe: Run the current scoring logic for high-quality stocks (AAPL-like: $3T market cap, 40 analysts, $190 price, 8/8 earnings quarters) on UNFIXED code and record total_score
  - Observe: Run for mid-cap stocks (AMD-like: $240B market cap, 35 analysts, $150 price) on UNFIXED code and record total_score
  - Write property-based test: for all inputs where market_cap >= $10B AND avg_volume >= 5M AND analyst_count >= 15 AND stock_price >= $50 AND earnings_consistency >= 1.0, the compute_quality_score() returns >= 70
  - Write property-based test: for all high-quality inputs (quality_score >= 70), the adjusted total_score is within 30% of the raw total_score (i.e., `abs(adjusted - raw) <= raw * 0.30`)
  - Write property-based test: compute_quality_score() always returns a value in [0, 100] for any non-negative inputs
  - Write property-based test: compute_quality_score() is monotonic — increasing any single input never decreases the score
  - Verify tests pass on UNFIXED code (compute_quality_score doesn't exist yet, so test the pure function in isolation)
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline behavior patterns to preserve)
  - Mark task complete when tests are written, run, and passing
  - _Requirements: 3.1, 3.2, 3.4, 3.6_

- [x] 3. Implement stock quality filtering fix

  - [x] 3.1 Add compute_quality_score() function to predict_with_model.py
    - Add new function after `calculate_risk_score()` in `backend/app/ml/predict_with_model.py`
    - Signature: `compute_quality_score(market_cap: float, avg_volume: float, analyst_count: int, stock_price: float, earnings_consistency: float) -> int`
    - Implement smooth gradients (NO hard cutoffs):
      - `market_cap_score = min(1.0, market_cap / 10_000_000_000)` — saturates at $10B
      - `volume_score = min(1.0, avg_volume / 5_000_000)` — saturates at 5M shares/day
      - `coverage_score = min(1.0, analyst_count / 15)` — saturates at 15 analysts
      - `price_score = min(1.0, stock_price / 50)` — saturates at $50
      - `earnings_score = earnings_consistency` — already 0→1
    - Composite: weighted geometric mean or product-based compounding
    - Return `int(composite * 100)` clamped to 0–100
    - _Bug_Condition: isBugCondition(input) where quality_score < 50 AND risk < 60 AND raw_total_score >= 55_
    - _Expected_Behavior: adjusted_score = int(raw_total_score * quality_score / 100)_
    - _Preservation: High-quality stocks (quality_score >= 70) get near-identical scores_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 3.2 Return profile data from fetch_enrichment_data()
    - Add `"profile": profile` to the return dict in `fetch_enrichment_data()`
    - This provides access to `marketCapitalization` in `predict_stock()`
    - _Requirements: 2.1_

  - [x] 3.3 Gather quality inputs and apply quality multiplier in predict_stock()
    - Extract `market_cap` from profile: `enrichment["profile"].get("marketCapitalization", 0) * 1_000_000` (Finnhub returns in millions)
    - Extract `avg_volume`: `metrics.get("10DayAverageTradingVolume", 0) * 1_000_000` (returned in millions)
    - Extract `analyst_count`: sum of buy + hold + sell + strongBuy + strongSell from recommendation data (reuse existing `rec_data` or fetch)
    - Use `est_price` (already computed from 52-week high/low midpoint)
    - Compute `earnings_consistency = min(1.0, len(earnings) / 8)`
    - Call `compute_quality_score(market_cap, avg_volume, analyst_count, est_price, earnings_consistency)`
    - Replace the profitability penalty if/elif block with: `total_score = int(total_score * (quality_score / 100))`
    - _Bug_Condition: isBugCondition(input) where quality_score < 50 AND risk < 60 AND raw_total_score >= 55_
    - _Expected_Behavior: total_score = int(total_score * quality_score / 100) for all inputs_
    - _Preservation: High-quality stocks get quality_score near 100, so multiplier ≈ 1.0_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2_

  - [x] 3.4 Remove profitability penalty if/elif block
    - Delete the block: `if op_margin < -100: ... elif op_margin < -50: ... elif op_margin < -20: ...`
    - This is subsumed by the quality score's smooth compounding behavior
    - _Requirements: 2.1, 2.4_

  - [x] 3.5 Store quality_score in feature_importance JSON
    - Add `"quality_score": quality_score` to the `feature_importance` dict in the result
    - Enables transparency and debugging of quality filtering decisions
    - _Requirements: 2.1_

  - [x] 3.6 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Low-Quality Stocks Get Demoted
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior (adjusted_score < raw_total_score for low-quality stocks)
    - When this test passes, it confirms the quality multiplier correctly demotes low-quality stocks
    - Run: `python -m pytest backend/tests/test_quality_bug_condition.py -v`
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.7 Verify preservation tests still pass
    - **Property 2: Preservation** - High-Quality Stocks Unaffected
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run: `python -m pytest backend/tests/test_quality_preservation.py -v`
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions for high-quality stocks)
    - Confirm quality_score >= 70 for large-cap, well-covered stocks
    - Confirm total_score adjustment is minimal (within 30%) for mid-cap stocks
    - _Requirements: 3.1, 3.2, 3.4, 3.6_

- [x] 4. Checkpoint - Ensure all tests pass
  - Run full test suite: `python -m pytest backend/tests/test_quality_bug_condition.py backend/tests/test_quality_preservation.py -v`
  - Verify bug condition test passes (low-quality stocks demoted)
  - Verify preservation tests pass (high-quality stocks unaffected)
  - Verify compute_quality_score() returns values in [0, 100] for all inputs
  - Verify monotonicity property holds
  - Ensure all tests pass, ask the user if questions arise.
