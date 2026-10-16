# NNFX engine and validation platform

A Python implementation of the No Nonsense Forex system as **one pure strategy
engine driven by two harnesses**, plus the research toolkit that decides -
against thresholds frozen before any result was seen - whether the system has
an edge at all. Design documents live in [`docs/adr/`](docs/adr/); what was built
against which ticket is in [`docs/implementation-status.md`](docs/implementation-status.md).

```
config (YAML) -> data layer (session close applied once) -> indicator registry
  -> StrategyEngine.decide()  [pure: no I/O, no clock, no concrete names]
  -> RiskManager (sizing, caps, liquidation guard, kill switch)
  -> Broker (BacktestBroker | PaperBroker)  -> append-only journal
```

## Setup

```bash
uv sync --frozen          # installs exactly what uv.lock pins
cp .env.example .env      # set NNFX_WORKSTATION_ID per machine
uv run pytest             # ~360 tests, about a minute
uv run nnfx determinism   # reproduce the committed reference run on this machine
```

## Commands

```bash
# Walking skeleton: CSV bars -> trade list + equity curve (H1 input is resampled under the session close)
uv run nnfx backtest --csv EURUSD=data/sample/EURUSD.D1.csv --csv GBPUSD=data/sample/GBPUSD.D1.csv
uv run nnfx gates    --csv EURUSD=data/sample/EURUSD.D1.csv          # integrity gates
uv run nnfx screen   --csv EURUSD=data/sample/EURUSD.D1.csv          # screening gates 1-5, no performance data
uv run nnfx ablate   --csv EURUSD=... --market fx                     # rule ablation, every variant a counted trial
uv run nnfx live     --csv EURUSD=... --now 2015-09-08T22:05Z         # one daily cycle against the PaperBroker
uv run nnfx select   --csv EURUSD=... --csv GBPUSD=... --market fx  # staged selection + random control -> runs/selection/
uv run nnfx plateau  --config runs/selection/finalist.fx.yaml --slot c1 --csv EURUSD=...   # criterion 11
uv run nnfx verdict  --evidence evidence.json                        # the 15 frozen criteria
uv run nnfx fetch    --feed dukascopy --symbol EURUSD --start 2003-05-05 --end 2026-10-01
uv run nnfx fetch    --feed nobitex --symbol BTC/USDT --start 2020-01-01 --end 2026-10-01
uv run nnfx fetch    --feed udf --base-url https://<exchange>/udf --venue-name <exchange> --symbol BTC/USDT ...
uv run nnfx import-tv chart_export.csv --symbol EURUSD --vendor OANDA  # TradingView "Export chart data", 1h bars
uv run nnfx research reconcile                                       # after merging research logs from another machine
uv run nnfx catalogue
```

## Web UI

```bash
uv run nnfx ui            # http://127.0.0.1:8765
```

A local dashboard over the same code the CLI runs (standard library only, no
extra install): **Backtest** (pick datasets, swap any slot, toggle any rule,
see KPIs, equity, price with baseline and trade markers, trade list),
**Indicators** (the full pool with defaults and grids), **Research** (logged
trial count, holdout status, frozen thresholds, trials log) and **Live** (latest
daily report, journal cycles, PaperBroker state). Browser backtests are
exploration: they never log a trial and never touch the holdout.

## Data sources

| source | how | notes |
|---|---|---|
| Dukascopy (FX) | `nnfx fetch --feed dukascopy` | H1, tick volume |
| ccxt exchanges | `nnfx fetch --feed ccxt --exchange binance` | needs `uv sync --extra crypto` |
| Nobitex | `nnfx fetch --feed nobitex` | public `market/udf/history`; symbols `BTC/USDT`, `BTC/IRT`; IRT prices are rials |
| any UDF datafeed | `nnfx fetch --feed udf --base-url ...` | the TradingView-charting protocol many exchanges expose |
| TradingView | `nnfx import-tv` | no public data API; export 1h bars from the chart menu |

`data/sample/` holds **synthetic** bars for demos only. Real history is fetched
into `data/cache/` (gitignored); its manifest in `data/manifests/` is committed.

## Working across machines (ADR 08)

* `uv.lock` pins the environment; every journal entry and trial line carries an
  environment fingerprint. A reproduction failure is classified as
  `ENVIRONMENT MISMATCH` or `DETERMINISM FAILURE` - different problems.
* `research/*.jsonl` is append-only and union-merged; the trial count is always
  *derived* by counting distinct ids. Run `nnfx research reconcile` after a merge.
* `research/thresholds.frozen.json` is `-merge`: changing it is a conflict a human resolves.
* The holdout is touched once, ever, per market - enforced across machines by the
  committed `research/holdout_touches.jsonl`.
