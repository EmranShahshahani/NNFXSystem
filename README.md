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
uv run pytest             # ~250 tests, < 1 minute
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
uv run nnfx fetch    --feed dukascopy --symbol EURUSD --start 2003-05-05 --end 2026-10-01
uv run nnfx research reconcile                                       # after merging research logs from another machine
uv run nnfx catalogue
```

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
