# Probability Calibration Feature

## Status
Draft — awaiting review

## Problem Statement

The trade detail modal currently displays a field called **"Combined Probability"** that is computed as a simple average:

```python
combined = (bot_win_rate + our_confluence) / 2.0
```

This number:
- Has no statistical basis
- Is not calibrated against actual outcomes
- Mixes two incomparable metrics (a claimed human win rate vs an internal heuristic score)
- Is displayed as if it were a probability, leading to misplaced confidence

**Example from a real trade:**
- Bot win rate: 69.0%
- Our confluence: 0.399 (adaptive score for 2 agreeing signals)
- Modal shows: `prob 54.4%`
- This is not a probability. It is a heuristic score presented as one.

## Current Data Asset

The project already captures every trade decision in `data/decisions.jsonl`:
```json
{
  "cycle_id": "...",
  "pair_api": "USDZAR_otc",
  "bot_win_rate": 0.69,
  "our_confluence_score": 0.399,
  "our_signal_breakdown": { ... },
  "agreement": true,
  "combined_probability": 0.544,
  "decision": "TRADE",
  "outcome": "win",
  "pnl": 2.90,
  "payout_pct": 92,
  ...
}
```

This dataset is the foundation for building a real probability model.

## Proposed Solution: Calibrated Probability Model

### Phase 1 — Rename & Clarify (Immediate)

Rename `combined_probability` → `confidence` throughout:

- [ ] `strategy/decision.py` — rename field, keep formula
- [ ] `strategy/trade_logger.py` — rename dataclass field
- [ ] `dashboard/web/js/components/history.js` — update modal display
- [ ] `dashboard/analytics.py` — update API response
- [ ] Tests — update assertions
- [ ] Docs — update any references

**Display text change:**
- Before: `prob 54.4%`
- After: `confidence 54.4%`

### Phase 2 — Build Calibrator (Short-term)

Create a new module: `strategy/probability_calibrator.py`

**Inputs (features):**
- `bot_win_rate` (float 0–1)
- `our_confluence` (float 0–1)
- `agreement` (bool)
- `agreeing_signals` (int 0–5)
- `payout_pct` (float)
- `bot_is_top_pick` (bool)
- `pair_api` (categorical — one-hot or embedding)

**Model:**
- Simple logistic regression (scikit-learn)
- Or: beta-binomial if sample sizes are small
- Predicts: actual P(win) based on historical outcomes

**Training pipeline:**
1. Read `data/decisions.jsonl`
2. Filter to records with known `outcome` (win/loss)
3. Fit model on features → binary outcome (win=1, loss=0)
4. Save model to `data/models/probability_calibrator_v1.pkl`
5. Log calibration metrics (accuracy, log-loss, AUC)

**Inference:**
- `decide()` calls `calibrator.predict(features)` instead of the simple average
- Returns a real, calibrated probability
- Falls back to simple average if model is absent

### Phase 3 — Continuous Learning (Medium-term)

- Nightly cron job re-reads `decisions.jsonl`, re-trains model
- Versioned models: `probability_calibrator_v1.pkl`, `v2.pkl`, etc.
- A/B testing: compare simple average vs calibrated model over time
- Dashboard update: show both `confidence` (heuristic) and `probability` (calibrated)

## Additional Notes

### Dependencies
- `scikit-learn` — added to `requirements.txt`
- `pandas` — already available
- No new runtime dependencies beyond model loading

### Backwards Compatibility
- Keep `combined_probability` in data schema for existing analytics
- Introduce `calibrated_probability` as new field
- Gradually deprecate the old field

### Testing
- Unit test: calibrator returns values in [0, 1]
- Unit test: calibrator falls back to average when model missing
- Integration test: full pipeline from `decide()` → modal display
- Backtest: train on first 80% of data, test on last 20%, report AUC

## Acceptance Criteria

- [ ] Phase 1 complete: all UI/API references renamed from "probability" to "confidence"
- [ ] Phase 2 complete: `strategy/probability_calibrator.py` exists and produces calibrated predictions
- [ ] Calibration model achieves AUC > 0.55 (better than the baseline average)
- [ ] Modal shows both `confidence` and `calibrated_probability` where available
- [ ] Nightly retraining script is documented and runnable
- [ ] All tests pass

## References

- `strategy/decision.py` — current `decide()` function
- `strategy/trade_logger.py` — `DecisionRow` dataclass
- `signals/confluence.py` — confluence scoring engine
- `dashboard/web/js/components/history.js` — modal rendering
- `data/decisions.jsonl` — training data source

---
*Document written 2026-06-08 after fixing min_signal_agreement bug (commit 8e0b86c)*
