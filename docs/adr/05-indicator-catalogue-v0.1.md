# NNFX Indicator Catalogue & Selection Procedure (v0.1)

**Companion to:** `01` spec, `02` architecture, `03` validation protocol
**Purpose:** The candidate pool for each slot, the normalization each candidate needs to satisfy the engine's contract, the screening gates every candidate must pass *before* performance testing, and the procedure for getting from ~70 candidates to one configuration without overfitting.

---

## 1. The combinatorial problem — read this first

This is the single most dangerous document in the project, because it is where the trial count explodes.

A modest pool of 15 baselines × 15 C1 × 15 C2 × 12 volume × 12 exit is **486,000 configurations**. Testing all of them and keeping the best is not research; it is a guaranteed way to find a configuration that fits history perfectly and predicts nothing. With that many trials, the best backtest in the set will look excellent *even if every indicator is pure noise*.

Three constraints follow, and they govern everything below:

1. **Staged reduction, never exhaustive search.** Slots are narrowed sequentially, with the surviving shortlist kept small.
2. **Every trial is counted and logged.** The final result is judged against the total number of configurations examined, via the Deflated Sharpe Ratio (`03` §5.3). An untracked trial count makes the DSR meaningless.
3. **A random-combination control.** Alongside the selected configuration, evaluate a sample of *randomly assembled* configurations from the same pool. If the carefully selected one doesn't clearly beat the random distribution, the selection procedure has no skill — and that finding matters more than any backtest.

Staged selection has its own bias: the best C1 in isolation is not necessarily the C1 in the best complete system. That bias is accepted deliberately, in exchange for a trial count small enough to be statistically defensible. The trade is documented rather than hidden.

---

## 2. Screening gates — applied before any performance test

A candidate that fails any gate is removed from the pool regardless of how well it backtests.

**Gate 1 — No lookahead (automated, mandatory).**
Recompute the indicator on history truncated at bar *t*, and compare the tail values against the same indicator computed on full history. Any difference means the indicator uses future information. This kills repainting indicators, which are the number-one source of beautiful backtests that fail live.

Repainting is usually an *implementation* property, not a property of the concept — the same indicator name may repaint in one library and not another. So the gate is run against the exact implementation that will ship, never assumed from the indicator's reputation. Families that warrant extra scrutiny: anything with centred or displaced smoothing, zig-zag or pivot-based logic, anything reconstructing swing highs/lows, and DSP filters whose published forms are non-causal.

**Gate 2 — Determinism.** Same input, same output, across runs and across restarts. No hidden state.

**Gate 3 — Signal frequency band. FINAL: 6 to 50 signals per instrument-year for C1.** Target zone 12–35.

*Derivation of the upper bound.* The bound is set by the trade's own timescale. Position sizing uses a 1.5×ATR stop and a 1.0×ATR first target. Daily close-to-close standard deviation runs roughly 0.6–0.7×ATR, so the barriers sit about 2.2σ and 1.5σ away. For a driftless random walk the expected two-barrier hitting time is approximately `(b₁/σ)(b₂/σ)` steps — here about 3.5 bars, with real trades typically resolving in 4–10 bars once drift and trends are included. An indicator firing 50 times a year flips every ~5 trading days, which is *inside* that resolution window: the exit rule "opposite C1 signal" would routinely close trades before they resolve either way. Above 50, the indicator is fighting the position sizing rather than informing it.

*Derivation of the lower bound.* Filters downstream of C1 (baseline agreement, C2, volume gate, bridge) pass roughly 10–20% of raw signals. Below ~6 signals per instrument-year, a 15-instrument universe yields under one trade per instrument-year after filtering — too few to evaluate, and too few to reach the sample floor in §8 of `03` within the available history.

**Gate 4 — C1/C2 independence. FINAL: 0.15 ≤ ρ ≤ 0.60**, computed on the `state` series, pooled across instruments, development set only.

This is a **band, not a ceiling** — my earlier provisional value only had an upper bound, and that was wrong. Both ends bite:

For two ±1 state series, `ρ = 2 × (fraction of bars in agreement) − 1`. So:

- **ρ = 0.60 ↔ 80% agreement.** C2 vetoes only one C1 signal in five, and much of that overlap is already caught by the baseline and volume filters. Above this, C2 is decoration — it adds trial count and reduces trades without adding information.
- **ρ = 0.15 ↔ 57.5% agreement.** *Below* this, C2 is barely tracking trend direction at all. It then behaves as a near-random filter that removes roughly half your trades for no informational reason — which raises win rate cosmetically (fewer, luckier trades) while leaving expectancy flat or worse. A too-independent C2 is as bad as a redundant one, and it fails in a way that looks like success on VP's own preferred metric.

Negative ρ is pathological and rejects immediately.

**Gate 5 — Parameterisation.** Exposes its parameters for the grid; no magic constants tuned to a specific market's price scale.

---

## 3. Baseline candidates

**Contract:** emits a line. `state = sign(close − line)`. Also serves as the distance reference for the bridge-too-far filter, so it must be a *smooth, meaningful level* — not a fast oscillator.

| Candidate | Family | Character |
|---|---|---|
| KAMA | Efficiency-ratio adaptive MA | VP's own reference. Adapts smoothing to trendiness. |
| ALMA | Gaussian-weighted MA | Low lag, low noise. Strong general performer. |
| HMA | Hull MA | Very low lag; overshoots at turns. |
| T3 (Tillson) | Multi-smoothed EMA | Smooth, tunable curvature. |
| VIDYA | CMO-adaptive MA | Volatility-adaptive. |
| McGinley Dynamic | Adaptive tracker | Designed to hug price without lag. |
| TEMA / DEMA | Multi-smoothed EMA | Lower lag than EMA, noisier. |
| **Kijun-sen** | Midpoint of N-bar range | **Not a moving average.** Flat in ranges, steps in trends. Genuinely different personality — valuable for pool diversity. |
| Donchian midline | Range midpoint | Same non-MA logic, simpler. |
| SSL Channel | HL-MA channel | Discrete side flips; check the implementation for repaint. |
| Range Filter | Volatility-banded | Noise-suppressing; verify causality carefully. |
| Ehlers filters (Gaussian, super-smoother) | DSP | Excellent lag/smoothness trade-off; several published forms are non-causal — Gate 1 is essential here. |

**Diversity note:** the list is MA-heavy. Kijun-sen, Donchian midline and SSL are the genuinely different mechanisms and should be over-represented in the shortlist rather than dropped early for being unfamiliar.

---

## 4. C1 — primary confirmation

**Contract:** `signal ∈ {−1,0,+1}` on the bar it fires; `state ∈ {−1,+1}` continuously. Fast, decisive, tolerant of some false signals.

| Candidate | Family | Notes |
|---|---|---|
| Schaff Trend Cycle | Cycle-adjusted MACD | Community favourite; fast, oscillator-bounded |
| Coral Trend | Smoothed trend line | Clean flips |
| SuperTrend | ATR band | Non-repainting by construction; ATR-based, so it interacts with the ATR slot |
| Half Trend | Adaptive band | Popular; **implementations vary in repaint behaviour** |
| Aroon Up/Down | Time-since-extreme | Genuinely different mechanism — no price averaging |
| Vortex Indicator | Directional movement | Different family from most of this list |
| QQE | Smoothed RSI + ATR bands | Two-line cross |
| Wave Trend | Channel oscillator | Fast |
| TDFI (Trend Direction Force Index) | Force/momentum | Often used as C1 or volume |
| Kase Permission Stochastic | Stochastic derivative | Smoothed, fewer whipsaws |
| Fisher Transform | Distribution transform | Sharp turns, noisy |
| Ergodic TVI | Momentum | |
| Trend Trigger Factor | Range comparison | Non-MA logic |
| Laguerre RSI | Laguerre-filtered RSI | Very low lag |
| CMO (Chande Momentum) | Momentum | Simple, well-understood |
| MACD / DiNapoli MACD | MA convergence | The baseline case to beat |
| SMI (Stochastic Momentum) | Stochastic derivative | |
| TTM Trend | Bar-colour trend | |

---

## 5. C2 — secondary confirmation

**Contract:** `state` only — it must *agree*, it need not *fire* (Spec ambiguity A4).

The pool is the same as C1, but selection differs in two ways: C2 should be **slower or more selective** than the chosen C1, and it **must come from a different family** (Gate 4). In practice, if C1 is a stochastic derivative, C2 should be a directional-movement or range-based indicator rather than another oscillator.

Additional candidates that suit a state-only, slower role: ADX with DI cross, Ichimoku cloud position, Elder Impulse, a long-period Vortex, or a slow SSL.

**The question the ablation study must answer honestly:** does C2 add expectancy, or does it merely reduce trade count? Halving the number of trades will usually raise win rate while leaving expectancy flat or worse. Win rate is exactly the metric that makes this look like an improvement, which is why `03` refuses to optimize on it.

---

## 6. Volume / volatility gate

**Contract:** `bool` per bar — is there enough force behind this move?

| Candidate | Measures |
|---|---|
| Waddah Attar Explosion | MACD-derived momentum vs Bollinger-derived volatility. The community default. |
| VPCI (Volume Price Confirmation) | Whether volume confirms the price move |
| Damiani Volatmeter | Trend vs noise regime |
| ADX / ADXm | Trend strength, direction-agnostic |
| Normalized Volume | Volume relative to its own recent average |
| Volume Zone Oscillator | Directional volume |
| Chaikin Money Flow | Accumulation/distribution |
| Money Flow Index | Volume-weighted RSI |
| Klinger Volume Oscillator | Volume force |
| OBV slope | Cumulative volume trend |
| Bollinger Bandwidth | Volatility expansion |
| Choppiness Index (inverted) | Trending vs ranging |
| Vertical Horizontal Filter | Trending vs ranging |

**Critical market difference.** In forex, "volume" is *tick volume* — a count of price updates, not traded size. Every volume-based indicator in FX is therefore a proxy of a proxy, and this is a known structural weakness of the slot in the market NNFX was designed for. **In crypto, exchange volume is genuine traded size.** The Volume slot is better founded in crypto than in FX, which is a real and under-appreciated argument for the crypto branch.

Two crypto cautions: use volume from the *same venue* as the price series, and prefer major venues — reported volume on lower-tier exchanges is contaminated by wash trading.

---

## 7. Exit

**Contract:** `signal ∈ {exit_long, exit_short, none}`. Should be *faster* than the entry logic — giving back open profit is the cost of a slow exit.

| Candidate | Notes |
|---|---|
| Parabolic SAR | Classic trailing exit; whipsaws in chop |
| Chandelier Exit | ATR-based trailing from extreme |
| SuperTrend (fast settings) | ATR band, non-repainting |
| Half Trend (fast) | Check repaint |
| SSL (fast period) | Discrete flips |
| Rex Oscillator | Candle-body based |
| MACD signal cross | Simple, well-understood |
| QQE exit | |
| Braid Filter | Three-MA convergence/divergence |
| Aroon exit | |
| Waddah Attar dead zone | Exits when volatility collapses |
| Faster copy of the chosen baseline | Structurally coherent with the entry logic |

**Interaction warning:** the exit indicator overlaps with the ATR trailing stop from Spec §7. Two mechanisms competing to close the same position must be tested *jointly* — an exit indicator that looks excellent alongside no trailing stop may be redundant or actively harmful alongside one. Ablate the pair, not each alone.

---

## 8. ATR / volatility unit

Least glamorous slot, largest blast radius: it sets every stop, every target, and every position size.

| Candidate | Notes |
|---|---|
| **ATR(14), Wilder** | Canonical. The default and the benchmark. |
| ATR with SMA smoothing | Common variant; different responsiveness |
| ADR (Average Daily Range) | Simpler, ignores gaps |
| Keltner channel width | ATR derivative |
| Parkinson / Garman-Klass / Yang-Zhang | Range-based volatility estimators — statistically more efficient than ATR, and Yang-Zhang handles overnight gaps properly. Worth testing; none are traditional in NNFX. |

**On percentage vs absolute ATR in crypto — a precise statement, because this is widely got wrong.**

The core mechanics are *already scale-invariant*: the stop (`1.5 × ATR`), the bridge filter (`|close − baseline| ≤ ATR`) and position sizing (`risk / (1.5 × ATR × value_per_unit)`) all compare price units to price units. BTC moving from $200 to $100,000 across the sample does **not** break them.

Where absolute ATR *does* break down:

- **Cross-sectional comparison** — ranking instruments by volatility for universe selection and exposure caps
- **Regime classification and reporting** across a sample spanning three orders of magnitude in price
- **Any indicator carrying an absolute threshold** — these must be re-expressed in percentage or ATR-relative terms before crossing from FX to crypto, or they silently stop working

So: keep absolute ATR in the trade mechanics, and use percentage ATR (`ATR / close`) for analysis, universe construction, and any threshold that would otherwise be price-scale-dependent.

---

## 9. Parameter policy

- **Start from published defaults.** They carry no in-sample fitting from this project.
- **Small grids only** — typically 3–5 values per parameter, spanning a sensible range rather than a fine sweep. Every grid point is a counted trial.
- **Plateaus, not peaks** (`03` §5.6). A configuration whose neighbours perform poorly is a fitting artefact, regardless of how good the peak looks.
- **Never tune parameters per instrument.** One parameter set across the whole universe. Per-instrument tuning multiplies the trial count by the number of instruments and is the fastest route to a curve-fitted portfolio.

---

## 10. Selection procedure

| Stage | Action | Trials |
|---|---|---|
| 0 | Run all candidates through Gates 1–5 | 0 — pass/fail, no performance data touched |
| 1 | **C1 in isolation.** Each survivor tested alone against the naked ATR exit (VP's screening method, with our metrics). Rank by expectancy in R, not win%. | ~18 × grid |
| 2 | **Shortlist 5 C1 candidates.** Not the top 5 by point estimate — the top 5 by *lower confidence bound*, which penalises small-sample flukes. | — |
| 3 | **Baseline sweep** against each shortlisted C1 | ~12 × 5 |
| 4 | **C2 sweep**, Gate-4 filtered against the chosen C1 | reduced pool × survivors |
| 5 | **Volume gate sweep** | ~13 × survivors |
| 6 | **Exit sweep**, jointly with trailing-stop on/off (§7) | ~12 × 2 × survivors |
| 7 | **Rule ablation** (`03` §6) on the surviving 2–3 configurations | ~15 per config |
| 8 | **Random-combination control** — sample ~100 random configurations from the pool and compare their distribution to the selected one | 100 |
| 9 | **Walk-forward, DSR, PBO** on finalists only | — |
| 10 | **Holdout.** Once. | 1 |

Cumulative trial count lands in the low thousands rather than the hundreds of thousands — small enough that the Deflated Sharpe Ratio can still return a meaningful verdict.

**Every stage logs its trial count to a running total.** If that total is not accurate, stage 9 produces a number that looks rigorous and means nothing.

---

## 11. Open questions for the next revision

- Final numeric thresholds for Gates 3 and 4 (signal frequency band, correlation ceiling)
- Whether the Continuation slot draws from the C1 pool or needs its own
- Whether to test the FX and crypto branches on the same shortlist, or let each select independently — testing the *same* configuration in both markets is the stronger evidence (`03` §3b), and probably outweighs letting each market pick its own favourite
- 