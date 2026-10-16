# NNFX System — Architecture & Module Contracts (v0.1)

**Companion to:** `01-nnfx-spec-v0.1.md` (the rules)
**Scope:** How the system is built so that indicators, brokers, and markets are all replaceable without touching the decision logic.

**Implementation model (rev. 2026-08-27):** Emran implements in his own IDE. This document specifies *contracts, invariants and acceptance criteria* precise enough to code against — it is not a source repository. Where code appears, it is interface definition, not implementation. Language: Python throughout, with `mypy --strict`, `pydantic` for every data contract crossing a module boundary, and `ruff`. The type discipline matters here more than in most projects: an order state machine handling real money is exactly the domain where making illegal states unrepresentable pays for itself.

---

## 1. Four principles

**P1 — One engine, two harnesses.**
The backtester and the live trader are *not* two implementations of the strategy. They are two harnesses feeding the same `StrategyEngine` object. The engine is a pure function:

```
decide(history, open_positions, account_state, config) → list[OrderIntent]
```

It performs no I/O, reads no clock, and has no knowledge of whether it is in 2011 or live. This single decision eliminates the most common and most expensive failure in retail algo trading: a backtest and a live bot that quietly disagree.

**P2 — The engine knows no concrete names.**
It never sees "RSI" or "MT5". It sees a `ConfirmationIndicator` and a `Broker`. Swapping either is a config edit.

**P3 — Determinism.**
Same inputs → same outputs, always. Time, randomness, and network access are injected dependencies, never called directly. A backtest run twice produces identical results, byte for byte.

**P4 — Every decision is journaled.**
Each daily evaluation appends a record containing the inputs it saw, the indicator values it computed, and the intents it produced. This is what makes live-vs-backtest reconciliation possible, and what lets the system recover from a crash without duplicating orders.

---

## 2. Layers

```
┌──────────────────────────────────────────────┐
│  Config (YAML)  — the entire system's knobs  │
└──────────────────────────────────────────────┘
                      ↓
┌──────────────────────────────────────────────┐
│  Data Layer                                  │
│  raw feeds → normalized UTC OHLCV bars       │
│  session-close convention applied here       │
└──────────────────────────────────────────────┘
                      ↓
┌──────────────────────────────────────────────┐
│  Indicator Layer                             │
│  registry → normalized signal contracts      │
└──────────────────────────────────────────────┘
                      ↓
┌──────────────────────────────────────────────┐
│  Strategy Engine   ← PURE, no I/O            │
│  entry state machine, exit logic             │
└──────────────────────────────────────────────┘
                      ↓
┌──────────────────────────────────────────────┐
│  Risk / Portfolio                            │
│  sizing, exposure caps, kill switch          │
└──────────────────────────────────────────────┘
                      ↓
┌──────────────────────────────────────────────┐
│  Broker Adapter                              │
│  Backtest │ Paper │ MT5 │ CCXT │ …           │
└──────────────────────────────────────────────┘
                      ↓
┌──────────────────────────────────────────────┐
│  Journal & Observability                     │
└──────────────────────────────────────────────┘
```

---

## 3. Module contracts

### 3.1 Data

```python
class BarFeed(Protocol):
    def bars(self, symbol: str, start: datetime, end: datetime) -> BarFrame: ...
```

`BarFrame` is a strict schema: UTC-indexed, `open/high/low/close/volume`, no gaps, no duplicate timestamps, no partial final bar.

The **session-close convention** (Spec §3) is applied here and nowhere else. Downstream code never re-times bars. `session_close_tz` is a config value; resampling raw H1 data into D1 under different conventions is a data-layer concern.

Implementations: `DukascopyFeed`, `CsvFeed`, `MT5Feed`, `CcxtFeed`.

### 3.2 Indicators

Every indicator is a class registered by name, taking parameters, emitting a normalized contract.

```python
@register("baseline", "kama")
class KAMA(BaselineIndicator):
    def line(self, bars: BarFrame) -> Series[float]: ...

class ConfirmationIndicator(Protocol):
    def signals(self, bars: BarFrame) -> Frame[signal: int, state: int]:
        """signal ∈ {-1,0,+1} — fires on this bar.
           state  ∈ {-1,+1}   — current directional stance."""

class VolumeIndicator(Protocol):
    def gate(self, bars: BarFrame) -> Series[bool]: ...

class ExitIndicator(Protocol):
    def exits(self, bars: BarFrame) -> Series[int]: ...   # -1 exit short, +1 exit long, 0 none

class VolatilityIndicator(Protocol):
    def value(self, bars: BarFrame) -> Series[float]: ...  # ATR lives here
```

**Two hard rules for every indicator wrapper:**

1. **No lookahead.** Value at bar `t` may depend only on bars `≤ t`. Enforced by an automated test that recomputes each indicator on truncated history and asserts the tail values are unchanged.
2. **The wrapper owns normalization.** Converting an indicator's native output (a histogram, a colour change, a band crossing) into `signal`/`state`/`gate` is the wrapper's job. The engine sees only the contract. This is the mechanism that makes indicators genuinely swappable.

### 3.3 Strategy engine

Implements Spec §5 and §6 as an explicit state machine per symbol:

```
FLAT ──(pullback setup qualified)──→ PENDING_PULLBACK ──(expires after 1 bar)──→ FLAT
  │                                          │
  │                                          ↓ (confirmed)
  └────────────(entry qualified)────────→ IN_TRADE
                                              │
                                     (TP1 hit) ↓
                                          RUNNER_BE
                                              │
                                    (+0.5 ATR) ↓
                                          TRAILING
                                              │
                        (baseline cross / exit indi / stop) ↓
                                            FLAT
```

`PENDING_PULLBACK` carries an explicit expiry bar. State is serialized to the journal on every evaluation so a restart resumes exactly where it left off.

Every structural rule from the spec is a boolean flag on the engine config — `bridge_too_far`, `seven_candle_rule`, `one_candle_rule`, `continuation_entries` — so the ablation study in the validation protocol can toggle them without code changes.

### 3.4 Risk & portfolio

```python
class RiskManager(Protocol):
    def size(self, intent, atr, account, instrument) -> list[Position]: ...
    def approve(self, intent, open_positions, account) -> Decision: ...
```

Responsibilities:

- Position sizing per Spec §7, using instrument metadata from the broker adapter (never hardcoded pip values).
- **Sizing quantization guard.** Given the cent-account decision, the manager computes the *realized* risk after rounding to the broker's lot step and rejects the trade if realized risk deviates from target by more than a configured tolerance. This is what stops the small-account problem from silently corrupting the risk model.
- **Correlated exposure cap** (Spec ambiguity A8): limit simultaneous positions per currency. If EURUSD, GBPUSD and AUDUSD all fire long, that is three expressions of one short-USD bet, and the account is carrying 6% risk on a single view, not 2% on three. Cap is a config value, to be set from the correlation analysis.
- **Kill switch.** Evaluated before every order. Halts new entries on breach of the drawdown threshold derived in the validation protocol. Existing positions are managed to their exits rather than dumped.

### 3.5 Broker adapter

```python
class Broker(Protocol):
    def account(self) -> AccountState: ...
    def positions(self) -> list[Position]: ...
    def instrument(self, symbol: str) -> InstrumentSpec: ...   # lot step, min lot, pip value, margin
    def submit(self, order: Order, idempotency_key: str) -> OrderResult: ...
    def modify_stop(self, position_id: str, new_stop: float) -> None: ...
    def close(self, position_id: str, fraction: float = 1.0) -> None: ...
```

`InstrumentSpec` is the market-abstraction boundary (Spec §3b). It declares capabilities rather than a market name:

```python
class InstrumentSpec(BaseModel):
    symbol: str
    market_class: Literal["fx_spot", "crypto_spot", "crypto_perp"]
    can_short: bool
    size_step: Decimal          # 0.01 lots in FX; ~1e-8 in crypto
    min_size: Decimal
    value_per_price_unit: Decimal
    has_funding: bool           # crypto perps
    has_swap: bool              # FX
    has_sessions: bool          # False for crypto — 24/7
    supports_hedging: bool      # False on US-regulated FX; forces single-position mode
    stop_trigger_price: Literal["last", "mark"]   # exchanges use mark; FX uses last
```

The engine branches on these flags, never on `market_class` directly. `supports_hedging=False` and `stop_trigger_price="mark"` are the two that change behaviour rather than just arithmetic, and both need explicit test coverage.

Planned implementations, in build order:

1. `BacktestBroker` — simulated fills with explicit spread, commission, carry (swap *or* funding) and slippage models. Models mark-price stop triggering where the spec demands it.
2. `PaperBroker` — live data, simulated fills. The parity harness.
3. `CcxtBroker` — crypto spot and perpetuals. **Promoted ahead of FX**: better API, free data, no account friction, and it exercises the fractional-sizing path.
4. `MT5Broker` — the FX branch, via the MetaTrader5 Python package.

**Idempotency is mandatory.** Every order carries a deterministic key derived from `(symbol, signal_bar_timestamp, position_index)`. A retry after a timeout can never create a duplicate position — the single most dangerous failure mode in unattended trading.

`InstrumentSpec` is why the US-regulation question mattered: a FIFO/no-hedging venue cannot express two independent same-direction positions, and would require the engine to model one position with a partial close instead. The adapter interface declares its capabilities so the engine can adapt rather than silently misbehave.

---

## 4. Repository layout

```
nnfx/
├── config/
│   ├── system.yaml            # slot assignments, rule flags, risk params
│   ├── instruments.yaml       # pair basket, per-symbol overrides
│   └── venues/                # one file per broker profile
├── nnfx/
│   ├── data/                  # feeds, normalization, session handling
│   ├── indicators/            # registry + one module per indicator
│   ├── engine/                # state machine, entry/exit logic  [PURE]
│   ├── risk/                  # sizing, exposure, kill switch
│   ├── brokers/               # adapters
│   ├── harness/
│   │   ├── backtest.py        # drives engine over history
│   │   └── live.py            # drives engine once per day
│   ├── journal/               # append-only decision log
│   └── research/              # validation protocol tooling
├── tests/
│   ├── test_no_lookahead.py
│   ├── test_engine_rules.py   # hand-built fixtures per entry type
│   └── test_parity.py         # backtest vs live decision equality
└── reports/
```

## 5. Configuration

The entire system's behaviour is one file:

```yaml
slots:
  atr:      { name: atr,  params: { period: 14 } }
  baseline: { name: kama, params: { period: 10, fast: 2, slow: 30 } }
  c1:       { name: ...,  params: {} }
  c2:       { name: ...,  params: {} }
  volume:   { name: ...,  params: {} }
  exit:     { name: ...,  params: {} }

rules:
  bridge_too_far:     true
  bridge_multiple:    1.0
  seven_candle_rule:  true
  seven_candle_bars:  7
  one_candle_rule:    false     # spec ambiguity A7 — off until resolved
  continuation:       true

risk:
  risk_per_position:      0.01
  positions_per_entry:    2
  stop_atr_multiple:      1.5
  tp1_atr_multiple:       1.0
  trail_atr_multiple:     1.5
  trail_step_atr:         0.5
  max_positions_per_ccy:  2       # provisional
  sizing_tolerance:       0.25    # reject if realized risk off-target by >25%

session:
  close_tz: "America/New_York"
  close_hour: 17
```

Two configs differing only in `slots` are two different trading systems. That is the point.

---

## 6. Operational design

**Daily cycle.** The live harness wakes once, shortly after the session close, and runs: fetch bars → verify data integrity → load state from journal → evaluate engine → risk approval → reconcile against broker's actual positions → submit → journal → report.

**Reconciliation before action.** Every run compares the journal's expected position set against the broker's reported positions. Any divergence — a manual intervention, a stop-out the system didn't record, a partial fill — halts trading and alerts rather than trading on a false picture of the account.

**Restart safety.** State lives in the journal, not in memory. The process can be killed at any moment and resume correctly.

**Monitoring.** Daily report: decisions made, orders placed, open risk, equity curve versus backtest expectation, and any rule that was evaluated but blocked. Silence is not success — the system reports even on days it does nothing.

**Hosting.** Target is your own server, containerised, with a scheduled daily invocation. A daily-bar system needs neither low latency nor high availability — it needs to be correct once a day.

---

## 7. Build order

| # | Deliverable | Why first |
|---|---|---|
| 1 | Data layer + session normalization | Everything downstream is wrong if bars are wrong |
| 2 | Indicator registry + no-lookahead test harness | The contract that makes the rest modular |
| 3 | Strategy engine + rule fixtures | Pure logic, fully unit-testable, no broker needed |
| 4 | BacktestBroker + cost model | Makes the engine measurable |
| 5 | Validation protocol execution | Decides whether there is anything worth deploying |
| 6 | Risk manager + kill switch | Thresholds come out of step 5 |
| 7 | PaperBroker + parity harness | Proves live == backtest |
| 8 | CcxtBroker / MT5Broker + deployment | Only now does real money appear |

Steps 1–5 require no broker account, no funding, and no venue decision. That is deliberate: the venue question can stay open for a long time without blocking anything that matters.

**Crypto-specific additions to the risk manager (§3.4):**

- **Leverage constraint:** effective leverage must keep the liquidation price beyond 3×ATR from entry, so the 1.5×ATR stop is always the binding exit. Violation is a sizing bug and blocks the order.
- **Funding accrual:** carried as a running per-position cost, long/short asymmetric, surfaced in the daily report so live carry can be reconciled against the backtest's model.
- **BTC-beta exposure cap:** the crypto analogue of the per-currency cap. Because most instruments track BTC, the cap must be expressed in beta-weighted terms rather than by counting positions — five alt longs is not five bets.
- 