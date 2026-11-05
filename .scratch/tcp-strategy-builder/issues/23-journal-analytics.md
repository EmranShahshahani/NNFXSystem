# 23: Journal analytics

**What to build:** The trade journal carries the blueprint's fields (timestamp, session, asset, direction, setup type, risk tier, size, leverage, stop, targets, outcome, realised R, MAE, slippage, fees), and the UI shows statistics by setup, session, weekday, asset and risk tier, with a review prompt every 50 trades and a warning against changing rules before 100 forward trades.

**Blocked by:** 08 (Pre-Trade Checklist and candidate journal)

**Status:** ready-for-agent

- [ ] All listed fields are journaled for backtest and paper trades
- [ ] Statistics views per dimension with counts and expectancy
- [ ] Review prompt at every 50 trades; rule-change warning before 100 forward trades
- [ ] API tests for the statistics
- [ ] Trades carry the blueprint journal fields (session, setup type, risk tier, size, leverage, MAE, slippage, fees; spec story 102), noted in ticket 08 review

Spec: `.scratch/tcp-strategy-builder/spec.md`
