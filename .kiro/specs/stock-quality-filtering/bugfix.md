# Bugfix Requirements Document

## Introduction

The prediction system over-ranks penny stocks and microcap biotech stocks as top recommendations in the "Top Trades" list. These low-quality, unpredictable stocks appear at the top because they exhibit large percentage price swings and high short-term volatility, which the model interprets as "high opportunity." However, these movements are noisy, non-fundamental, and driven by news/hype/dilution rather than earnings — making them unreliable predictions that mislead users.

The root cause is that the risk score (`calculate_risk_score()`) doesn't adequately penalize stocks that are fundamentally unpredictable. The current risk factors (stock price, operating margin, sector, volatility) are insufficient — a $3 stock with 26% revenue growth and -3% margins can still receive a BUY recommendation because the individual risk factors don't compound to exceed the risk < 60 threshold. There is no consideration of liquidity, analyst coverage, market cap tiers, earnings consistency, or data reliability as quality signals.

The fix implements a Stock Quality Scoring layer that computes a composite quality/reliability score (0-100) based on liquidity, market cap, financial stability, volatility, and data reliability, then uses this score as a weight multiplier on the final recommendation score — ensuring low-quality stocks are naturally demoted without hard cutoffs.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a stock has very low market cap, low liquidity, minimal analyst coverage, and inconsistent earnings history THEN the system assigns a risk score that can still fall below 60, allowing a BUY recommendation

1.2 WHEN a low-priced stock shows large percentage price swings and high short-term volatility THEN the system interprets this as "high opportunity" and assigns a high total score, ranking it above fundamentally sound large-cap stocks in the Top Trades list

1.3 WHEN a microcap biotech stock has strong revenue growth (e.g., 26% YoY) but deeply negative margins and no analyst coverage THEN the system's individual risk factors (price_risk, margin_risk, sector_risk) do not compound sufficiently to push risk above 60

1.4 WHEN the prediction engine calculates the total score for a low-quality stock THEN there is no quality-based weight multiplier applied, so the raw score based on momentum and beat probability alone determines ranking

1.5 WHEN a stock lacks sufficient trading volume, analyst coverage, or has unreliable/sparse financial data THEN the system treats it with the same confidence as a well-covered large-cap stock with years of reliable data

### Expected Behavior (Correct)

2.1 WHEN a stock has low market cap, low liquidity, minimal analyst coverage, and inconsistent earnings history THEN the system SHALL compute a quality score (0-100) using smooth continuous gradients for each factor (no hard cutoffs), and this quality score SHALL act as a weight multiplier on the total recommendation score, naturally reducing its ranking

2.2 WHEN a low-priced stock shows large percentage price swings and high short-term volatility THEN the system SHALL recognize these as noise rather than opportunity by assigning a low quality score — the price component uses a smooth curve where risk increases exponentially as price decreases (e.g., `min(1.0, price/50)`)

2.3 WHEN a microcap biotech stock has strong revenue growth but deeply negative margins and no analyst coverage THEN the system SHALL assign a quality score that reflects the combination of these unreliability signals through smooth compounding gradients, ensuring the weighted total score is naturally low enough to prevent a BUY recommendation

2.4 WHEN the prediction engine calculates the total score THEN the system SHALL apply a quality score multiplier (quality_score / 100) to the total score before generating the recommendation, so that low-quality stocks are naturally demoted in ranking without any hard price or market cap thresholds

2.5 WHEN a stock lacks sufficient trading volume, analyst coverage, or has unreliable/sparse financial data THEN the system SHALL assign a lower quality score reflecting reduced prediction confidence — each factor contributes on a smooth 0-to-1 scale that compounds with other factors

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a stock has large market cap (> $10B), high liquidity, strong analyst coverage, and consistent earnings history THEN the system SHALL CONTINUE TO rank and recommend it based on its prediction signals without penalty (quality score near 100)

3.2 WHEN a mid-cap stock ($2B-$10B) has adequate liquidity and analyst coverage THEN the system SHALL CONTINUE TO generate recommendations with minimal quality adjustment (quality score 70-90)

3.3 WHEN the risk score for any stock exceeds 60 THEN the system SHALL CONTINUE TO block BUY recommendations regardless of quality score, preserving the existing risk threshold gate

3.4 WHEN the prediction engine generates beat probability, direction probability, and expected move calculations THEN the system SHALL CONTINUE TO use the same ML model inference and signal blending logic without modification

3.5 WHEN a stock receives a SELL or AVOID recommendation under the current system THEN the system SHALL CONTINUE TO assign SELL or AVOID (the quality filter only further restricts BUY, never promotes to BUY)

3.6 WHEN the system calculates risk_score using prediction uncertainty, volatility, beta, downside potential, fundamental risk, stock price risk, and sector risk THEN the system SHALL CONTINUE TO use these existing risk factors unchanged — the quality score is an additional layer, not a replacement

---

## Bug Condition (Formal)

### Bug Condition Function

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type StockPredictionInput
  OUTPUT: boolean
  
  // Returns true when the stock is low-quality/unpredictable but the current
  // system fails to adequately penalize it, allowing inflated scores/rankings.
  // Uses smooth continuous functions — NO hard cutoffs.
  
  quality_score ← computeQualityScore(X)
  // Quality score uses smooth gradients for all inputs:
  //   market_cap_score = min(1.0, market_cap / 10B)  — smooth 0→1
  //   volume_score = min(1.0, avg_daily_volume / 5M) — smooth 0→1
  //   coverage_score = min(1.0, analyst_count / 15)   — smooth 0→1
  //   price_score = min(1.0, stock_price / 50)        — smooth 0→1 (exponential feel at low prices)
  //   earnings_consistency = quarters_with_data / 8   — smooth 0→1
  
  RETURN quality_score < 50 AND X.current_risk_score < 60 AND X.current_total_score >= 55
END FUNCTION
```

### Property Specification — Fix Checking

```pascal
// Property: Fix Checking — Low-quality stocks get demoted
FOR ALL X WHERE isBugCondition(X) DO
  quality_score ← computeQualityScore(X)
  adjusted_score ← F'(X).total_score
  
  ASSERT quality_score < 70
  ASSERT adjusted_score < F(X).total_score
  ASSERT (adjusted_score < 55) OR (F'(X).risk_score >= 60)
  // Low-quality stocks should either have their score reduced below BUY threshold
  // or have their effective risk pushed above the BUY gate
END FOR
```

### Preservation Goal

```pascal
// Property: Preservation Checking — High-quality stocks unaffected
FOR ALL X WHERE NOT isBugCondition(X) DO
  quality_score ← computeQualityScore(X)
  
  ASSERT quality_score >= 70
  ASSERT abs(F(X).total_score - F'(X).total_score) <= 5
  // High-quality stocks should have near-identical scores (within rounding)
END FOR
```
