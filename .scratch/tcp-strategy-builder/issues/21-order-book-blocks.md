# 21: Order-book Blocks

**What to build:** Execution, Stop and Exit Blocks using the Order Book Source: move a trigger just beyond the largest persistent ask wall above resistance (mirror for shorts), abort a breakout when volume contracts into a heavy wall, shield the stop behind the nearest persistent bid wall, and place targets just in front of opposing walls. In backtests without recorded snapshots these Blocks are not-applicable and the run is flagged.

**Blocked by:** 04 (Order Book Source and recorder), 07 (Profit Chain and position management), 12 (TCP Azizpour Template (core))

**Status:** resolved

- [x] Spoof walls never move orders
- [x] Wall thresholds are relative to the book's own depth distribution
- [x] Backtest results show which periods lacked book data
- [x] Fixture-based tests for each adjustment; Template updated

Spec: `.scratch/tcp-strategy-builder/spec.md`

## Resolution

`strategy/book.py` (`BookData`: snapshots fed once to a `WallTracker`, state read as of the candidate's time, never later, stale or one-sided is none), `strategy/orderbook_blocks.py` (`wall_trigger` with the volume-contraction abort, `wall_shielded_stop`, `wall_targets` extending the Profit Chain), `StrategyData.book`, the engine's `book_missing` journal key and `book_blocks`, `DocumentRun.incomplete` now covering order-book Blocks plus `book_gaps` and `book_missing_candidates`, `nnfx strategy backtest --orderbook DIR`, Template rows (disabled), ADR 10 §25. Notes: without a book each Block is its plain counterpart; targets never go below 2R; the abort lives in `wall_trigger` (an Execution Block cannot veto another's); the UI cannot upload recordings yet.
