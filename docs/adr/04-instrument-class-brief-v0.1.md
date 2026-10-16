# Decision Brief — Spot vs Perpetual Futures vs Margin (Crypto)

**Question:** Which crypto instrument class should the NNFX engine trade?
**Status:** Recommendation made; final choice yours.

---

## 1. The four properties NNFX actually cares about

The system was designed on spot FX, which quietly provides all four. Crypto instrument classes each break at least one.

1. **Symmetry** — can you take short signals? NNFX generates long and short signals with equal frequency and treats them identically.
2. **Carry** — what does a multi-week hold cost? NNFX holds trends for weeks; carry compounds.
3. **Sizing fidelity** — can position size be arbitrary? ATR-scaled risk requires it.
4. **Forced exit** — can you be removed from a correct position by something other than your stop?

---

## 2. Spot

| Property | Assessment |
|---|---|
| Symmetry | ❌ **No shorting** |
| Carry | ✅ Zero |
| Sizing | ✅ Fully fractional |
| Forced exit | ✅ Impossible |

**The decisive issue is symmetry, and it's bigger than "you lose half the trades."**

NNFX is a trend-following system. Crypto's most sustained, cleanest trends have been *downtrends* — 2018 and 2022 both trended down for the better part of a year with low noise. Those are precisely the conditions trend-following exists to harvest. A spot-only system sits in cash through them.

What you'd actually be building is a **long-only trend filter** — a timing overlay on buy-and-hold, not the NNFX system. That may still be a perfectly good thing to own. But it must be *validated as what it is*: you cannot test the symmetric system and then trade half of it, because the tested edge and the traded edge are different objects.

**Verdict:** Safest and simplest. Structurally a different system.

---

## 3. Perpetual futures

| Property | Assessment |
|---|---|
| Symmetry | ✅ Full, and identical mechanics both directions |
| Carry | ⚠️ Funding rate, settled ~3×/day |
| Sizing | ✅ Fractional, subject to contract step |
| Forced exit | ⚠️ Liquidation — but see below |

**This is the only faithful implementation of NNFX in crypto.**

**On funding.** Perpetuals hold their price to spot via a funding payment between longs and shorts, typically every 8 hours. When funding is positive — the usual state in a bull market — longs pay shorts. Two consequences the backtest must model rather than assume away:

- On a multi-week hold, funding is the crypto analogue of FX swap and can be material. It is not a rounding error.
- **It is asymmetric.** Shorts *receive* funding in bull markets; longs *pay* it. This systematically biases the measured performance of long versus short signals. If funding isn't modelled per-hold, the backtest will misattribute a carry effect as signal quality.

**On liquidation — this matters less than people assume, if sizing is correct.** Your stop is 1.5×ATR from entry. Liquidation only ever triggers if the liquidation price sits *closer* than the stop. With 1% risk per position, the required leverage is low, and the liquidation distance can trivially be kept beyond 3×ATR — at which point the stop always fires first and liquidation becomes unreachable in normal operation.

**Design rule: liquidation distance must exceed 3× ATR at all times. If it doesn't, the position is mis-sized — liquidation risk is a symptom of a sizing bug, not an inherent cost of perpetuals.**

**Real residual risks**, which are operational rather than strategic:

- **Mark-price stop semantics.** Exchanges trigger stops on *mark price*, not last traded price. The backtest must model this or it will disagree with live execution during wicks — a classic parity failure.
- **Auto-deleveraging (ADL).** In extreme moves, a profitable position can be forcibly closed by the exchange. Rare, but real, and unmodellable — accept it as tail risk.
- **Counterparty risk.** Your capital sits on the exchange. This is the largest genuine risk in crypto trading and no backtest captures it.
- **History depth.** Perpetual contracts are younger than spot — major USDT perps generally date from 2019–2020, versus 2017 for liquid spot. This *shortens an already short sample*. Mitigation: generate signals from spot price history (longer) and model funding as a separate cost layer, validating the two together. This must be done carefully and documented, since it is a splice of two data sources.

**Verdict:** Faithful to the system. Costs are modellable. Recommended.

---

## 4. Spot margin

| Property | Assessment |
|---|---|
| Symmetry | ✅ Via borrow |
| Carry | ❌ Borrow interest — higher and less predictable than funding |
| Sizing | ✅ Fractional |
| Forced exit | ⚠️ Liquidation |

Shorting requires borrowing the asset. Borrow rates are typically worse than perpetual funding, less predictable, and — the killer — **borrow availability disappears for smaller coins exactly when everyone wants to short them**, which is exactly when your system wants to short them too. You'd be building a system whose short signals silently fail to execute under the conditions that generate them.

**Verdict:** Same risks as perpetuals, worse liquidity, less predictable cost, no compensating advantage. Rejected.

---

## 5. Side-by-side

| | Spot | Perpetuals | Spot margin |
|---|---|---|---|
| Short signals | No | Yes | Yes, unreliably |
| Holding cost | None | Funding, ~3×/day, asymmetric | Borrow interest, volatile |
| Sizing fidelity | Perfect | Near-perfect | Near-perfect |
| Forced exit | None | Liquidation (avoidable by sizing) | Liquidation |
| History depth | 2017+ | 2019/2020+ | Varies |
| Faithful to NNFX | No | Yes | Partially |
| Operational complexity | Lowest | Moderate | Highest |

---

## 6. Recommendation

**Perpetual futures at low effective leverage**, with these design constraints written into the spec:

1. Funding modelled as an explicit per-period cost, with long/short asymmetry preserved.
2. Leverage chosen so liquidation distance exceeds 3×ATR — stops are the only exit mechanism that ever fires.
3. Stop triggering modelled on mark price, matching exchange behaviour.
4. Counterparty risk managed operationally: API keys with trading permission but **withdrawal disabled**, IP allowlisting, and capital on-exchange limited to what you would accept losing entirely to an exchange failure.

**And — validate the spot long-only variant as a benchmark in the same protocol.** This costs little extra since the engine already supports disabling short entries via a rule flag. If long-only spot performs comparably, take it: it is strictly safer, structurally simpler, and carries no funding, liquidation, or leverage risk.

That's an empirical question, and the validation protocol should be the thing that answers it rather than either of us guessing now.
