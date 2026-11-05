# 09: Market structure and wave cycles

**What to build:** Context Blocks for structure: confirmed swing pivots, Dow trend state per timeframe, HWC/MWC/LWC roles setting allowed directions, the bottom-up reversal sequence, the failed-peak rule, 'don't short the LWC downtrend' inside an HWC uptrend, and the two-way box mode when HWC and MWC both range.

**Blocked by:** 01 (Intraday base bars and multi-timeframe views), 05 (Strategy Document tracer bullet)

**Status:** resolved

- [x] Pivots are confirmed k bars later and pass the no-lookahead gate
- [x] Dow state (up/down/range) per timeframe role
- [x] HWC sets allowed directions; LWC counter-moves are never shorted in an HWC uptrend (and the mirror)
- [x] A trend ends only on a failed new high plus a neckline break
- [x] Reversal requires LWC then MWC change before HWC is treated as flat
- [x] Two-way box mode can be enabled when HWC and MWC are both ranging, with 2R-3R targets
- [x] Candidates against the higher-timeframe primary trend (secondary waves) carry the `counter_trend` tag, so the Profit Chain's `counter_trend: tagged` mode applies to them (ticket 07)
- [x] Harness-level fixtures for each rule

Spec: `.scratch/tcp-strategy-builder/spec.md`
