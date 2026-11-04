# 06: Risk governor

**What to build:** Strategy Documents get a full Risk section: size from equity x risk / stop distance, Risk Tiers from the Confluence Score capped at 1%, the Leverage Governor with a liquidation check, refusal of any entry without a stop, the Streak Governor, daily and weekly loss limits, the performance governor and equity-milestone rebasing. Every refusal is journaled with its reason.

**Blocked by:** 05 (Strategy Document tracer bullet)

**Status:** ready-for-agent

- [ ] Size = equity x tier / stop distance; leverage only sets margin
- [ ] Tier mapping from Confluence Score is a parameter (defaults 0.25/0.50/0.75/1.0%), never above 1%
- [ ] Max leverage < 100% / (stop% x 1.5); an order whose liquidation price is closer than its stop is rejected
- [ ] An entry intent without a stop is refused
- [ ] Streak Governor: 3 consecutive losses -> 0.25%, 5 -> 48h halt, base risk restored after a win (all parameters)
- [ ] Daily loss limit (default -1.5%) halts for 24h; weekly limit parameter
- [ ] Performance governor: rolling 50-trade win rate < 40% or drawdown > 6% -> 0.25% until equity recovers
- [ ] Risk recalculated only at +/-10% equity milestones (parameter)
- [ ] Resting pending orders count against the open-risk and exposure caps (ADR 09 §4 amendment (e); found in ticket 02 review)
- [ ] Harness-level tests for each rule

Spec: `.scratch/tcp-strategy-builder/spec.md`
