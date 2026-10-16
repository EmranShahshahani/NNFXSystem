# NNFX System — Data & Validation Protocol (v0.1)

**Companion to:** `01-nnfx-spec-v0.1.md`, `02-nnfx-architecture-v0.1.md`
**Purpose:** Decide, honestly, whether this system has an edge — before any money is connected to it.

This is the document that determines whether the project succeeds or produces an expensive illusion. Everything here should be read as adversarial: the goal is not to produce a good backtest, it is to *try hard to prove the system doesn't work* and see whether it survives.

---

## 1. Why we are replacing VP's method

VP's recommended process — roughly 2 years of daily data, score indicators by raw win percentage, keep the top 3–5 — fails on three counts:

**Sample size.** Two years of daily bars across a handful of pairs yields a few hundred trades. The standard error on a win rate from 300 trades is around ±3%; the spread between the "best" and "tenth-best" indicator in such a test is routinely smaller than that. The ranking is largely noise.

**Selection bias.** Test 40 indicators on the same 2-year sample and the top performer is, in expectation, the luckiest — not the best. Nothing in the method corrects for the number of things tried. This is the single largest source of dead retail trading systems.

**Wrong metric.** Win% ignores payoff. The system risks 1.5R to make 1R on the first position and lets the second run. A 45% win rate can be highly profitable and a 60% win rate can lose money. Optimizing win% optimizes the wrong quantity.

We keep VP's *rules*. We replace his *evidence standard*.

---

## 2. Data — Forex branch

**Source:** Dukascopy historical bars (free, 2003–present, generally regarded as clean for FX). Cross-checked against a second free source on a sample of dates to catch feed-specific artefacts.

**Coverage:** The 28 major/cross pairs from the 8 majors (USD, EUR, GBP, JPY, CHF, CAD, AUD, NZD). Note the pair basket will be constrained later by the exposure-cap analysis, not by data availability.

**Construction:** H1 bars downloaded, resampled to D1 in the data layer under the configured session close. Resampling from H1 (rather than taking a vendor's D1) is what allows the close-convention sensitivity test.

**Integrity gates, automated, run before any research:**
- No duplicate or out-of-order timestamps
- No zero/negative prices, no high < low
- Gap detection against the expected trading calendar
- Outlier detection on daily returns (flags feed errors and genuine events alike — both need eyes)
- Volume sanity (FX "volume" is tick volume; this must be documented wherever the volume slot uses it)

**Cost model, applied from the first backtest:**
- Spread: per-pair typical values, modelled as time-varying where data allows, widened at rollover
- Commission: per-lot, venue-dependent
- Swap: nightly, per-pair, both directions — material for a system holding trends for weeks
- Slippage: applied to market orders and, importantly, to stop fills; stops model gap risk rather than assuming perfect execution

An unrealistically optimistic cost model is a form of lying to yourself, and daily systems hold positions long enough for swap alone to change the verdict.

---

## 2b. Data — Crypto branch

**Source:** Exchange REST APIs via `ccxt` (Binance, Bybit, OKX). Free, complete, and higher quality than anything available in retail FX. Cross-check the same symbol across two exchanges to catch venue-specific artefacts.

**Universe:** Top 10–20 by liquidity, selected on **a rule applied at the start of the test window, not today.** Selecting "the top 20 coins of 2026" and backtesting them to 2017 is survivorship bias of the most damaging kind — it guarantees you only test assets that survived and thrived. The universe must be reconstructed point-in-time: at each rebalance date, rank by trailing liquidity using only data available then.

**Delisting handling:** Coins that delist must remain in the dataset with their positions force-closed at the last valid price. Silently dropping them inflates results.

**Bar construction:** 1h bars from the exchange, resampled to D1 at 00:00 UTC.

**Cost model:**
- Taker/maker fees per exchange tier
- **Funding rate**, actual historical values from the exchange API, applied per settlement period, long/short asymmetric
- Slippage scaled to instrument depth — an alt-coin's slippage is not BTC's
- Stop fills modelled on **mark price**, matching exchange behaviour

**The splice problem.** Perpetual history (~2019–2020) is shorter than spot history (~2017). If spot prices are used to extend the signal history, the splice must be explicit, documented, and reported separately — spliced-period results are weaker evidence than native-perp results, and must never be silently pooled.

---

## 3. Data partitioning

| Segment | Period | Use | Rule |
|---|---|---|---|
| **Development** | 2004–2015 | Indicator selection, rule ablation, parameter exploration | Look at freely |
| **Validation** | 2016–2021 | Confirm findings from development | Limited passes, each one logged |
| **Holdout** | 2022–2026 | Final verdict | **Touched exactly once, ever** |

The holdout is sacred. Every time it is examined and the system is then adjusted, it stops being a holdout and becomes another development set. The single most valuable discipline in this entire project is not looking at it.

### 3b. Crypto partitioning — and why it's harder

Crypto gives roughly 8 years of usable history against forex's 20+. Splitting it three ways leaves segments too short to trust, and the segments aren't comparable: 2017 (retail mania), 2018 (bear), 2021 (leverage bull), 2022 (deleveraging bear), 2023–2026 (institutional) are structurally different markets. A conventional chronological split risks a development set that contains no bear market at all.

Provisional approach, to be finalized before testing:

| Segment | Period | Note |
|---|---|---|
| Development | 2017–2021 | Contains one full bull/bear cycle |
| Validation | 2022–2024 | Contains the 2022 deleveraging |
| Holdout | 2025–2026 | Short. Touched once. |

**Three compensating measures, because the sample is thin:**

1. **Regime-stratified reporting.** Performance is reported *per regime* (bull / bear / chop, classified by an independent rule) as well as in aggregate. A trend system that only works in bull markets is a leveraged long, and the aggregate number will hide that.
2. **Cross-market corroboration.** This is the strongest argument for keeping the forex branch alive. If a configuration works on 20 years of FX *and* on 8 years of crypto, that is far better evidence than either alone — the FX result acts as an out-of-sample test in a different asset class entirely. **This is now the main reason to validate both markets rather than picking one early.**
3. **Effective sample size, not trade count.** With BTC-correlation near 1, 400 trades across 20 coins carries nowhere near the information of 400 independent trades. Report effective sample size adjusted for cross-sectional correlation, and treat it — not raw trade count — as the sample-size gate.

A written log records every pass over the validation segment. If that log grows long, the validation segment has been contaminated by iteration and its results must be discounted accordingly.

---

## 4. Metrics

Win% is reported but never optimized. The decision metrics are:

| Metric | Why |
|---|---|
| **Expectancy in R** | Average profit per trade in units of risk. The core number. |
| **Distribution of R-multiples** | Reveals whether profit comes from many small edges or two lucky runners |
| **Profit factor** | Gross win / gross loss |
| **Sharpe & Sortino** on daily equity | Risk-adjusted return; Sortino because upside volatility is not a problem here |
| **Maximum drawdown** (depth and duration) | Determines survivability and sets the kill switch |
| **Longest losing streak** | Psychological and operational tolerance |
| **MAR ratio** (CAGR / max DD) | Single-number comparison across variants |
| **Trade count** | Any result on fewer than ~500 trades is provisional |
| **Time in market** | A system in the market 5% of the time carries different risk than one at 60% |

Reported per-pair *and* portfolio-level. A system that works on 3 of 28 pairs has found three lucky pairs, not an edge.

---

## 5. Controlling for overfitting

This is the heart of the protocol.

**5.1 Pre-registration.** Acceptance thresholds are written down and committed to the repository *before* the tests are run (see §8). Moving the goalposts after seeing results is how everyone talks themselves into a bad system.

**5.2 Count every trial.** Every indicator, parameter set, and rule combination evaluated is logged. The final result is judged against the *number of things tried*, not in isolation.

**5.3 Deflated Sharpe Ratio.** Bailey & López de Prado's adjustment discounts an observed Sharpe by the number of trials and the non-normality of returns. A Sharpe of 1.0 found after 200 trials is not the same discovery as a Sharpe of 1.0 found on the first attempt, and the DSR quantifies exactly that.

**5.4 Probability of Backtest Overfitting (PBO).** Via combinatorially symmetric cross-validation: repeatedly split the history, select the best configuration in-sample, and measure how often it ranks below median out-of-sample. A PBO above ~50% means the selection process has no skill and the whole exercise should be abandoned rather than deployed.

**5.5 Walk-forward analysis.** Rolling windows — select on N years, trade the following year, roll forward. This mimics how the system would actually have been run and is far more honest than a single split. The walk-forward efficiency ratio (out-of-sample return / in-sample return) should be meaningfully above zero; near-zero means the selection doesn't generalize.

**5.6 Parameter plateaus, not peaks.** For any surviving configuration, examine performance across neighbouring parameter values. A sharp peak surrounded by poor results is a fitting artefact. A broad plateau suggests a real effect. This test alone kills most candidates.

**5.7 Curated search space.** Per your decision, the indicator pool is the NNFX community's vetted set rather than an exhaustive scan. This is a deliberate statistical choice: fewer trials means less selection damage and a more believable result, at the cost of possibly missing a better combination.

---

## 6. Rule ablation

Each structural rule is toggled independently and its marginal contribution measured on the development segment:

| Rule | Question it answers |
|---|---|
| Bridge-too-far (1×ATR) | Does the distance filter add anything, or just reduce trade count? |
| Bridge multiple (0.5 / 1.0 / 1.5×ATR) | Is 1.0 special, or arbitrary? |
| 7-candle rule | Does stale-confirmation filtering matter? |
| 1-Candle Rule | Pending definition (Spec A7) |
| Continuation entries | Do they add expectancy or just add exposure? |
| C2 requirement | Does the second confirmation earn its slot, or merely halve trade count? |
| Two-position split vs single position | Is the split superior to a simple 2%-risk single position with the same exits? |
| Session close convention | How sensitive is the whole system to where the day is cut? |
| **Long-only vs symmetric** (crypto) | Does the spot long-only variant match the perpetual symmetric one? If yes, take the simpler, safer instrument — see `04`. |
| **Funding cost on/off** (crypto) | How much of measured performance is carry rather than signal? |

Rules that don't earn their keep are switched off and the finding recorded. This is Deviation D2 from the spec, and it is also the most interesting research in the project — some of these rules are likely to be folklore.

---

## 7. Monte Carlo and the kill switch

The kill-switch threshold you asked me to derive comes from here.

- **Trade-sequence bootstrap:** resample the trade sequence thousands of times to produce a distribution of maximum drawdowns and losing-streak lengths. The historical max drawdown is *one draw* from this distribution and is almost certainly not the worst case.
- **Threshold rule:** set the halt level above the 95th percentile of simulated drawdown (so normal bad luck doesn't stop a working system) and below the level at which the account is unrecoverable.
- **Regime stress:** examine behaviour separately across 2008, 2015 (CHF), 2020, and the 2022 rate cycle. A trend system should do *well* in some of these; if it doesn't, that's diagnostic.
- **Correlation stress:** simulate the portfolio with all positions in a single currency direction to bound the worst-case simultaneous-exposure loss. This sets the per-currency cap.

You approve the resulting number before go-live.

---

## 8. Pre-registered acceptance criteria — FINAL

**Status: frozen 2026-08-27. These are committed before any performance test is run.**

### 8.1 How much evidence a real edge actually requires

The sample-size question is usually waved at. It shouldn't be, because the arithmetic is unforgiving and it shapes the entire project.

Per-entry R-multiples in this system are right-skewed: position 1 resolves near ±1R, position 2 either loses 1R or runs to +2R–+5R. Standard deviation of the combined per-entry outcome is realistically **σ ≈ 1.5R** (to be measured, not assumed — this is the planning estimate). The standard error of measured expectancy is `σ/√n`, so the trades needed for a 95% confidence interval that excludes zero:

| True expectancy | Trades required |
|---|---|
| 0.05 R | ~3,460 |
| 0.10 R | **~865** |
| 0.15 R | ~385 |
| 0.20 R | ~216 |
| 0.30 R | ~96 |

**This is the number that should govern expectations.** A genuine but modest edge of 0.10R needs on the order of 865 trades before it can be distinguished from zero. VP's recommended 2-year sample produces a small fraction of that — which is the quantitative statement of why his method cannot work, and why a system can pass his screen and still be nothing.

**Crypto correlation makes this substantially worse.** Raw trade count overstates evidence when trades are concurrent and correlated. The effective sample size is:

```
N_eff = N / (1 + (m̄ − 1) · ρ̄)
```

where `m̄` is mean concurrent positions and `ρ̄` the mean pairwise correlation of concurrent trade returns. With 8 concurrent positions at ρ̄ = 0.6 — entirely plausible for a BTC-correlated alt basket — the design effect is 5.2. **800 raw crypto trades carry the evidential weight of about 154.** This single calculation is the strongest argument in the whole project for validating forex alongside crypto: FX supplies the sample size that crypto structurally cannot.

### 8.2 The criteria

| # | Criterion | Threshold | Basis |
|---|---|---|---|
| 1 | **Expectancy, 95% CI lower bound** | **> 0** | The primary gate. Replaces a raw trade-count rule — it self-adjusts for the sample-size/effect-size trade-off above. Use a **bootstrap BCa interval**, not the normal approximation: R-multiple distributions are right-skewed and fat-tailed. |
| 2 | Effective sample floor | ≥ 400 `N_eff` | Below this the CI itself is unreliable regardless of what it reports |
| 3 | Expectancy point estimate | ≥ 0.10 R after full modelled costs | Below this the edge is too thin to survive cost-model error |
| 4 | Deflated Sharpe Ratio | > 0 at 95%, against the **logged** trial count | Meaningless if the trial counter is inaccurate — see `05` §1 |
| 5 | Probability of Backtest Overfitting | **< 30%** | 50% is the no-skill point, so 40% is barely better than a coin flip. 30% is the loosest defensible bar. |
| 6 | Walk-forward efficiency | ≥ 0.5 | Practitioner heuristic, not theoretically grounded — recorded as such |
| 7 | MAR ratio (CAGR / max DD) | ≥ 0.5 | Below this the return doesn't justify the drawdown |
| 8 | Bootstrap 95th-percentile drawdown | < 35% | Recovering 35% requires +54%; recovering 50% requires +100%. Beyond ~35% the account is mathematically hard to rescue. |
| 9 | **Random-combination control** | Selected config beats the **90th percentile** of ~100 randomly assembled configs | If it doesn't, the selection procedure has no demonstrated skill and nothing else on this list matters |
| 10 | Cost stress | Criteria 1 and 3 still hold with all costs inflated **×1.5** | Guards against an optimistic cost model — the most common silent backtest error |
| 11 | Parameter plateau | Neighbouring grid points (±1 step, each parameter) retain ≥ 60% of peak expectancy | Quantifies `05` §9's plateau requirement |
| 12 | Holdout degradation | OOS expectancy ≥ 50% of development | Some decay is expected and healthy; more than half signals fitting |
| 13 | Regime coverage *(crypto)* | Positive expectancy in **both** bull and bear regimes | A trend system profitable only in bull markets is a leveraged long wearing a costume |
| 14 | Instrument breadth *(FX)* | > 60% of the basket profitable | Weak in crypto, where correlation makes this near-automatic — hence criterion 13 replaces it there |
| 15 | Cross-market corroboration | Same configuration directionally consistent in the second market | The strongest single piece of evidence available (§3b) |

### 8.3 Binding commitments

**No goalpost moving.** These thresholds are frozen as of the date above. If a result lands just short, that is a fail. Adjusting a threshold after seeing a number converts this document from a safeguard into a rationalisation.

**On failure, no re-optimisation on the same data.** If the system fails, the permitted responses are: (a) abandon, or (b) return to the development segment with a *new, documented, counted* trial budget — and the holdout stays untouched. What is not permitted is tweaking until it passes, which is how every overfitted system in history was born.

**Failure is an acceptable outcome.** Given that NNFX's own validation standard is roughly two orders of magnitude short of the evidence required to establish a 0.10R edge, a fair test failing is a live possibility. The ablation study still yields something valuable in that case: a clear account of which of VP's rules are load-bearing and which are folklore.

---

## 9. Forward testing

Backward testing is only half of what you asked for.

**Phase 1 — Parity (2–4 weeks).** The live engine runs against a demo account on live data. Every day, its decisions are compared against the backtest engine fed identical bars. Requirement: **identical decisions, every day, zero exceptions.** Any divergence is a bug and blocks progress. This phase catches data-feed differences, session-boundary errors, and state-management bugs — all of which are invisible in backtesting.

**Phase 2 — Demo forward test (3–6 months).** Full system on demo, unattended, with daily reporting. Measured against the backtest's expected distribution: is live expectancy inside the confidence interval the backtest predicts? A shortfall here is the system telling you the backtest was optimistic.

**Phase 3 — Live micro.** Cent account, real money, smallest viable size. The purpose is to surface execution reality — slippage, requotes, swap charges, broker behaviour around rollover — not to make money. Continue reconciling against expectation.

**Phase 4 — Scale.** Only after Phase 3 matches expectation over a meaningful number of trades.

There is no shortcut through this. A daily system generates trades slowly, which means forward testing takes real calendar time. That is the cost of the timeframe, and it is worth budgeting for honestly: from first line of code to justified live trading is realistically **6–12 months**, most of it waiting.

---

## 10. Ongoing maintenance

- **Monthly:** live-versus-expected reconciliation, cost audit (are real spreads and swaps matching the model?)
- **Quarterly:** rolling performance review against the backtest distribution
- **Annually:** re-run walk-forward including the newest year; check whether the selected configuration is still in the top cohort
- **Never:** re-optimize after a losing period. That is the road to permanently fitting the 