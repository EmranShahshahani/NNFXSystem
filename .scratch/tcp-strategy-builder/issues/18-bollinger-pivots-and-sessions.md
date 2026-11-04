# 18: Bollinger, pivots and sessions

**What to build:** Blocks for higher-timeframe-directed Bollinger touches and mid-line crosses, Bollinger squeeze and expansion, the double Bollinger 'momentum runway', floor-trader pivots on 4H and weekly (beyond R1/S1 as confirmation, R3/R4 and S3/S4 as exits), and sessions (Asia, London, New York in UTC; no new entries 21:00-00:00 UTC; session regimes).

**Blocked by:** 12 (TCP Azizpour Template (core))

**Status:** ready-for-agent

- [ ] Each rule is a switchable Block
- [ ] Pivots are computed only from closed 4H/weekly periods
- [ ] Session filter is UTC-based and tested across DST boundaries
- [ ] Fixtures per rule; Template updated

Spec: `.scratch/tcp-strategy-builder/spec.md`
