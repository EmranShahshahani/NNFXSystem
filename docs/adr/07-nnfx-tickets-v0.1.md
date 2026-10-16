# NNFX Engine — Tickets (from /to-tickets)

**Source spec:** `claude/06-nnfx-engine-spec-v0.1.md`  
**Tracker:** local markdown, `.scratch/nnfx-engine/issues/<NN>-<slug>.md` — configured by `/setup-matt-pocock-skills` (no git remote, so the local-file fallback).  
**Status:** all `ready-for-agent`.  
**Rev. 2026-08-31:** added ticket 00 (repo foundations) and propagated the reproducibility decisions from ADR `08` into tickets 01, 04, 05, 08, 19, 22 and 25.

---

# NNFX Engine - tickets

29 tracer-bullet tickets decomposing `docs/adr/06-nnfx-engine-spec-v0.1.md`
(build steps 1-5 of the architecture, plus the paper broker and parity harness).

**Ticket 00 is prefactoring** - the pinned environment and merge-safe research
state that everything else assumes. It exists because determinism and an
accurate trial count are acceptance properties of this project, and working
across two workstations breaks both silently. See `docs/adr/08`.

**Ticket 01 is the tracer bullet proper:** a narrow but complete path through
config, data, indicators, engine, broker and journal. Every ticket after it
thickens one part of a path that already runs end to end, so there is never a
point where the system does not work.

All tickets are `ready-for-agent`. Blocking edges are prose - there is no native
tracker relationship to use - so keep them accurate when you re-order anything.

| # | Ticket | Blocked by | Criteria |
|---|---|---|---|
| 00 | [Repo foundations - pinned environment and merge-safe research state](00-repo-foundations.md) | None (can start immediately) | 11 |
| 01 | [Walking skeleton: CSV bars to backtest report](01-walking-skeleton.md) | 00 (repo foundations) | 12 |
| 02 | [Bar contract and integrity gates](02-bar-contract-integrity-gates.md) | 01 (walking skeleton) | 9 |
| 03 | [Session-close resampling and weekend merge](03-session-close-resampling.md) | 02 (bar contract and integrity gates) | 7 |
| 04 | [Forex feed: Dukascopy with second-source cross-check](04-forex-feed-dukascopy.md) | 03 (session-close resampling) | 9 |
| 05 | [Crypto feed: ccxt with two-exchange cross-check](05-crypto-feed-ccxt.md) | 03 (session-close resampling) | 9 |
| 06 | [Crypto universe: point-in-time selection, delisting, splice marking](06-crypto-universe-point-in-time.md) | 05 (crypto feed) | 7 |
| 07 | [Indicator registry and normalisation contract](07-indicator-registry.md) | 01 (walking skeleton) | 7 |
| 08 | [No-lookahead and determinism gates](08-lookahead-determinism-gates.md) | 07 (indicator registry), 00 (repo foundations) | 9 |
| 09 | [Screening gates 3-5 and the screening report](09-screening-gates-report.md) | 08 (no-lookahead and determinism gates), 04 (forex feed) | 7 |
| 10 | [Populate the indicator catalogue](10-indicator-catalogue.md) | 09 (screening gates) | 9 |
| 11 | [Baseline and pullback entries, and the 7-candle rule](11-baseline-pullback-entries.md) | 01 (walking skeleton) | 8 |
| 12 | [Continuation entries and the continuation slot](12-continuation-entries.md) | 11 (baseline and pullback entries) | 7 |
| 13 | [1-Candle Rule variants A and B behind flags](13-one-candle-rule-variants.md) | 11 (baseline and pullback entries) | 8 |
| 14 | [Exit precedence chain and the exit slot](14-exit-precedence-chain.md) | 07 (indicator registry), 11 (baseline and pullback entries) | 7 |
| 15 | [Two-position money management and the ATR trail](15-two-position-money-management.md) | 01 (walking skeleton) | 9 |
| 16 | [InstrumentSpec capabilities: hedging and mark-price stops](16-instrument-spec-capabilities.md) | 15 (two-position money management) | 7 |
| 17 | [Cost model and the 1.5x cost stress](17-cost-model-and-stress.md) | 16 (InstrumentSpec capabilities) | 9 |
| 18 | [Risk manager, exposure caps and kill switch](18-risk-manager-kill-switch.md) | 16 (InstrumentSpec capabilities) | 8 |
| 19 | [Journal, idempotency, restart safety and reconciliation](19-journal-idempotency-restart.md) | 01 (walking skeleton) | 9 |
| 20 | [Rule flags and the ablation runner](20-rule-flags-ablation-runner.md) | 12 (continuation entries), 13 (1CR variants), 14 (exit precedence), 15 (money management) | 10 |
| 21 | [Metrics, effective sample size and BCa intervals](21-metrics-neff-bca.md) | 17 (cost model) | 8 |
| 22 | [Data partitioning, holdout guard and trial counter](22-partitioning-holdout-trial-counter.md) | 21 (metrics), 00 (repo foundations) | 11 |
| 23 | [Overfitting suite: DSR, PBO, walk-forward and plateau](23-overfitting-suite.md) | 22 (partitioning and trial counter) | 8 |
| 24 | [Monte Carlo, regime reporting and stress runs](24-monte-carlo-regimes-stress.md) | 21 (metrics), 18 (risk manager) | 8 |
| 25 | [Selection pipeline and the random-combination control](25-selection-pipeline-random-control.md) | 10 (indicator catalogue), 20 (ablation runner), 22 (partitioning and trial counter) | 11 |
| 26 | [Acceptance-criteria verdict](26-acceptance-verdict.md) | 23 (overfitting suite), 24 (Monte Carlo and stress), 25 (selection pipeline) | 10 |
| 27 | [PaperBroker and the live harness daily cycle](27-paper-broker-live-harness.md) | 18 (risk manager), 19 (journal and reconciliation) | 7 |
| 28 | [Parity harness: live versus backtest decision equality](28-parity-harness.md) | 27 (PaperBroker and live harness) | 7 |

## Parallel tracks

00 first, then 01. After that three tracks open at once and do not block each
other:

- **Data** - 02, 03, then 04 and 05 in parallel, then 06
- **Indicators** - 07, 08, 09, 10
- **Engine** - 11, then 12, 13, 14 in parallel; 15 independently

They converge at 20 (ablation) and 25 (selection pipeline).

## Where the work runs

Tickets 00-19 run comfortably on a laptop - small fixtures and unit tests.
Ticket 25 sweeps thousands of configurations across decades of daily bars and
wants a substantially bigger machine, likely the same box that later runs the
daily live cycle. The pipeline is checkpointed so a run can move between
machines without restarting or double-counting. See `docs/adr/08` section 4.

## What is not here

Live venue adapters (CcxtBroker, MT5Broker), the venue decision, numeric
kill-switch and exposure thresholds, news and rollover avoidance, discretionary
override, sub-daily timeframes, indicator discovery, hosting, and forward-testing
phases 2-4. See the Out of Scope section of the spec.


---

# 00: Repo foundations - pinned environment and merge-safe research state

**What to build:** A clone of this repo on any workstation produces the same results as a clone on any other. The environment is pinned and installed from a lockfile, market data stays out of version control while its checksums stay in, and the append-only research logs merge cleanly when two machines both contribute. This ticket exists because determinism and an accurate trial count are acceptance properties of this project, and multi-workstation working breaks both silently and in the flattering direction.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `.python-version` and `pyproject.toml` bound the toolchain; `uv.lock` is generated and committed
- [ ] `uv sync` on a clean machine reproduces the environment exactly
- [ ] An `environment fingerprint` helper returns Python version plus resolved dependency versions, as a stable serialisable value
- [ ] `.gitignore` excludes the bar cache, run outputs, secrets and virtualenvs
- [ ] `.gitignore` explicitly does NOT exclude `research/*.jsonl`, `data/manifests/`, `research/thresholds.frozen.json` or `uv.lock`, with a comment saying why
- [ ] `.gitattributes` normalises line endings to LF so a CRLF flip cannot masquerade as a golden-journal diff
- [ ] `.gitattributes` sets `merge=union` on the append-only research and journal logs
- [ ] `.gitattributes` sets `-merge` on the frozen thresholds file, so a goalpost move surfaces as a conflict a human must resolve
- [ ] `.env.example` documents exchange keys (trading permission only, withdrawal disabled), workstation id and cache path; `.env` is ignored
- [ ] A `nnfx research reconcile` command dedupes the append-only logs by id and reports per-workstation contribution counts
- [ ] A test simulates two divergent workstation logs, merges them with union semantics, reconciles, and asserts the derived count is correct with no double-counting


---

# 01: Walking skeleton: CSV bars to backtest report

**What to build:** I can point the system at a CSV of daily bars for one symbol, give it a config naming an indicator for each of the six slots, and get back a list of trades and an equity curve. Standard entry only, zero costs, no position sizing beyond a fixed unit. This is the tracer bullet: a narrow but complete path through config, data, indicators, engine, broker and journal, so every later ticket thickens a path that already runs end to end.

**Blocked by:** 00 (repo foundations)

**Status:** ready-for-agent

- [ ] `system.yaml` loads through a pydantic schema and fails loudly on an unknown slot name
- [ ] A CSV feed produces a `BarFrame`: UTC-indexed, OHLCV, validated at construction
- [ ] One trivial concrete indicator per slot, each emitting the normalised contract
- [ ] `StrategyEngine.decide(history, open_positions, account_state, config)` returns `OrderIntent`s and performs no I/O, reads no clock
- [ ] Standard entry implemented: C1 signal, baseline agreement, bridge-too-far at 1.0x ATR, C2 state agreement, volume gate
- [ ] Exit on baseline cross against the position, and on stop or target
- [ ] A `BacktestBroker` fills at the open of bar t+1 with zero spread, commission and slippage
- [ ] Every evaluation appends to the journal: inputs seen, indicator values computed, intents produced
- [ ] A single command runs a backtest over the CSV and prints a trade list and equity curve
- [ ] Engine unit tests drive `decide()` with hand-built OHLCV fixtures and assert the returned intents
- [ ] The environment is installed from the committed lockfile, not from loose versions
- [ ] Every journal entry carries the environment fingerprint from ticket 00, so a decision traces to the toolchain that produced it


---

# 02: Bar contract and integrity gates

**What to build:** When I hand the system a corrupted price series, it refuses to run and tells me which gate failed and where, rather than silently producing a result I might believe. Every downstream module can then assume its input is clean instead of re-checking it.

**Blocked by:** 01 (walking skeleton)

**Status:** ready-for-agent

- [ ] `BarFrame` rejects duplicate timestamps, out-of-order timestamps and a partial final bar at construction
- [ ] Gate: no zero or negative prices
- [ ] Gate: no bar where high is below low
- [ ] Gate: calendar gap detection against the expected trading calendar for the instrument
- [ ] Gate: daily-return outlier flags, reported rather than dropped, since feed errors and genuine events look alike
- [ ] Gate: volume sanity, with tick-volume-derived series flagged as such so the flag travels into any report that consumes them
- [ ] Gates run automatically before any research command, not on request
- [ ] A failing gate names the gate, the symbol and the offending timestamps
- [ ] Tests drive each gate against a deliberately corrupted frame


---

# 03: Session-close resampling and weekend merge

**What to build:** I can change one config value and see the whole system move: different daily bars, different ATR, different signals. This is what makes the close-convention sensitivity test possible, and it is the rule that most implementations get silently wrong.

**Blocked by:** 02 (bar contract and integrity gates)

**Status:** ready-for-agent

- [ ] D1 bars are resampled from H1 input, not taken from a vendor D1 series
- [ ] `session_close_tz` and `close_hour` are config values, defaulting to America/New_York at 17:00
- [ ] Resampling happens in the data layer and nowhere else; no downstream module re-times a bar
- [ ] Sunday partial bars are merged into Monday for instruments with `has_sessions=True`
- [ ] Instruments with `has_sessions=False` resample at 00:00 UTC with no weekend handling
- [ ] Tests assert that two close conventions over the same H1 input produce different D1 frames, and that both are internally valid
- [ ] A test asserts the same backtest under two conventions produces different trade lists, proving the sensitivity path works


---

# 04: Forex feed: Dukascopy with second-source cross-check

**What to build:** I can pull H1 history for the 28 major and cross pairs, and see a reconciliation report against a second free source on a sample of dates, so feed-specific artefacts surface before they become findings.

**Blocked by:** 03 (session-close resampling)

**Status:** ready-for-agent

- [ ] `DukascopyFeed` implements `BarFeed` and fetches H1 bars from 2003 to present
- [ ] The 28 major and cross pairs from the 8 majors are configured as an instrument basket
- [ ] Fetched data is cached locally so a re-run does not re-download
- [ ] A cross-check command compares a sampled set of dates against a second free source and reports divergences
- [ ] `InstrumentSpec` for each pair declares `has_swap=True`, `has_sessions=True`, `can_short=True`, lot step and min lot
- [ ] All integrity gates from ticket 02 pass on the fetched history, or the failures are documented
- [ ] Each fetch writes a committed manifest: symbol, date range, row count and content checksum
- [ ] A second workstation verifies its re-download against the manifest and reports a mismatch rather than proceeding, since a vendor can revise history under the same name
- [ ] The walking-skeleton backtest runs on a real pair end to end


---

# 05: Crypto feed: ccxt with two-exchange cross-check

**What to build:** The same backtest that runs on EURUSD runs on BTC/USDT, with no engine change - only a different feed and a different InstrumentSpec. Crypto data is free, complete and better than retail forex data, so this is also where the fractional-sizing path first gets exercised.

**Blocked by:** 03 (session-close resampling)

**Status:** ready-for-agent

- [ ] `CcxtFeed` implements `BarFeed` against a major exchange and fetches 1h bars
- [ ] Bars resample to D1 at 00:00 UTC via the existing session logic, with no crypto-specific branch in the data layer
- [ ] A cross-check command compares the same symbol across two exchanges and reports divergences
- [ ] `InstrumentSpec` declares `market_class`, `has_funding`, `has_sessions=False`, and a fractional `size_step`
- [ ] Volume is recorded as genuine traded volume and is not flagged as tick volume
- [ ] Volume and price come from the same venue, enforced rather than assumed
- [ ] Each fetch writes a committed manifest: symbol, date range, row count and content checksum
- [ ] A second workstation verifies its re-download against the manifest and reports a mismatch rather than proceeding, since a vendor can revise history under the same name
- [ ] The walking-skeleton backtest runs on BTC/USDT end to end


---

# 06: Crypto universe: point-in-time selection, delisting, splice marking

**What to build:** The crypto universe I backtest is the universe I would have been able to trade at the time - ranked by liquidity available then, including the coins that later died. Without this the backtest only ever tests survivors, which is survivorship bias in its most damaging form.

**Blocked by:** 05 (crypto feed)

**Status:** ready-for-agent

- [ ] Universe is reconstructed at each rebalance date by ranking on trailing liquidity using only data available at that date
- [ ] The rebalance rule and window are config values
- [ ] Delisted instruments remain in the dataset with positions force-closed at the last valid price, never dropped
- [ ] Where spot history is spliced onto perpetual history, the splice point is marked in the data
- [ ] Any report covering a spliced period reports it separately and refuses to pool it with native-perp results
- [ ] A test builds a synthetic universe containing a coin that delists mid-sample and asserts it appears in the backtest and is force-closed
- [ ] A test asserts that selecting the universe using end-of-sample data produces a different (and rejected) basket


---

# 07: Indicator registry and normalisation contract

**What to build:** I can swap the confirmation indicator by editing one config line, and nothing in the engine changes. This is the mechanism the entire modularity claim rests on: the wrapper owns the translation from an indicator's native output into the contract, and the engine only ever sees the contract.

**Blocked by:** 01 (walking skeleton)

**Status:** ready-for-agent

- [ ] Indicators register by slot and name and instantiate from config parameters
- [ ] `BaselineIndicator`, `ConfirmationIndicator`, `VolumeIndicator`, `ExitIndicator` and `VolatilityIndicator` protocols are defined and type-checked
- [ ] At least three real indicators per slot, drawn from doc 05, are implemented
- [ ] Each wrapper converts its native output (histogram, colour change, band crossing) into `line`, `signal`, `state`, `gate` or `value`
- [ ] Swapping any slot is a config edit with zero engine changes, proven by a test that runs the same backtest under two slot assignments
- [ ] No engine module imports a concrete indicator name
- [ ] Per-indicator tests assert the wrapper emits the contract, not the indicator's native shape


---

# 08: No-lookahead and determinism gates

**What to build:** Any indicator that peeks at the future is caught automatically before it ever produces a backtest. Repainting is the number-one source of beautiful results that fail live, and it is an implementation property rather than a property of the concept - so the gate runs against the exact code that will ship, never against the indicator's reputation.

**Blocked by:** 07 (indicator registry), 00 (repo foundations)

**Status:** ready-for-agent

- [ ] Gate 1: recompute each indicator on history truncated at bar t, assert tail values are unchanged against the full-history computation
- [ ] The gate runs across every registered indicator automatically, with no per-indicator test to write
- [ ] Gate 2: same input produces same output across runs and across process restarts; no hidden state
- [ ] A backtest run twice produces byte-identical output, asserted as a test
- [ ] Gate failures name the indicator and the first bar at which values diverge
- [ ] A deliberately repainting fixture indicator is included and asserted to fail Gate 1
- [ ] Cross-machine determinism: a clean checkout on a second workstation, installed from the lockfile, reproduces a committed reference run byte for byte
- [ ] A mismatch whose environment fingerprint differs from the reference is reported as an ENVIRONMENT MISMATCH, not as a determinism failure - they are different problems and confusing them costs days
- [ ] Families needing extra scrutiny (centred or displaced smoothing, zig-zag and pivot logic, swing reconstruction, non-causal DSP filters) are listed in the gate documentation


---

# 09: Screening gates 3-5 and the screening report

**What to build:** Before any performance number is computed, I get a pass/fail table telling me which candidates are eligible at all. Screening must not become a covert first round of selection, so these gates consult no performance data.

**Blocked by:** 08 (no-lookahead and determinism gates), 04 (forex feed)

**Status:** ready-for-agent

- [ ] Gate 3: C1 signal frequency must fall in 6-50 signals per instrument-year, with the 12-35 target zone reported
- [ ] Gate 4: C1/C2 correlation on pooled `state` series must fall in 0.15 <= rho <= 0.60, computed on the development segment only
- [ ] Negative rho rejects immediately
- [ ] Gate 5: parameters are exposed for the grid; no magic constants tuned to a market price scale
- [ ] The report records pass/fail per candidate with the measured values, and consults no performance data
- [ ] Gate 4 documentation states the agreement mapping (rho = 2 x agreement f