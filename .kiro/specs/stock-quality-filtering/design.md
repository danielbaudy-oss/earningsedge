# Stock Quality Filtering Bugfix Design

## Overview

The prediction system over-ranks penny stocks and microcap biotech stocks because the current scoring pipeline lacks a quality/reliability layer. The `calculate_risk_score()` function uses hard cutoffs for operating margin and a linear price risk gradient, but these individual factors don't compound — a $3 biotech with 26% revenue growth can still pass the `risk < 60` gate and receive a BUY recommendation.

The fix introduces a `compute_quality_score()` function that produces a 0–100 composite score using smooth continuous gradients (no hard cutoffs). This score acts as a multiplier on the total score (`total_score = int(raw_total_score * (quality_score / 100))`), naturally demoting low-quality stocks without binary thresholds. The existing profitability penalty (hard if/elif blocks) is removed and subsumed by the quality score's smooth compounding behavior.

## Glossary

- **Bug_Condition (C)**: A stock is low-quality (quality_score < 50) but the current system assigns a total_score ≥ 55 with risk < 60, allowing a BUY recommendation
- **Property (P)**: After applying the quality multiplier, low-quality stocks have their total_score reduced proportionally, preventing unwarranted BUY recommendations
- **Preservation**: High-quality stocks (quality_score ≥ 70) receive near-identical scores to the current system — the multiplier is close to 1.0
- **compute_quality_score()**: New function in `predict_with_model.py` that takes market_cap, avg_volume, analyst_count, stock_price, earnings_consistency and returns a 0–100 score using smooth curves
- **Quality Multiplier**: The ratio `quality_score / 100` applied to the raw total score before recommendation generation
- **Smooth Gradient**: A continuous function (e.g., `min(1.0, x / reference)` or exponential curve) that maps an input to 0–1 without any if/else thresholds

## Bug Details

### Bug Condition

The bug manifests when a stock has low market cap, low liquidity, minimal analyst coverage, and/or inconsistent earnings history, yet the current system's risk factors don't compound sufficiently to block a BUY recommendation. The `calculate_risk_score()` function uses independent weighted factors that can individually stay low enough to keep the total risk below 60, even when the stock is fundamentally unpredictable.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type StockPredictionContext
  OUTPUT: boolean
  
  quality_score ← compute_quality_score(
    market_cap = input.market_cap,
    avg_volume = input.avg_daily_volume,
    analyst_count = input.analyst_count,
    stock_price = input.stock_price,
    earnings_consistency = input.quarters_with_earnings_data / 8
  )
  
  RETURN quality_score < 50
         AND input.current_risk_score < 60
         AND input.current_raw_total_score >= 55
END FUNCTION
```

### Examples

- **IMVT ($2.91, biotech, -3% margin, 0 analysts, $800M market cap)**: Current system gives total_score=68, risk=52 → BUY. With quality score ≈ 25, adjusted score = 68 * 0.25 = 17 → AVOID
- **SAVA ($3.50, biotech, -200% margin, 2 analysts, $150M market cap)**: Current system gives total_score=61, risk=55 → BUY. With quality score ≈ 18, adjusted score = 61 * 0.18 = 11 → AVOID
- **AAPL ($190, tech, 30% margin, 40 analysts, $3T market cap)**: Quality score ≈ 100, adjusted score = total_score * 1.0 → unchanged
- **AMD ($150, semiconductor, 5% margin, 35 analysts, $240B market cap)**: Quality score ≈ 95, adjusted score ≈ total_score * 0.95 → negligible change

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Large-cap stocks ($10B+) with strong analyst coverage receive quality scores near 100, so their total scores are effectively unchanged
- Mid-cap stocks ($2B–$10B) with adequate coverage receive quality scores of 70–90, resulting in minimal adjustment (≤ 30% reduction at worst)
- The `calculate_risk_score()` function itself is NOT modified — it continues to compute risk using uncertainty, volatility, beta, downside, margin, price, and sector factors
- The risk < 60 gate for BUY recommendations remains unchanged
- ML model inference (beat_prob, direction_prob, expected_move) is not modified
- The recommendation logic in `generate_recommendation()` is not modified
- All existing features, signals, and enrichment data continue to be computed identically

**Scope:**
All inputs where `quality_score >= 70` should produce total scores within 5 points of the current system. The quality filter only further restricts — it never promotes a stock that would otherwise be AVOID/SELL to BUY.

## Hypothesized Root Cause

Based on the bug description, the most likely issues are:

1. **No Compounding of Weakness Signals**: The current `calculate_risk_score()` uses independent weighted factors. A stock can have moderate price_risk (0.5), moderate margin_risk (0.45), and moderate sector_risk (0.5) — each individually "not that bad" — but together they represent a fundamentally unreliable stock. The weighted sum doesn't push risk above 60.

2. **Missing Quality Dimensions**: The risk score doesn't consider market cap, trading volume, analyst coverage, or earnings data reliability. A $3 stock with zero analyst coverage and 2 quarters of data is treated with the same confidence as AAPL.

3. **Hard Cutoffs in Profitability Penalty**: The current profitability penalty uses if/elif blocks (`< -100`, `< -50`, `< -20`) which create discontinuities and don't interact with other quality signals. A stock at -19% margin gets zero penalty regardless of other red flags.

4. **No Multiplicative Interaction**: The current system uses additive risk scoring. Quality signals should compound multiplicatively — a stock that's low-cap AND low-volume AND low-coverage should be penalized much more than the sum of individual penalties.

## Correctness Properties

Property 1: Bug Condition - Low-Quality Stocks Get Demoted

_For any_ stock prediction input where the bug condition holds (quality_score < 50 AND current risk < 60 AND raw total score ≥ 55), the fixed function SHALL produce an adjusted total_score that is strictly less than the raw total_score, with the reduction proportional to the quality score (adjusted = raw * quality_score / 100).

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

Property 2: Preservation - High-Quality Stocks Unaffected

_For any_ stock prediction input where the bug condition does NOT hold (quality_score ≥ 70), the fixed function SHALL produce a total_score within 5 points of the original system's total_score, preserving the ranking and recommendation for well-covered, liquid, large-cap stocks.

**Validates: Requirements 3.1, 3.2, 3.4, 3.6**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `backend/app/ml/predict_with_model.py`

**New Function**: `compute_quality_score(market_cap, avg_volume, analyst_count, stock_price, earnings_consistency)`

**Specific Changes**:

1. **Add `compute_quality_score()` function** (near the other scoring functions, after `calculate_risk_score()`):
   - `market_cap_score = min(1.0, market_cap / 10_000_000_000)` — smooth 0→1, saturates at $10B
   - `volume_score = min(1.0, avg_volume / 5_000_000)` — smooth 0→1, saturates at 5M shares/day
   - `coverage_score = min(1.0, analyst_count / 15)` — smooth 0→1, saturates at 15 analysts
   - `price_score = min(1.0, stock_price / 50)` — smooth 0→1, exponential feel at low prices
   - `earnings_score = earnings_consistency` — already 0→1 (quarters_with_data / 8)
   - Composite: weighted geometric mean or product-based compounding so multiple weak signals compound naturally
   - Final score: `int(composite * 100)`, clamped to 0–100

2. **Gather quality inputs in `predict_stock()`**:
   - `market_cap`: from Finnhub profile2 endpoint (`profile.get("marketCapitalization", 0) * 1_000_000` — Finnhub returns in millions)
   - `avg_volume`: from Finnhub metrics (`metrics.get("10DayAverageTradingVolume", 0) * 1_000_000` — returned in millions)
   - `analyst_count`: sum of buy + hold + sell + strongBuy + strongSell from the recommendation data (already fetched)
   - `stock_price`: estimated from 52-week high/low midpoint (already computed as `est_price`)
   - `earnings_consistency`: `min(1.0, len(earnings) / 8)` — number of historical earnings quarters available

3. **Return profile from `fetch_enrichment_data()`**: Add `"profile": profile` to the return dict so `predict_stock()` can access `marketCapitalization`

4. **Apply quality multiplier to total_score**: Replace the hard-cutoff profitability penalty block with:
   ```python
   quality_score = compute_quality_score(market_cap, avg_volume, analyst_count, est_price, earnings_consistency)
   total_score = int(total_score * (quality_score / 100))
   ```

5. **Remove profitability penalty**: Delete the if/elif block that applies 0.70/0.80/0.90 multipliers based on operating margin thresholds

6. **Store quality_score in feature_importance**: Add `"quality_score": quality_score` to the `feature_importance` dict for transparency and debugging

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that simulate prediction scoring for known low-quality stocks (penny stocks, microcap biotechs with minimal coverage) and assert that the current system inappropriately assigns high scores and BUY recommendations. Run these tests on the UNFIXED code to observe the bug in action.

**Test Cases**:
1. **Penny Biotech Test**: Simulate scoring for a $3 biotech with -200% margin, 0 analysts, $150M market cap (will produce BUY on unfixed code)
2. **Microcap No Coverage Test**: Simulate scoring for a $5 stock with 0 analyst coverage, $500M market cap, 2 quarters of data (will produce inflated score on unfixed code)
3. **Low Volume Speculative Test**: Simulate scoring for a stock with < 100K daily volume, high volatility, no analyst coverage (will produce BUY on unfixed code)
4. **Compound Weakness Test**: Simulate a stock that's moderate on each individual factor but weak across all of them (will pass risk < 60 on unfixed code)

**Expected Counterexamples**:
- Stocks with quality_score < 30 receiving total_score > 55 and BUY recommendations
- Possible causes: no quality multiplier exists, profitability penalty has hard cutoffs that don't trigger for moderate cases

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  quality_score := compute_quality_score(input.market_cap, input.avg_volume, input.analyst_count, input.stock_price, input.earnings_consistency)
  adjusted_score := int(raw_total_score * (quality_score / 100))
  ASSERT adjusted_score < raw_total_score
  ASSERT adjusted_score == int(raw_total_score * quality_score / 100)
  ASSERT quality_score >= 0 AND quality_score <= 100
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  quality_score := compute_quality_score(input.market_cap, input.avg_volume, input.analyst_count, input.stock_price, input.earnings_consistency)
  ASSERT quality_score >= 70
  adjusted_score := int(raw_total_score * (quality_score / 100))
  ASSERT abs(adjusted_score - raw_total_score) <= raw_total_score * 0.30
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many random stock configurations across the input domain
- It catches edge cases where quality factors interact unexpectedly
- It provides strong guarantees that high-quality stocks are not penalized

**Test Plan**: Observe behavior on UNFIXED code first for high-quality stocks (large-cap, high-coverage), then write property-based tests capturing that behavior.

**Test Cases**:
1. **Large-Cap Preservation**: Verify that stocks with market_cap > $10B, 15+ analysts, high volume receive quality_score ≥ 95 and near-identical total scores
2. **Mid-Cap Preservation**: Verify that stocks with market_cap $2B–$10B, 5–15 analysts receive quality_score 70–95 and minimal score reduction
3. **Recommendation Gate Preservation**: Verify that the risk < 60 gate still blocks BUY regardless of quality score
4. **Score Monotonicity**: Verify that increasing any quality input (market_cap, volume, analysts, price, consistency) never decreases the quality score

### Unit Tests

- Test `compute_quality_score()` with known inputs and verify smooth gradient behavior
- Test that each individual factor produces a smooth 0→1 curve with no discontinuities
- Test edge cases: zero market cap, zero volume, zero analysts, zero price
- Test that the composite compounding works (multiple low factors → very low score)
- Test that the profitability penalty removal doesn't break existing test cases

### Property-Based Tests

- Generate random (market_cap, avg_volume, analyst_count, stock_price, earnings_consistency) tuples and verify quality_score is always in [0, 100]
- Generate random inputs and verify monotonicity: increasing any single input never decreases quality_score
- Generate random high-quality stock configurations and verify quality_score ≥ 70
- Generate random low-quality configurations and verify the multiplier reduces total_score below BUY threshold

### Integration Tests

- Test full `predict_stock()` flow with a mocked low-quality stock and verify the quality multiplier is applied
- Test full `predict_stock()` flow with a mocked high-quality stock and verify minimal score change
- Test that `quality_score` appears in the `feature_importance` JSON output
- Test that removing the profitability penalty + adding quality score produces equivalent or better filtering for known bad stocks
