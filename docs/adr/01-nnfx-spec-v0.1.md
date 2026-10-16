# NNFX System Specification — v0.1 (Rule Codification)

**Status:** Draft for review. This is the *rules* document, not the architecture document.
**Purpose:** Convert the No Nonsense Forex system from video/prose form into unambiguous, implementable logic — and, just as importantly, produce an explicit register of everything the source material leaves ambiguous.

**Locked project decisions (rev. 2026-08-27):**

| Decision | Choice |
|---|---|
| Fidelity | NNFX skeleton kept; every rule re-validated statistically. Deviations documented. |
| Stack | Python throughout (strict `mypy`, `pydantic` data contracts, `ruff`) |
| Markets | **Crypto and forex both validated; primary market decided by the data** |
| Crypto instrument | Perpetual futures recommended, spot long-only as benchmark — see `04` |
| Universe | Crypto: top 10–20 by liquidity. FX: 28 majors/crosses. |
| Automation | Full automation, gated behind a parity phase |
| Capital | Under $1,000 — no longer a constraint in crypto (see §11) |
| Kill-switch | Derived from validated backtest, approved before go-live |
| Venue | Undecided; engine is venue-agnostic by design |
| Implementation | **Emran codes in his own IDE. Deliverables here are specs, contracts and acceptance criteria — not source files.** |

---

## 1. Provenance

Sources used for this codification:

- nononsenseforex.com (the system's home; the "Backtesting Step By Step" podcast page)
- The NNFX entry/exit flow charts (nononsensetrader.com PDF) — the most precise public statement of the rules
- The No Nonsense Trader starter guides (Parts 1 & 2) and Daily Routine page
- Third-party implementations (fxDreema, TradingView Pine ports, NNFX Algo Tester) used as *corroboration only*, never as authority

Where sources conflict, the flow charts win, and the conflict is logged in §8.

---

## 2. The six slots

The system is a fixed decision skeleton with six replaceable components. The engine must never know which concrete indicator fills a slot.

| Slot | Role | Output contract |
|---|---|---|
| **ATR** | Volatility unit. Drives stop, target, sizing, and the distance filter. Not a signal. | `float` per bar, price units |
| **Baseline** | Trend arbiter and the distance reference. | `float` line per bar |
| **C1** (Confirmation 1) | The trigger. Fires discrete entry signals. | `signal ∈ {+1, 0, −1}` and `state ∈ {+1, −1}` |
| **C2** (Confirmation 2) | The veto. Slower, stricter. Must *agree*; need not fire. | `state ∈ {+1, −1}` |
| **Volume / Volatility** | Gate. Is there enough force behind the move? | `bool` |
| **Exit** | Dedicated exit trigger, independent of entry logic. | `signal ∈ {exit_long, exit_short, none}` |

Optional seventh slot: **Continuation indicator**, used only by continuation entries (§5.D).

**Design rule:** every indicator is wrapped to emit this normalized contract. The engine consumes only the contract. Swapping RSI for Waddah Attar must be a config line, never a code change.

---

## 3. Bar and timing convention

This section is the one most implementations get silently wrong.

- **Timeframe:** Daily (D1), exclusively.
- **Decision point:** All logic evaluates on the **completed** bar `t`. No intrabar decisions.
- **Execution point:** Market order at the open of bar `t+1`.
- **The daily close is a configuration parameter, not a given.** A broker cutting the day at 17:00 New York produces different bars, different ATR, and different signals than one cutting at 00:00 UTC. `session_close_tz` is an explicit config value, and the backtest must be run across candidate conventions to measure sensitivity. If results swing wildly by close-time, the edge is fragile and we need to know that before funding anything.
- **Weekend/holiday bars:** Sunday partial bars are merged into Monday. Broker-specific; must be normalized in the data layer.

---

## 3b. Market abstraction — what changes between FX and crypto

The rule engine is market-agnostic. Everything market-specific lives behind the instrument abstraction. This table is the complete list of what differs.

| Concern | Forex | Crypto |
|---|---|---|
| **Session close** | Genuinely ambiguous; broker-dependent (17:00 NY typical). Must be tested. | Market is 24/7; 00:00 UTC is the near-universal exchange convention. Ambiguity A1 largely dissolves, but the convention is still a config value and still worth a sensitivity check. |
| **Weekend gaps** | Real and material — Friday close to Monday open gaps jump stops. | None. Continuous. Removes a whole class of gap risk. |
| **Carry cost** | Swap, nightly, per-pair, both directions. | Funding rate on perpetuals, ~3×/day, **asymmetric between long and short**. Zero on spot. |
| **Volume data** | Tick volume only — a count of price changes, not traded size. A known weakness of the Volume slot in FX. | Genuine traded volume. The Volume slot is *better founded* in crypto than in the market NNFX was designed for. |
| **Sizing granularity** | Lot-quantized; minimum 0.01 lots (or 0.0001 on cent accounts). Quantization guard required. | Fractional to many decimal places. **Quantization is a non-issue.** |
| **Shorting** | Symmetric and free. | Requires perpetuals or margin — see `04-instrument-class-brief`. |
| **Forced exit** | Margin call only. | Liquidation, avoidable by sizing (see `04`). |
| **Instrument mortality** | Pairs don't die. | Coins delist. Survivorship bias is a live threat to the backtest. |
| **Usable history** | 20+ years. | ~2017 spot, ~2019/2020 perpetuals. The binding constraint on validation. |
| **Correlation structure** | 28 pairs from 8 currencies — meaningful independence, USD-clustered. | Near-everything tracks BTC. Effective independent bets ≈ 1–3 regardless of instrument count. |

**Design consequence:** `InstrumentSpec` carries a `market_class` and the engine branches only on capability flags (`can_short`, `has_funding`, `has_sessions`, `size_step`), never on a market name.

## 4. Core quantities

```
ATR_t        = ATR(14, Wilder) evaluated on bar t
B_t          = baseline value at bar t
C_t          = close of bar t
distance_t   = |C_t − B_t|
```

**Bridge-Too-Far filter:** `distance_t ≤ 1.0 × ATR_t`

Rationale: if price has already run more than one full unit of volatility away from the trend line, the move is extended and the reward-to-risk on a fresh entry is degraded.

---

## 5. Entry logic

All entry types produce: `(direction d ∈ {+1,−1}, entry_bar = t+1)`.

### A. Standard entry
```
C1.signal_t == d
AND sign(C_t − B_t) == d               # baseline agrees
AND distance_t ≤ 1.0 × ATR_t           # bridge-too-far
AND C2.state_t == d
AND Volume.gate_t == True
```

### B. Baseline entry
Triggered by price crossing the baseline rather than by C1 firing.
```
sign(C_t − B_t) == d AND sign(C_{t−1} − B_{t−1}) != d    # fresh cross
AND C1.state_t == d
AND age(last C1 signal in direction d) ≤ 7 bars          # 7-candle rule
AND C2.state_t == d
AND Volume.gate_t == True
AND distance_t ≤ 1.0 × ATR_t
```
The 7-candle rule prevents entering on a stale confirmation.

### C. Pullback entry
```
IF a Standard or Baseline entry satisfied every condition EXCEPT distance_t ≤ 1×ATR_t:
    wait exactly one bar
    IF distance_{t+1} ≤ 1.0 × ATR_{t+1} AND all other conditions still hold at t+1:
        enter at open of t+2
    ELSE: setup expires
```
The setup has a lifetime of exactly one bar. It does not linger.

### D. Continuation entry
Adds to an existing trend that has not been invalidated.
```
baseline has NOT been crossed since the original entry signal
AND Continuation.signal_t == d
AND C1.state_t == d
AND sign(C_t − B_t) == d
```
Bridge-too-far and the 1-Candle Rule do **not** apply to continuations — by construction price is already extended.

### E. 1-Candle Rule (1CR) — resolved as *irreducibly ambiguous*

Applies to Standard and Baseline entries only. **Investigated 2026-08-27; no canonical definition exists.** VP's own treatment is a podcast episode with no published transcript; the community has no consensus; independent implementations differ; and a prominent NNFX teacher publicly argues the rule contradicts the 7-candle rule. See §8 A7 for the full finding.

Two coherent readings survive the evidence. Both are specified here, both are implemented, both are flagged, and the ablation study decides.

**Variant 1CR-A — "grace period for a lagging condition."**
The reading best supported by working implementations. A setup fires but exactly one required condition is unmet — most commonly the Volume gate, sometimes C2.
```
at bar t: entry conditions satisfied EXCEPT exactly one of {Volume.gate, C2.state}
at bar t+1: the missing condition now agrees
            AND all other conditions still hold at t+1
            AND distance_{t+1} ≤ 1.0 × ATR_{t+1}
→ enter at open of t+2; otherwise the setup expires
```
Grace period is exactly one bar. The C1 signal is read from bar `t`, everything else from `t+1`.

**Variant 1CR-B — "retracement requirement."**
The reading implied by the flow charts' *"The Price RETRACTED"* node.
```
at bar t: entry conditions fully satisfied
at bar t+1: price retraced against the signal direction (close_{t+1} against d relative to close_t)
            AND all conditions still hold
→ enter at open of t+2; otherwise the setup expires
```

**Both default to OFF.** Neither ships enabled until the ablation study shows it adds expectancy.

**Known design tension (record, don't resolve by argument):** the 7-candle rule tolerates a C1 signal up to seven bars stale, while 1CR grants only one bar of grace. These are motivated inconsistently. Whether either matters is an empirical question, and the ablation study tests them jointly rather than in isolation.

---

## 6. Exit logic

A position exits, fully, on the **first** of:

1. Close crosses the baseline against the position.
2. Exit indicator fires against the position.
3. If no exit indicator is configured: an opposite signal from C1 or C2.
4. Stop loss or final take-profit is hit.

No re-entry on the same bar as an exit.

---

## 7. Money management

Every entry opens **two positions**, each risking 1% of equity — 2% total.

| Element | Rule |
|---|---|
| Stop loss (both positions) | `1.5 × ATR_entry` from entry price |
| Take profit (position 1) | `1.0 × ATR_entry` from entry price |
| Position 2 | No fixed target; managed by trailing stop and §6 exits |
| On TP1 hit | Position 2's stop moves to breakeven |
| Thereafter | Trail at `1.5 × ATR` distance, stepped in `0.5 × ATR` increments of favorable movement |

**ATR is frozen at entry** for stop/target/sizing (decision — see Ambiguity A3).

### Position sizing
```
risk_cash      = 0.01 × account_equity
stop_distance  = 1.5 × ATR_entry              # in price units
units          = risk_cash / (stop_distance × value_per_price_unit)
```
`value_per_price_unit` is instrument- and account-currency-specific and comes from the broker adapter, never hardcoded.

---

## 8. Ambiguity register

Every item here is a place where the source material is silent, contradictory, or open to reading. Each must be resolved by decision + test, and each resolution recorded with its rationale. **This register is the honest core of the project.**

| # | Ambiguity | Provisional decision | How it gets resolved |
|---|---|---|---|
| A1 | Daily close convention | Config parameter, default 17:00 New York | Sensitivity test across conventions |
| A2 | Entry at signal-bar close vs next-bar open | Next-bar open | Realism; measure the cost of the difference |
| A3 | ATR frozen at entry vs recalculated each bar | Frozen | Test both; frozen is the more conservative reading |
| A4 | Must C2 *fire*, or merely *agree*? | Agree (state, not signal) | Flow charts imply agreement; test both |
| A5 | Volume gate semantics differ per indicator | Normalize to boolean at the wrapper | Per-indicator wrapper spec |
| A6 | 7-candle rule: inclusive of signal bar? | Inclusive (signal bar counts as bar 1) | Test off-by-one sensitivity |
| A7 | **1-Candle Rule exact definition** | **RESOLVED 2026-08-27: no canonical definition exists.** Two variants specified (§5.E), both flagged, both default off | Ablation study decides. Sources: VP's Ep39 podcast (audio only, no transcript); fxDreema implementer threads (implement 1CR-A via candle-ID offset, triggered by an unconfirmed Volume gate); No Nonsense Trader Lesson 9 (declines to define it and argues it contradicts the 7-candle rule) |
| A8 | Max concurrent exposure per currency | Unresolved — likely needs a cap | Portfolio-level correlation analysis |
| A9 | News / rollover avoidance: in-algo or discretionary? | Unresolved | Decide; if in-algo, needs a calendar feed |
| A10 | Which pairs, and how many | Unresolved | Constrained by capital (see Open Risk #1) |
| A11 | Trailing stop: does it use frozen or live ATR? | Live ATR | Test both |

---

## 9. Deliberate deviations from VP

Documented so they are choices, not drift.

**D1 — Validation methodology, replaced entirely.** VP recommends ~2 years of daily data, scoring indicators on raw win% and keeping the top 3–5. On daily bars that is a few hundred trades; ranking dozens of indicators on that sample selects mostly noise, and win% ignores the system's asymmetric payoff (risking 1.5R to make 1R on the first position). We will instead use: long history, an untouched out-of-sample holdout, walk-forward analysis, expectancy and distribution of R-multiples rather than win%, and explicit correction for testing many indicators. Detailed in the forthcoming validation protocol document.

**D2 — Every structural rule is testable.** The 7-candle rule, the 1×ATR bridge, 1CR, and continuation entries each get an on/off flag and are measured for their marginal contribution. Rules that don't earn their keep are disabled, and the fact is recorded.

**D3 — Costs modeled explicitly.** Spread, commission, swap/rollover and realistic slippage are in the backtest from day one, not added later. A daily trend system's edge is not fragile to costs the way a scalper's is, but at small account sizes the *quantization* of position size is a real distortion and will be modeled.

---

## 10. Open risks

**#1 — Capital. RESOLVED for crypto; managed for FX.** Under $1,000 with 2% risk split into two 1% positions means roughly $10 of risk per position. In **crypto this is a non-issue**: fractional sizing means a $10 risk budget expresses exactly as a $10 risk budget, at full ATR fidelity, on any instrument. This is a genuine and underrated argument for the crypto pivot. In **FX** the constraint stands and is handled by a cent/nano-lot account plus the sizing quantization guard (Architecture §3.4), which rejects any trade whose post-rounding realized risk deviates from target beyond tolerance.

**#2 — Venue.** Deliberately open. The engine is venue-agnostic and steps 1–5 of the build require no account. For crypto, exchange counterparty risk is the material concern rather than access: keys without withdrawal permission, IP allowlisting, and on-exchange capital capped at what a total exchange failure could be absorbed.

**#4 — Short crypto history.** ~2017 for liquid spot, ~2019–2020 for perpetuals, against 20+ years in FX. This is the single largest threat to honest validation in the crypto branch and is addressed directly in the validation protocol (`03`, §3b).

**#3 — Full automation from day one.** Accepted as the user's choice. Mitigation is non-negotiable: a demo-account parity phase where the live engine and the backtest engine are fed identical data and must produce identical decisions, before any real capital is connected. This is not manual trading — it is proving the machine is the machine we tested.

---

*Next documents: (2) Architecture & module contracts, (3) Data & validation protocol, (4) Venue evaluation.*
