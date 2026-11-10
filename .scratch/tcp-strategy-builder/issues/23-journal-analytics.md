# 23: Journal analytics

**What to build:** The trade journal carries the blueprint's fields (timestamp, session, asset, direction, setup type, risk tier, size, leverage, stop, targets, outcome, realised R, MAE, slippage, fees), and the UI shows statistics by setup, session, weekday, asset and risk tier, with a review prompt every 50 trades and a warning against changing rules before 100 forward trades.

**Blocked by:** 08 (Pre-Trade Checklist and candidate journal)

**Status:** resolved

- [x] All listed fields are journaled for backtest and paper trades
- [x] Statistics views per dimension with counts and expectancy
- [x] Review prompt at every 50 trades; rule-change warning before 100 forward trades
- [x] API tests for the statistics
- [x] Trades carry the blueprint journal fields (session, setup type, risk tier, size, leverage, MAE, slippage, fees; spec story 102), noted in ticket 08 review

Spec: `.scratch/tcp-strategy-builder/spec.md`

## Resolution

`strategy/analytics.py` (`JournalRow` per closed position, `statistics` per setup/session/weekday/asset/risk tier, `review_status`: prompt from 50 trades, rule-change warning below 100 forward trades, losing-streak note), `targets` journaled in the candidate record, `journal`/`stats`/`review` in `/api/strategy/backtest`, `GET /api/paper/journal`, journal block in the backtest result and paper tab, ADR 10 §27. Notes: MAE needs bars (None without them); the review prompt is stateless (no "reviewed" acknowledgement); the 100-trade count counts only paper trades.
