# Spec: Strategy Builder with the Trade City Pro (Azizpour) system as its first Template

Status: ready-for-agent

Source of truth for TCP rules: the ten blueprint documents in `docs/sources/tcp-blueprint/`
(videos 1–94 plus the 3-SMA note). Earlier Telegram-derived TCP material is **not** used
for this spec. Vocabulary: `GLOSSARY.md`. Related ADRs: 02 (engine/harness), 08
(reproducibility), 09 (intraday bars, pending orders, fractional exits).

## Problem Statement

The platform can test exactly one hard-wired system (NNFX on daily bars). A trader who
follows Arshia Azizpour's Trade City Pro method, or wants to try a variant of it, cannot
express it here: the method trades 15-minute triggers inside 4-hour and daily structure,
enters only with stop-market orders, sizes from the stop distance with confluence-based
risk tiers, scales out along a profit ladder, and filters by dominance, sessions, oscillator
behaviour and the order book. None of that can be configured, combined or switched off,
and a friend testing the beta cannot build "Arshia's system, but with my own numbers".
Other traders' methods share many of the same building blocks, so the gap is a general
one: there is no way for a user to assemble a strategy from parts, see why it did or did not
trade, and test it honestly.

## Solution

A **Strategy Builder**. A user builds a **Strategy Document** from **Blocks** in a Block
Library (Context, Setup, Confirmation, Execution, Stop, Exit, Risk, Market Filter), each with
editable parameters and published defaults. The document is data, validated before use, and
runs through the same harness as everything else: backtest, paper trading and (later) live.
The first **Template** is "TCP Azizpour", a faithful encoding of the blueprint: clone it, change
any number, switch any rule off, add or remove Blocks, and compare the variant with the
original. For every bar the user can see the Pre-Trade Checklist of each Setup Candidate:
which checks passed, which failed, which Risk Tier it earned, and why an order was or was
not placed. Order-book rules work in paper/live mode from live snapshots and in backtests
only over periods the system has recorded.

## User Stories

### Building and managing strategies
1. As a trader, I want to start from the "TCP Azizpour" Template, so that I begin from the full method instead of an empty page.
2. As a trader, I want to clone a Template into my own Strategy Document, so that I can change it without touching the original.
3. As a trader, I want every number in every Block to be editable with its default shown, so that I know what I changed.
4. As a trader, I want to switch any Block on or off without deleting it, so that I can test the method with and without a rule.
5. As a trader, I want to add Blocks from the library to my strategy, so that I can combine Arshia's rules with others.
6. As a trader, I want to see a diff of my strategy against the Template it came from, so that I remember what makes my variant different.
7. As a trader, I want my strategy validated before it runs (missing timeframes, contradictory settings, impossible values), so that I get a clear error instead of a silent wrong result.
8. As a trader, I want to name, version and duplicate my strategies, so that I can keep several variants.
9. As a trader, I want each saved version to have a stable fingerprint, so that a result always points to the exact rules that produced it.
10. As a trader, I want to export and import a strategy as a file, so that I can share it with a friend.
11. As a trader, I want the builder in Persian and usable on my phone, so that I can work with it anywhere.
12. As a trader, I want each Block to carry a short explanation and a link to the source video, so that I understand what the rule is for.

### Timeframes and market cycles (HWC / MWC / LWC)
13. As a trader, I want to assign the HWC, MWC and LWC timeframes (default weekly/daily, 4H/daily, 15m), so that the method runs top-down.
14. As a trader, I want the HWC trend to set the allowed trade direction, so that I never trade against the macro trend.
15. As a trader, I want LWC counter-moves inside an HWC uptrend to be treated as long opportunities rather than short signals, so that I follow the "don't short the LWC downtrend" rule.
16. As a trader, I want a reversal to require the bottom-up sequence (LWC, then MWC turns, then HWC flattens), so that one 15-minute breakdown never flips my bias.
17. As a trader, I want, when HWC and MWC are both ranging, the option to trade both box edges with fast 2R–3R targets, so that I can use the two-way box rule.
18. As a trader, I want levels to belong to the timeframe they were drawn on, so that a 15m close above a 4H level does not count as a 4H breakout.
19. As a trader, I want to manage open positions on 4H closes after entering on 15m, so that I follow the execution-isolation rule.

### Structure: Dow, levels, boxes, trendlines, Fibonacci
20. As a trader, I want swing highs and lows detected without lookahead, so that Dow trend states (HH/HL, LH/LL) are honest in backtests.
21. As a trader, I want a trend to end only when price fails to make a new high and breaks the neckline, so that I follow the failed-peak rule.
22. As a trader, I want horizontal levels mapped from weekly/daily first and weighted by recency, so that recent tests matter more than old ones.
23. As a trader, I want levels as single prices calibrated to recent candle bodies, not wide zones, so that triggers are precise.
24. As a trader, I want polarity flips (old resistance becomes support), so that broken levels keep working.
25. As a trader, I want touches on a level counted, with first-touch breakouts blocked and second-touch breakouts allowed only with extra confluence, so that I follow the touch-count rule.
26. As a trader, I want boxes detected with their touch counts and volume behaviour inside them, so that box breakouts can be set up automatically.
27. As a trader, I want trendlines that become valid only after the third touch, are anchored from the second swing, fit in a 200-bar window, and fall inside the allowed slope range, so that trendline rules are objective.
28. As a trader, I want Fibonacci retracements anchored only on confirmed structural pivots and only after the impulse has ended, on log scale, so that Fib levels are not hindsight.
29. As a trader, I want Fib levels to count only when at least two other factors meet them (level, SMA 25/99, order-book wall), so that a lone Fib line never triggers.
30. As a trader, I want Fib extensions (1.0, 1.272, 1.618, 2.0) available as targets, so that I can use measured-move exits.

### Trend health
31. As a trader, I want swing-amplitude decay (each leg smaller than the last) to flag trend exhaustion, so that I stop adding continuation entries.
32. As a trader, I want impulse-vs-correction duration ratios measured, so that a trend that needs ever more bars to make a high is flagged weak.
33. As a trader, I want body-to-range ratios and close placement tracked over recent bars, so that absorption shows up before price turns.
34. As a trader, I want the colour ratio of candles over a rolling window, so that rising opposite-colour bars warn me.
35. As a trader, I want a breakout above a trend channel's upper edge treated as exhaustion, not a buy, so that I follow the channel-excursion rule.
36. As a trader, I want climax candles (range and volume far above normal) flagged, so that I take profit instead of buying the spike.

### 3-SMA system
37. As a trader, I want SMA 7/25/99 alignment (price > 7 > 25 > 99, all sloping the same way) as a context Block, so that I only trade aligned trends.
38. As a trader, I want the Choppy Regime detected when the three SMAs flatten and cross repeatedly, so that breakout orders are disabled in chop.
39. As a trader, I want the 99 SMA direction filter (no bullish setups below it, no bearish above it), so that setups respect the macro baseline.
40. As a trader, I want an overextension guard on distance from the 99 SMA, so that I do not start new breakouts in a stretched move.
41. As a trader, I want SMA 7 slope flattening to stop new entries and SMA 25 flattening to trigger profit-taking, so that slope rules manage risk.
42. As a trader, I want SMA crossovers available only as confirmation for holding, never as entries, so that I follow the lag rule.

### Setups
43. As a trader, I want the Candle Setup (wick ≥ 1.5–2× body, small opposite wick, SMA 7 behind the wick and not through the body, SMA 7 sloping my way, in the Second Wave), so that I can trade the flagship entry.
44. As a trader, I want the Candle Setup's RSI condition (RSI 14 entering above 70 for longs, below 30 for shorts) and volume condition (expanding for a new leg, quieter than the impulse for a continuation), so that the full checklist applies.
45. As a trader, I want the Box Breakout setup (≥ 3 touches, volume drying up into the edge), so that I can trade consolidation breaks.
46. As a trader, I want the Engulfing setup (body covers the previous candle's whole range, only after prior weakness), so that I can use the crypto engulfing rule.
47. As a trader, I want the Giant Indecision Reversal setup (range and volume larger than the last 10 bars, entry beyond its opposite side after higher-timeframe weakness), so that I can trade reversals the way the method allows.
48. As a trader, I want the Absorption Wick setup (wick through support that closes back inside), so that I can trade trapped sellers.
49. As a trader, I want the "LA" layered setup (impulse, box, higher low inside the box, faster pushes up than down), so that I can trade it with a stop under the inner higher low.
50. As a trader, I want the 0.382 Fib reclaim fakeout setup, so that sweeps below the 0.382 retracement become long triggers.
51. As a trader, I want the Dow continuation setup (break of the last swing with stop beyond the previous swing), so that pure structure trades are possible.
52. As a trader, I want the BB-on-RSI re-entry setup (RSI dips to its Bollinger mid-line and curls back above in an established trend), so that I can re-enter trends.
53. As a trader, I want the Bollinger squeeze-and-expansion setup and the higher-timeframe-directed Bollinger touches, so that the Bollinger rules are available.
54. As a trader, I want the binary scenario mode (pre-place both a stop-buy above and a stop-sell below a box, each with volume and RSI conditions), so that I trade whichever side breaks without predicting.
55. As a trader, I want the momentum-continuation mode (in strong multi-timeframe momentum, any valid micro-setup triggers), so that I am not left behind in bull runs.

### Confirmation filters
56. As a trader, I want breakout confirmation by body close only (wicks are sweeps), so that fakeouts are filtered.
57. As a trader, I want the volatility filter (breakout candle range ≥ 1.5× the average of the previous 6), so that weak breaks are ignored.
58. As a trader, I want the time filter (N consecutive closes beyond the level: 8 on 15m, 4 on 4H, 2 on daily), so that I can choose slower confirmation.
59. As a trader, I want effort-vs-result checks (high volume with small body = absorption; big body on light volume = vacuum), so that suspicious bars are flagged.
60. As a trader, I want the four-state volume matrix (price/volume up/down) as a filter, so that divergences block entries.
61. As a trader, I want the RSI multi-timeframe cascade (15m, 1H, 4H, daily entering > 70), so that missed entries move up a timeframe and winners are held longer.
62. As a trader, I want oscillators to act only as filters and alerts, never as triggers, so that I follow the master oscillator rule.
63. As a trader, I want the eight oscillator methods available as filter Blocks (overbought/oversold momentum, 50/0 inflection, extreme-zone crossovers with a synthetic half-period signal line, levels and trendlines on the oscillator, Bollinger on RSI, cycle-length recalibration, MF scaling, divergences only with a pivot in the extreme zone), so that any of them can be combined.
64. As a trader, I want MACD rules (ignore near-zero crossovers, histogram deceleration as a profit-taking warning), so that MACD fits the method.
65. As a trader, I want the ROC ceiling filter (4H ROC at its 200-bar extreme disables 15m longs and takes profit) and the ROC box-breakout confirmation, so that I avoid buying exhausted legs.
66. As a trader, I want the ADX/DMI order-type switch (separated DI with rising ADX → stop orders; tangled DI → wait for a body close) and the ADX exhaustion exit (above 45–50 and curling down), so that trend strength shapes execution.
67. As a trader, I want session filters (Asia, London, New York in UTC; no new entries 21:00–00:00 UTC) and the session-regime rules, so that I trade liquid hours.
68. As a trader, I want floor-trader pivots on 4H and weekly as confirmation (beyond R1/S1) and as targets (R3/R4, S3/S4), so that pivot rules are usable.

### Market filters (crypto)
69. As a trader, I want the Dominance Regime (BTC-led, Altseason, Altcoin Flush) from BTC/USDT and BTC.D trends to decide whether I trade BTC or altcoins and in which direction, so that I follow the allocation matrix.
70. As a trader, I want the Relative-Strength Sieve (ALT/BTC breaking out or trending up; optional ALT/ETH or ETH/BTC) to admit an altcoin long, so that I only trade strong altcoins.
71. As a trader, I want a screener (24h volume ≥ 1,000 BTC, positive 24h and 7d performance against BTC) that builds a daily watchlist of at most 3–5 assets, so that the morning routine is automatic.
72. As a trader, I want USDT.D and TOTAL2/TOTAL3 available as context series, so that liquidity flow can be part of the checklist.

### Execution
73. As a trader, I want every entry to be a pending stop-market order at the trigger plus a buffer (setup high + ε for longs, low − ε for shorts), so that price must prove the move.
74. As a trader, I want a pending order cancelled when a candle closes beyond the invalidation level before it fills, so that dead setups never fill.
75. As a trader, I want pending orders to expire after a configurable number of bars, so that stale orders do not linger.
76. As a trader, I want chasing blocked (no entry after an outsized impulse bar), so that stops stay tight and R:R stays high.
77. As a trader, I want a trade skipped automatically when the distance to the next opposing barrier gives less than 2R, so that low-payoff trades are filtered.
78. As a trader, I want, in paper/live mode, the trigger moved just beyond the largest resting ask wall above a resistance (and the mirror for shorts), so that I enter after the wall is cleared.
79. As a trader, I want, in paper/live mode, a breakout aborted when volume contracts as price approaches a heavy wall, so that I avoid bounces off walls.

### Stops
80. As a trader, I want the stop placed at the setup's invalidation (beyond the rejection wick tip, below the inner higher low, beyond the opposite box edge, beyond the previous swing), so that stops are structural.
81. As a trader, I want, in paper/live mode, the stop shielded just behind the nearest persistent bid wall, so that sellers must eat the wall first.
82. As a trader, I want walls that vanish as price approaches classified as spoofs and ignored, so that phantom liquidity does not move my orders.

### Exits and the Profit Chain
83. As a trader, I want a configurable Profit Chain (default 35% at 2R, 40% at 5R, 15% at 10R, 10% runner), so that I can reproduce or change the ladder.
84. As a trader, I want no manual or rule-based full close below 2R, so that winners are not cut early.
85. As a trader, I want the stop moved to breakeven at 2R only if a new structural pivot has formed, so that I follow the conditional breakeven rule.
86. As a trader, I want the Runner trailed behind 4H/daily swing points with no fixed target, so that it can catch 20R–40R moves.
87. As a trader, I want counter-trend trades to disable the Runner and close everything at 2R or the first structural boundary, so that secondary-wave trades stay conservative.
88. As a trader, I want optional exhaustion exits (climax volume, RSI rejected at its upper Bollinger band, ADX curl, SMA 25 flattening, ROC ceiling, pivot R3/R4, Fib 1.618 without momentum), so that I can take profit on exhaustion.
89. As a trader, I want take-profit levels placed just in front of opposing walls in paper/live mode, so that targets fill before the wall stops price.
90. As a trader, I want the futures-to-spot recycling option (on +5R–10R close, record the realised profit as moved to spot), so that the capital-recycling rule is reflected in the equity curve.

### Risk and capital
91. As a trader, I want position size computed from equity × risk ÷ stop distance, with leverage only setting margin, so that leverage never changes risk.
92. As a trader, I want Risk Tiers (0.25%, 0.50%, 0.75%, 1.0%) assigned from the Confluence Score, never above 1%, so that conviction sets size.
93. As a trader, I want the Streak Governor (3 consecutive losses → 0.25%, 5 → 48-hour halt, back to base after a win), so that losing streaks are contained.
94. As a trader, I want a daily loss limit (default −1.5%) that halts trading for 24 hours, and a weekly limit, so that revenge trading is impossible.
95. As a trader, I want a performance governor (rolling 50-trade win rate below 40% or drawdown beyond 6% → 0.25% risk until equity recovers), so that degradation shrinks exposure.
96. As a trader, I want risk recalculated at equity milestones (every ±10%), not every tick, so that sizing is stable.
97. As a trader, I want the Leverage Governor (max leverage < 100% ÷ (stop % × 1.5)) and an order rejected when liquidation would come before the stop, so that liquidation can never hit first.
98. As a trader, I want a hard guarantee that no order ever opens without its stop, so that the "invariable stop" law holds.
99. As a trader, I want anti-martingale behaviour enforced (size never increases after losses), so that losses are never doubled down.

### Checklist, journal and analytics
100. As a trader, I want to see, for every Setup Candidate, the full Pre-Trade Checklist with pass/fail per item and the resulting Risk Tier, so that I know exactly why a trade was or was not taken.
101. As a trader, I want the decision tree (level test → volume → RSI → trigger → management) visible per candidate, so that I can audit the logic.
102. As a trader, I want every trade journaled with the blueprint's fields (timestamp, session, asset, direction, setup type, risk tier, size, leverage, stop, targets, outcome, realised R, MAE, slippage, fees), so that my journal matches the method.
103. As a trader, I want statistics by setup, session, weekday, asset and risk tier, so that I find leaks after every 50 trades.
104. As a trader, I want "justified" versus "unjustified" stops distinguished (stop on a setup that passed the checklist vs one that did not), so that I review rule breaks, not normal losses.
105. As a trader, I want the system to tolerate 6–7 losses in a row without changing rules, and to warn me against changing rules before 100 forward trades, so that I do not overfit to noise.

### Testing and running
106. As a trader, I want to backtest any Strategy Document on any symbol and period I have data for, so that I can see how it would have done.
107. As a trader, I want to compare two strategies (e.g. Template vs my variant) on the same data side by side, so that I see what my changes did.
108. As a trader, I want to run a strategy in paper mode on live Nobitex data, so that I can forward-test it.
109. As a trader, I want alerts when a Setup Candidate appears, a Trigger is placed, fills, or is cancelled, so that I follow the system without watching charts.
110. As a trader, I want to see when a result used order-book rules that were unavailable for that period, so that I never mistake a partial backtest for a full one.
111. As a researcher, I want every backtest of a Strategy Document logged as a Trial with its fingerprint, so that the trial count stays honest.
112. As a researcher, I want the existing gates (no lookahead, determinism, price-scale invariance) applied to every Block, so that no Block leaks the future.
113. As an admin, I want order-book snapshots recorded continuously for chosen symbols, so that order-book rules become backtestable over time.

## Implementation Decisions

- **Strategy Document schema.** A versioned, strict schema: metadata (name, version, parent Template and version), timeframe roles (HWC, MWC, LWC, management timeframe), market universe and Market Filter Blocks, an ordered list of Context, Setup, Confirmation, Execution, Stop and Exit Blocks, and a Risk section. Each Block is `{kind, type, enabled, params}` and is resolved through a registry. Unknown types, unknown parameters and type mismatches are validation errors. The document's content hash is its fingerprint. The schema allows Blocks to reference timeframe roles, not literal timeframes, so a user can re-map roles without editing Blocks.
- **Block Library.** One registry with typed contracts per kind:
  - Context Blocks emit per-bar states (allowed directions, regime labels, flags such as Choppy).
  - Setup Blocks emit Setup Candidates (direction, trigger, invalidation, proposed stop, setup tags, the bar they completed on).
  - Confirmation Blocks evaluate a Setup Candidate to pass / fail / not-applicable, with a weight toward the Confluence Score and a hard-fail flag.
  - Execution Blocks turn an accepted candidate into order intents (buffer, expiry, cancellation, OCO pairs, order-book adjustments).
  - Stop and Exit Blocks act on open positions (initial stop, conditional breakeven, trailing, ladders, exhaustion exits).
  - Risk Blocks size and gate (tiers, governors, leverage).
  Every Block is causal: its value at a bar uses only data closed by that bar on its own timeframe.
- **Multi-timeframe data.** The data layer resamples every timeframe from one base series (15m for the TCP Template; H1 still supported). A higher-timeframe value is visible to a lower-timeframe bar only after the higher bar has closed. MF-scaled indicators are an alternative Block, not a replacement for true resampling.
- **Structure module.** Shared, cached computations used by many Blocks: confirmed swing pivots (confirmed k bars later), Dow trend state per timeframe, horizontal levels with recency weights and touch counts, boxes, trendlines (third-touch activation, 200-bar window, slope bounds expressed in ATR per bar so they are scale-free; the degree-based limits from the source are converted and the conversion is documented), Fibonacci anchors on confirmed pivots in log space, trend-health metrics, candle vector metrics (body, wick asymmetry, colour ratio, peak velocity, range compression).
- **Indicator additions.** SMA slope and entanglement, RSI with Bollinger-on-RSI and synthetic signal line, rolling 200-bar extremes for unbounded oscillators, ROC/MOM, MACD histogram slope, ADX/DMI states, double Bollinger bands and bandwidth squeeze, volume baselines and the four-state matrix, climax detection, volume profile over a window, floor-trader pivots for 4H and weekly, session calendar. Existing indicators are reused where they already match.
- **Strategy Engine.** A new engine family that interprets a Strategy Document and keeps the platform's pure `decide()` contract and journaling. Per bar of the LWC it evaluates Context, runs Setup Blocks, scores candidates through the Pre-Trade Checklist, asks Risk for a tier and a size, and emits intents. It journals one evaluation record per candidate with every check's outcome. It builds on ADR 09: pending stop orders, cancel intents, fractional exits and risk-manager extensions are shared with the H2021/H2026 engines, not duplicated.
- **Order manager.** Pending stop-market orders with buffer, expiry in bars, cancel-on-invalidation-close, OCO pairs for binary scenarios. Fills follow ADR 09: gaps fill at the open; if a stop-loss and a target are both inside one bar, the stop is assumed first.
- **Position manager.** Exit fractions sum to 1. The Profit Chain is a list of `(R multiple, fraction)` steps plus a Runner rule. Breakeven is conditional on a new pivot. Counter-trend mode closes everything at 2R or the first structural boundary. Management can run on a different timeframe from entries (default 4H closes).
- **Risk governor.** Size from equity × tier ÷ stop distance; tier from Confluence Score with a 1% ceiling; Streak Governor, daily and weekly loss limits, performance governor, equity-milestone rebasing, Leverage Governor with liquidation check, and a hard refusal of any entry intent without a stop. All thresholds are parameters with the blueprint defaults.
- **Market context service.** Dominance series (BTC.D, USDT.D, TOTAL2/3) come from imported series (TradingView export) or a provider; pair ratios (ALT/BTC, ETH/BTC) are derived from exchange bars when the cross pair is missing. The screener uses exchange ticker data. Where a series is missing for a period, the Block reports not-applicable and the result is marked incomplete.
- **Order Book Source.** One interface with three providers: live exchange snapshots (Nobitex order book and depth endpoints first), recorded snapshots, and fixtures for tests. A recorder stores snapshots at a configurable interval. Wall detection is relative to the book's own depth distribution and requires persistence across N snapshots; walls that step back or vanish as price approaches are Spoofs. Backtests use recorded snapshots where they exist; otherwise order-book Blocks report not-applicable and the run is flagged as such.
- **TCP Azizpour Template.** A read-only Strategy Document encoding the blueprint defaults: HWC weekly/daily, MWC 4H/daily, LWC 15m; Candle Setup and Box Breakout as primary setups, with the other setups present but disabled; 3-SMA context with the Choppy filter and the 99 filter; RSI 14 momentum confirmation; body-close plus 1.5× six-bar range confirmation; touch-count rule; stop-market triggers with invalidation cancel; structural stops; Profit Chain 35/40/15/10; tiers 0.25–1.0%; Streak Governor 3→0.25%, 5→48h; daily limit −1.5%; Leverage Governor. Each Block records the video(s) it comes from. Where the blueprint gives two values (10R step 15% vs 20%; base risk 0.5% vs tiered), the Template uses the series-summary value and exposes the other as a parameter.
- **API and UI.** Endpoints to list Blocks with their parameter schemas, list Templates, create/clone/update/validate/version Strategy Documents per user, diff against the parent, run backtests and comparisons, start and stop paper runs, and read per-candidate checklists and journals. The Persian, mobile-first builder renders forms from the Block parameter schemas, so new Blocks need no UI code.
- **Research integration.** Every backtest of a Strategy Document records a Trial with the document fingerprint. The frozen H2021/H2026 pre-registration is untouched; the TCP Template is a separate hypothesis family and gets its own pre-registration before any result is used as evidence.
- **New ADR.** Record "Strategy Documents and the Block Library" as ADR 10: documents are data, Blocks are causal and registry-resolved, the engine interprets documents, order-book rules are live-first.

## Testing Decisions

- **Good tests check external behaviour only.** Given a Strategy Document and bars (and, where relevant, order-book snapshots), assert the trades, orders, cancellations, journal records and checklist outcomes. They never assert internal intermediate arrays unless the array is itself a Block's published output.
- **Seam 1: strategy run.** The main seam is the harness: (Strategy Document, bars) → trades and journal, through the backtest harness and the new engine. Each Setup, Confirmation, Execution, Stop, Exit and Risk Block gets hand-built bar fixtures that make the rule fire and not fire (prior art: the hand-built histories in the engine-rule tests and their helpers). The TCP Template gets end-to-end scenario tests: a clean Candle Setup long that fills, ladders out and trails; a setup cancelled by an invalidation close; a first-touch breakout refused; a Choppy regime with no orders; a losing streak that drops risk and then halts.
- **Gates on every Block.** No-lookahead truncation, in-process and cross-process determinism, and price-scale invariance run automatically over the whole Block Library (prior art: the indicator gate tests that iterate the registry).
- **Seam 2: HTTP API.** Create, clone, validate, version, diff, backtest and compare Strategy Documents over HTTP with accounts on (prior art: the UI and beta-auth tests that spin up the server on a free port).
- **Seam 3: Order Book Source.** Wall detection, spoof classification, trigger and stop adjustment are tested with recorded snapshot fixtures (prior art: the fake UDF server in the feed tests). The live provider is tested against the documented response shape, offline.
- **Parity.** Paper mode and backtest produce identical decisions over the same bars (prior art: the parity harness tests).
- **Validation errors** are tested as user-facing messages, in Persian where the UI shows them.

## Out of Scope

- Telegram-derived TCP rules and the 941 extracted calls (not used for this spec).
- Changing the frozen H2021/H2026 pre-registration.
- Real-money order routing to any exchange; the beta is paper-only.
- Macro series (DXY, oil, gold, equities) and economic calendars; they can be added later as Context Blocks.
- TensorCharts-style heatmaps and CVD; only snapshots from available exchange APIs.
- Chart-pattern recognition for named patterns (cup and handle, triangles on price) beyond boxes and trendlines; deferred.
- Psychology and routine guidance that cannot be expressed as a rule (except where it becomes a governor or a warning).
- Timeframes below 15 minutes.

## Further Notes

- The blueprint documents are AI-generated summaries of the videos, not transcripts. Every number is therefore a default parameter, never a hard-coded constant, and each Block cites its video so a user can check the original.
- Internal inconsistencies to expose as parameters, not resolve silently: 10R step 15% (videos 19/20, summary) vs 20% (blueprint §3B); base risk 0.5% with streak cut (video 75) vs tiered 0.25–1.0% (video 7); daily limit −1.5% (video 85) vs "daily and weekly thresholds" without numbers (video 62).
- Degree-based trendline slope limits (20°–60°) depend on chart scaling; the spec uses an ATR-per-bar equivalent and documents the mapping.
- Order-book thresholds from the videos refer to Binance futures depth; on Nobitex they must be relative to the local book.
- The Template becomes useful as evidence only after it has its own pre-registration; before that, its backtests are exploration.
