# 18: Bollinger, pivots and sessions

**What to build:** Blocks for higher-timeframe-directed Bollinger touches and mid-line crosses, Bollinger squeeze and expansion, the double Bollinger 'momentum runway', floor-trader pivots on 4H and weekly (beyond R1/S1 as confirmation, R3/R4 and S3/S4 as exits), and sessions (Asia, London, New York in UTC; no new entries 21:00-00:00 UTC; session regimes).

**Blocked by:** 12 (TCP Azizpour Template (core))

**Status:** resolved

- [x] Each rule is a switchable Block
- [x] Pivots are computed only from closed 4H/weekly periods
- [x] Session filter is UTC-based and tested across DST boundaries
- [x] Fixtures per rule; Template updated

Spec: `.scratch/tcp-strategy-builder/spec.md`

## Resolution

`strategy/bands.py` (`bb_htf_touch`, `bb_squeeze`, `bb_runway`), `strategy/pivots.py` (`pivot_breach`; H4/weekly floor pivots from closed periods only), `strategy/sessions.py` (`session_filter` with the 21:00-00:00 UTC blackout, `session_regime`), `profit_chain` options `runway_exit` and `pivot_exit` (r3/r4/both), Template rows (disabled), ADR 10 §22. Notes: pivot formulas are the "traditional" set (the blueprint gives none); sessions are UTC-only and tested across four DST changes; regime 2 is judged at the US-window start.
