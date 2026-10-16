# Implementation status

All 29 tickets of `docs/adr/07-nnfx-tickets-v0.1.md` have an implementation and
tests. Tickets 00-09 had full acceptance criteria in the ticket file; tickets
10-28 were implemented from their titles plus the spec (`06`), architecture
(`02`), validation protocol (`03`) and catalogue (`05`).

| # | Ticket | Code | Tests |
|---|---|---|---|
| 00 | Repo foundations | `pyproject.toml`, `uv.lock`, `.gitignore`, `.gitattributes`, `.env.example`, `nnfx/env.py`, `nnfx/research/logs.py` | `test_foundations.py` (incl. a real two-branch git union merge + reconcile) |
| 01 | Walking skeleton | `nnfx/config.py`, `data/feeds.py`, `engine/`, `brokers/sim.py`, `journal/`, `harness/backtest.py`, `cli.py` | `test_config.py`, `test_engine_rules.py` |
| 02 | Bar contract + integrity gates | `data/bars.py`, `data/gates.py` | `test_data.py` |
| 03 | Session-close resampling | `data/session.py` | `test_data.py` (two conventions -> different trade lists) |
| 04 | Dukascopy + cross-check | `data/dukascopy.py` (+ `StooqFeed`), `data/crosscheck.py`, `data/manifest.py`, `instruments.py` | `test_data.py` (offline `.bi5` fixtures) |
| 05 | ccxt + two-exchange cross-check | `data/ccxt_feed.py` | `test_data.py` (fake exchange) |
| 06 | Point-in-time crypto universe | `data/universe.py`, delisting in `harness/backtest.py`, splices in `research/metrics.py` | `test_universe.py` |
| 07 | Indicator registry + contract | `indicators/base.py`, `indicators/library.py`, `indicators/slots.py` | `test_indicators.py` |
| 08 | No-lookahead + determinism | `research/lookahead.py`, `research/determinism.py`, `tests/golden/reference_run.json`, `docs/gates.md` | `test_indicators.py` |
| 09 | Screening gates 3-5 | `research/screening.py` | `test_indicators.py` |
| 10 | Indicator catalogue | `indicators/catalogue.py` (32 implemented; the rest of doc 05 listed as planned) | `test_indicators.py` |
| 11 | Baseline/pullback entries, 7-candle rule | `engine/core.py` | `test_engine_rules.py` |
| 12 | Continuation entries + slot | `engine/core.py` | `test_engine_rules.py` |
| 13 | 1-Candle Rule A and B | `engine/core.py` | `test_engine_rules.py` |
| 14 | Exit precedence + exit slot | `engine/core.py` | `test_engine_rules.py` |
| 15 | Two positions + ATR trail | `engine/core.py`, `brokers/sim.py`, `risk/manager.py` | `test_engine_rules.py`, `test_broker_risk.py` |
| 16 | Hedging + mark-price stops | `engine/core.py` (combined leg), `brokers/sim.py` | `test_broker_risk.py` |
| 17 | Cost model + 1.5x stress | `brokers/costs.py`, `config/venues/backtest.yaml` | `test_broker_risk.py` |
| 18 | Risk manager, caps, kill switch | `risk/manager.py` | `test_broker_risk.py` |
| 19 | Journal, idempotency, restart, reconciliation | `journal/journal.py`, `harness/loop.py`, `harness/live.py` | `test_live.py` (simulated kill mid-cycle) |
| 20 | Rule flags + ablation runner | `config.py` (`RulesConfig`), `research/ablation.py` | `test_research.py` |
| 21 | Metrics, N_eff, BCa | `research/metrics.py` | `test_research.py` |
| 22 | Partitioning, holdout guard, trial counter | `research/partition.py`, `research/trials.py`, `research/thresholds.frozen.json` | `test_research.py` |
| 23 | DSR, PBO, walk-forward, plateau | `research/overfitting.py` | `test_research.py` |
| 24 | Monte Carlo, regimes, stress | `research/montecarlo.py` | `test_research.py` |
| 25 | Selection pipeline + random control | `research/selection.py`, `research/evaluate.py` | `test_research.py` (resume on a "second machine": zero re-runs, zero re-counts) |
| 26 | Acceptance verdict | `research/verdict.py` | `test_research.py` |
| 27 | PaperBroker + daily cycle | `brokers/paper.py`, `harness/live.py` | `test_live.py` |
| 28 | Parity harness | `harness/parity.py` | `test_live.py` (OK over 131 restarts; detects a 1% live-only ATR skew) |

## Decisions taken where the spec was open

* **Seams (spec 06 asked for confirmation).** `decide(history, open_positions,
  account_state, config, state)` takes engine state as an explicit fifth
  argument and returns `Decision(intents, state, evaluations)`. That keeps the
  engine a pure function while making `PENDING_PULLBACK` expiry and continuation
  bookkeeping explicit, serialisable state rather than something inferred.
  The other seams are `BarFeed.bars`, the `Broker` protocol, `RiskManager.size/approve`
  and the evaluator's `DataProvider(config) -> frames` (so session-close
  ablations re-resample in the data layer).
* **Bar labels.** Bars are indexed by their *close* time in UTC.
* **1-Candle Rule state.** The 1CR setups add a `PENDING_ONE_CANDLE` phase to the
  five states in doc 02.
* **R unit.** 1R = cash risked by one position (1% of equity). An entry's R is
  the sum over its legs, matching doc 03 §8.1's sigma ~ 1.5R planning figure.
* **Exit on opposite C2.** "Opposite signal from C2" uses C2's `signal`, not a state flip.
* **Continuation entries** are taken from flat after an exit that did not cross
  the baseline; they never pyramid onto an open position.
* **Single-position ablation** (`positions_per_entry: 1`) risks 2% with no fixed
  target; breakeven/trail start when price reaches the TP1 level.
* **Currency cap** counts entries (not legs) per currency and direction, ignoring
  stablecoin legs; the crypto cap is the BTC-beta-weighted sum of risk.
* **DSR criterion** is read as P(true Sharpe > 0 after deflation) >= 0.95.
* **Gate 5** probes price scale both ways (x1000 and x0.001).
* **numpy < 2.5**: pandas 2.3 trips numpy 2.5's timedelta deprecations.

## Not done / needs real data

* The Dukascopy, Stooq, ccxt and Nobitex/UDF feeds are implemented and tested
  offline only; this build environment's network policy blocks those hosts. The
  Nobitex client follows its published API docs (``apiv2.nobitex.ir/market/udf/history``).
  First real fetch writes the committed manifests.
* TradingView has no public market-data API; ``nnfx import-tv`` reads its chart
  export instead. Bitycle publishes only a partner (business) API, so no client
  was written; if it exposes a UDF datafeed, ``--feed udf --base-url`` covers it.
* No real-data research run has been made, so no trial has been logged and the
  holdout is untouched. `nnfx ablate` and `SelectionPipeline` are ready for it.
* The selection pipeline evaluates published defaults; `nnfx plateau` then sweeps
  the finalist's grid neighbourhood (each point a counted trial) for criterion 11.
* `nnfx verdict` scores an evidence JSON; assembling every evidence field
  (walk-forward, PBO across the selection's configurations, cost stress, holdout)
  from a real run is still a manual sequence of the existing functions.
* All 64 doc 05 indicators are wrapped (`library.py`, `library_ext.py`). Kase
  permission stochastic is a daily approximation (higher-timeframe window);
  directional indicators placed in the volume slot gate on reading strength.
* Out of scope per spec: live venue adapters, venue choice, numeric kill-switch
  and exposure thresholds, news/rollover avoidance, sub-daily timeframes.
