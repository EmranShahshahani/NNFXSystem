# Spec — NNFX Engine & Validation Platform

**Produced by:** `/to-spec` (Matt Pocock skills), synthesising docs `01`–`05` of this project.
**Status:** `ready-for-agent`. Rev. 2026-08-31 - added the reproducibility and multi-workstation stories, decisions and notes (ADR `08`).
**Scope:** Build steps 1–5 of Architecture §7 — the parts that require no broker account, no funding and no venue decision.
**Sources:** `01-nnfx-spec-v0.1.md`, `02-nnfx-architecture-v0.1.md`, `03-nnfx-validation-protocol-v0.1.md`, `04-instrument-class-brief-v0.1.md`, `05-indicator-catalogue-v0.1.md`, `08-reproducibility-and-workstations-v0.1.md`.

> **Two deviations from the skill, declared up front.**
> 1. No issue tracker is configured for this project, so this spec is published to the project docs rather than opened as an issue. Run `/setup-matt-pocock-skills` in the implementation repo and this becomes a single `ready-for-agent` issue.
> 2. There is no codebase to explore yet — Emran implements in his own IDE. Repo exploration is replaced by synthesis of the five design documents, which serve as the domain glossary and the ADR set.
>
> **Seams need your confirmation before implementation starts.** See *Testing Decisions §Seams*. That is the one open question this spec deliberately leaves for you.

---

## Problem Statement

I want to trade the No Nonsense Forex system without being the thing that executes it. Today the system exists only as a few hundred hours of video and a set of flow charts. Three things stop me from acting on it:

**I cannot execute it consistently.** NNFX is a daily-bar system across a basket of instruments. Evaluating six indicator slots plus four entry types on 28 pairs, every day, at the same hour, without skipping a signal I dislike the look of, is not something I will do reliably for years. The edge, if there is one, is destroyed by the discretion I would inevitably add.

**I do not know whether the system works.** VP's own validation standard — roughly two years of daily data, rank indicators by win rate, keep the top few — is around two orders of magnitude short of the evidence needed to establish a 0.10R edge, and it optimises a metric the system's asymmetric payoff makes meaningless. I have a set of rules and no idea whether any of them are load-bearing or folklore. I would be funding a belief, not a finding.

**Even if I built it, I could not trust it.** The characteristic failure of retail algo trading is a backtest and a live bot that quietly disagree — different session boundaries, different indicator implementations, a state bug after a restart, a duplicate order after a network timeout. By the time the disagreement surfaces, it has cost money.

And the system's whole design premise is that its six components are *replaceable*. If swapping the confirmation indicator means editing decision logic, the system is unmaintainable and every research question becomes a code change.

## Solution

A Python system in two halves that share one brain.

**The brain** is a pure `StrategyEngine`. Given history, open positions, account state and a config, it returns order intents. It performs no I/O, reads no clock, and does not know whether it is in 2011 or live. Every NNFX rule lives here and nowhere else, and every *structural* rule — the bridge-too-far filter, the 7-candle rule, the 1-Candle Rule, continuation entries — is a boolean flag rather than a hard-coded assumption, so each can be measured for whether it earns its place.

**The two halves** are harnesses, not implementations. The backtest harness drives the engine over history; the live harness drives it once a day. Because they feed the same object, "the live bot disagrees with the backtest" stops being possible by construction rather than by discipline. Parity is then a test, not a hope.

Around the brain sit four replaceable boundaries. Every indicator is wrapped so it emits a normalised contract — a line, a signal, a state, a boolean gate — and the engine sees only that contract, so swapping KAMA for a Kijun-sen is a config line. Every venue sits behind a `Broker` protocol that declares *capabilities* (`can_short`, `has_funding`, `size_step`, `supports_hedging`) rather than a market name, so forex and crypto perpetuals run the same engine. Every bar arrives through a data layer that applies the session-close convention once, in one place. Every decision is journaled, so a crashed process resumes exactly where it stopped and live can be reconciled against backtest bar by bar.

**The second half of the solution is the verdict.** A research toolkit runs the pre-registered acceptance criteria — bootstrap confidence interval on expectancy, Deflated Sharpe against a logged trial count, Probability of Backtest Overfitting, walk-forward efficiency, a random-combination control, a cost-stress run at 1.5× — and returns pass or fail against thresholds frozen before any performance number is seen. A fail is a legitimate, planned outcome and still produces something worth having: a clear account of which of VP's rules are real.

What I get at the end of this spec is not a live trading bot. It is a machine that can honestly answer whether one is worth building, plus the engine that would become it.

---

## User Stories

**Configuration and modularity**

1. As a system operator, I want the entire system's behaviour defined by a single configuration file, so that two configs differing only in their `slots` block are literally two different trading systems.
2. As a researcher, I want to change the indicator in any of the six slots by editing a config line, so that testing a new confirmation indicator never requires touching decision logic.
3. As a researcher, I want every structural rule exposed as a boolean flag (`bridge_too_far`, `seven_candle_rule`, `one_candle_rule`, `continuation`), so that I can ablate each one without a code change.
4. As a researcher, I want rule *parameters* exposed as config values (`bridge_multiple`, `seven_candle_bars`), so that I can test whether 1.0×ATR and 7 bars are special or arbitrary.
5. As a system operator, I want the instrument basket and per-symbol overrides in their own config, so that changing the universe is not a code change.
6. As a system operator, I want venue profiles in separate config files, so that the same system config can be pointed at a different broker.
7. As a maintainer, I want every configuration validated against a strict schema at load time, so that a typo in a slot name fails immediately rather than silently disabling a filter.

**Data**

8. As a researcher, I want raw feeds normalised into a single strict bar schema — UTC-indexed OHLCV, no gaps, no duplicate timestamps, no partial final bar — so that every downstream module can assume clean input.
9. As a researcher, I want the daily session-close convention applied in exactly one place in the data layer, so that no downstream code ever re-times a bar.
10. As a researcher, I want `session_close_tz` and `close_hour` as config values with D1 bars resampled from H1, so that I can measure how sensitive the whole system is to where the trading day is cut.
11. As a researcher, I want forex Sunday partial bars merged into Monday during normalisation, so that broker-specific week boundaries do not leak into signals.
12. As a researcher, I want automated integrity gates that run before any research — duplicate/out-of-order timestamps, non-positive prices, high < low, calendar gap detection, daily-return outlier flags, volume sanity — so that I never analyse a corrupted series.
13. As a researcher, I want forex bars sourced from Dukascopy H1 and cross-checked against a second free source on a sample of dates, so that feed-specific artefacts are caught before they become findings.
14. As a researcher, I want crypto bars sourced through `ccxt` from a major exchange and cross-checked against a second exchange for the same symbol, so that venue-specific artefacts are caught the same way.
15. As a researcher, I want the crypto universe reconstructed point-in-time — ranked by trailing liquidity using only data available at each rebalance date — so that I am not backtesting today's survivors against a decade they did not all survive.
16. As a researcher, I want delisted coins retained in the dataset with positions force-closed at the last valid price, so that dropping them cannot inflate results.
17. As a researcher, I want any splice between spot price history and perpetual history explicitly marked in the data, so that spliced-period results are reported separately and never silently pooled with native-perp results.
18. As a researcher, I want tick-volume-derived series flagged as such wherever the volume slot consumes them, so that a known structural weakness of the forex branch is visible in every report that depends on it.

**Indicators**

19. As a researcher, I want every indicator registered by name and instantiated from config parameters, so that the candidate pool is data rather than code branches.
20. As a maintainer, I want each indicator wrapper to own the translation from its native output — a histogram, a colour change, a band crossing — into the normalised contract, so that the engine only ever sees `line`, `signal`, `state`, `gate` or `value`.
21. As a researcher, I want an automated no-lookahead gate that recomputes each indicator on truncated history and asserts the tail values are unchanged, so that repainting implementations are eliminated before they produce a beautiful backtest.
22. As a researcher, I want the no-lookahead gate run against the exact implementation that will ship rather than against the indicator's reputation, so that a repaint introduced by one library's version of a well-behaved concept is still caught.
23. As a researcher, I want a determinism gate asserting identical output across runs and restarts, so that hidden state cannot leak into results.
24. As a researcher, I want a signal-frequency gate rejecting any C1 outside 6–50 signals per instrument-year, so that indicators that fight the 1.5×ATR / 1.0×ATR barrier geometry are removed before performance testing.
25. As a researcher, I want a C1/C2 independence gate enforcing 0.15 ≤ ρ ≤ 0.60 on pooled `state` series over the development set only, so that a redundant C2 and a near-random C2 are both rejected — the second of which would otherwise raise win rate while flattening expectancy.
26. As a researcher, I want a parameterisation gate rejecting indicators with magic constants tuned to a specific market's price scale, so that a candidate cannot silently stop working when it crosses from forex to crypto.
27. As a researcher, I want gate results recorded as pass/fail with no performance data consulted, so that screening cannot become a covert first round of selection.
28. As a researcher, I want indicators carrying absolute thresholds re-expressed in percentage or ATR-relative terms before use in crypto, so that a three-order-of-magnitude price range does not disable them.

**Entry logic**

29. As a trader, I want all logic evaluated on the completed bar and orders placed at the open of the following bar, so that the backtest models something I could actually have executed.
30. As a trader, I want a standard entry to require C1 firing in the direction, baseline agreement, distance within 1×ATR, C2 agreement and the volume gate, so that the core NNFX entry is implemented exactly as the flow charts state it.
31. As a trader, I want a baseline entry triggered by a fresh baseline cross with C1 already in-state and its last signal no more than 7 bars old, so that I can take a trend that resumes without a new trigger but not one confirmed by a stale signal.
32. As a trader, I want a pullback entry that arms when every condition except the 1×ATR distance filter is met and expires after exactly one bar, so that extended setups get one chance to come back and no more.
33. As a trader, I want a continuation entry that requires an uncrossed baseline, a continuation signal and C1 still in-state, with bridge-too-far and the 1-Candle Rule explicitly not applied, so that adding to a running trend is not blocked by a filter designed for fresh entries.
34. As a researcher, I want both readings of the 1-Candle Rule implemented behind flags — 1CR-A as a one-bar grace period for a single lagging condition, 1CR-B as a required retracement — and both defaulting to off, so that an ambiguity with no canonical definition is settled by measurement rather than by argument.
35. As a researcher, I want the 7-candle rule's inclusivity treated as a configurable off-by-one, so that its sensitivity can be tested rather than assumed.
36. As a trader, I want C2 checked as a `state` (agreement) rather than a `signal` (firing) by default, with the alternative testable, so that the flow charts' reading is the default but not the only thing I can measure.

**Exits and money management**

37. As a trader, I want a position closed on the first of: baseline cross against the position, exit indicator firing, opposite C1/C2 signal where no exit indicator is configured, or stop/target being hit — so that exit precedence is deterministic rather than order-of-evaluation dependent.
38. As a trader, I want no re-entry on the same bar as an exit, so that the system cannot churn within a single decision.
39. As a trader, I want each entry to open two positions, each risking 1% of equity, so that the system's characteristic payoff — one position taking a fixed target, one running — is preserved.
40. As a trader, I want both positions stopped at 1.5×ATR from entry and position 1 targeted at 1.0×ATR, so that risk and first target follow the specified geometry.
41. As a trader, I want position 2's stop moved to breakeven when TP1 is hit, and then trailed at 1.5×ATR in 0.5×ATR steps of favourable movement, so that the runner is managed as specified.
42. As a trader, I want ATR frozen at entry for stop, target and sizing, with recalculated-ATR testable as an alternative, so that the more conservative reading ships and the other is measured.
43. As a researcher, I want the trailing stop's use of frozen versus live ATR to be a separate toggle from the entry freeze, so that A3 and A11 are resolved independently.
44. As a trader, I want position size derived from risk cash, stop distance and an instrument-supplied `value_per_price_unit`, so that no pip value is ever hard-coded.

**Risk and portfolio**

45. As a trader, I want a sizing quantization guard that computes realised risk after rounding to the broker's lot step and rejects the trade when it deviates from target beyond tolerance, so that a small forex account cannot silently corrupt the risk model.
46. As a trader, I want a correlated-exposure cap limiting simultaneous positions per currency, so that EURUSD, GBPUSD and AUDUSD firing long is recognised as one 6%-risk short-USD bet rather than three 2% bets.
47. As a trader, I want the crypto analogue of that cap expressed in BTC-beta-weighted terms rather than by counting positions, so that five altcoin longs are not mistaken for five independent bets.
48. As a trader, I want a leverage constraint keeping the liquidation price beyond 3×ATR from entry, with a violation blocking the order as a sizing bug, so that the 1.5×ATR stop is always the binding exit and liquidation is unreachable in normal operation.
49. As a trader, I want funding accrued as a running, long/short-asymmetric per-position cost and surfaced in reporting, so that carry is never misattributed as signal quality.
50. As a trader, I want a kill switch evaluated before every order that halts new entries on a drawdown breach while managing existing positions to their exits rather than dumping them, so that a bad run stops the system without a forced liquidation of its own making.
51. As a system operator, I want the kill-switch threshold to be a config value I approve, derived from the bootstrap drawdown distribution rather than chosen by feel, so that it sits above normal bad luck and below unrecoverable.

**Engine, harnesses and journal**

52. As a maintainer, I want the engine to be a pure function performing no I/O and reading no clock, with time, randomness and network injected, so that it is fully unit-testable without a broker or a data connection.
53. As a maintainer, I want the same engine object driven by both the backtest harness and the live harness, so that a backtest/live divergence is a bug in a harness rather than a difference of implementation.
54. As a maintainer, I want a backtest run twice to produce byte-identical results, so that determinism is a checked property rather than an intention.
55. As a maintainer, I want per-symbol engine state modelled as an explicit state machine (`FLAT`, `PENDING_PULLBACK`, `IN_TRADE`, `RUNNER_BE`, `TRAILING`) with `PENDING_PULLBACK` carrying an explicit expiry bar, so that setup lifetime is represented rather than inferred.
56. As a maintainer, I want engine state serialised to the journal on every evaluation, so that a killed process resumes exactly where it left off.
57. As a maintainer, I want each evaluation to journal the inputs seen, the indicator values computed and the intents produced, so that any decision can be reconstructed and reconciled after the fact.
58. As a system operator, I want every order to carry a deterministic idempotency key derived from symbol, signal-bar timestamp and position index, so that a retry after a timeout can never create a duplicate position.
59. As a system operator, I want the live harness to reconcile the journal's expected positions against the broker's reported positions before acting, and to halt and alert on any divergence, so that the system never trades on a false picture of the account.
60. As a system operator, I want the daily cycle to run once shortly after session close — fetch, verify, load state, evaluate, size, reconcile, submit, journal, report — so that a daily system does exactly one thing per day, correctly.
61. As a system operator, I want a daily report covering decisions made, orders placed, open risk, equity versus backtest expectation and any rule that blocked a trade, produced even on days nothing happened, so that silence is never mistaken for success.

**Venue abstraction**

62. As a maintainer, I want the engine to branch only on instrument capability flags and never on a market name, so that adding a market is adding an `InstrumentSpec`, not a code path.
63. As a maintainer, I want `supports_hedging=False` handled explicitly by expressing the two-position structure as one position with a partial close, so that a FIFO/no-hedging venue is adapted to rather than silently misbehaved on.
64. As a maintainer, I want `stop_trigger_price` declared per instrument and stop triggering modelled on mark price where the venue uses it, so that wick behaviour in the backtest matches the exchange and does not surface later as a parity failure.
65. As a researcher, I want a backtest broker with explicit spread, commission, carry (swap or funding) and slippage models, with slippage applied to stop fills and gap risk modelled rather than assuming perfect execution, so that costs are in the result from the first run rather than bolted on later.
66. As a researcher, I want crypto slippage scaled to instrument depth, so that an altcoin is not assumed to fill like BTC.
67. As a researcher, I want the long-only spot variant expressible by disabling short entries via a rule flag, so that the safer, simpler instrument class can be benchmarked against perpetuals at near-zero extra cost.

**Validation**

68. As a researcher, I want data partitioned into development, validation and holdout segments with distinct periods per market, so that the evidence standard is structural rather than remembered.
69. As a researcher, I want the holdout enforced as touch-once with every access logged, so that it cannot quietly degrade into a second development set.
70. As a researcher, I want a 