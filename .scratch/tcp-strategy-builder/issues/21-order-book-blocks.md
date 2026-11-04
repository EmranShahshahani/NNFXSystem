# 21: Order-book Blocks

**What to build:** Execution, Stop and Exit Blocks using the Order Book Source: move a trigger just beyond the largest persistent ask wall above resistance (mirror for shorts), abort a breakout when volume contracts into a heavy wall, shield the stop behind the nearest persistent bid wall, and place targets just in front of opposing walls. In backtests without recorded snapshots these Blocks are not-applicable and the run is flagged.

**Blocked by:** 04 (Order Book Source and recorder), 07 (Profit Chain and position management), 12 (TCP Azizpour Template (core))

**Status:** ready-for-agent

- [ ] Spoof walls never move orders
- [ ] Wall thresholds are relative to the book's own depth distribution
- [ ] Backtest results show which periods lacked book data
- [ ] Fixture-based tests for each adjustment; Template updated

Spec: `.scratch/tcp-strategy-builder/spec.md`
