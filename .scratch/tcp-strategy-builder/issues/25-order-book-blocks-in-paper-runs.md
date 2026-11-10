# 25: Order-book Blocks see the book in Paper Runs

**What to build:** A Paper Run's order-book Blocks (wall trigger, shielded stop, wall targets) read the recorded books as of each cycle, exactly as an order-book backtest does, instead of acting as their plain counterparts. A cycle sees the snapshots recorded up to its bar, including ones recorded after the server started, without rescanning the whole history each time. The run's checklists carry `book_missing` only where no fresh snapshot existed, and the run reports its stretches without a book.

**Blocked by:** 24 (Order-book snapshots for paper-run symbols)

**Status:** resolved

- [x] Parity: a Paper Run over recorded bars and recorded snapshots decides exactly as the order-book backtest over the same data, cycle for cycle, and a restart on every bar changes nothing
- [x] Snapshots recorded while the server runs are seen by later cycles (the book is not frozen at the first read)
- [x] `book_missing` appears on a candidate only when no fresh two-sided snapshot existed; no-book stretches are reported per run and shown in the paper tab
- [x] A cycle's cost does not grow with the recording's whole history (tested on a long recording)
- [x] ADR 10 §26 limit on paper runs without a book is replaced by the new behaviour

Spec: `.scratch/tcp-strategy-builder/spec.md` (stories 108; order-book Blocks, ticket 21)

## Resolution

`LiveRecordedOrderBook` (incremental reads by byte offset, history window), `BookData.refresh` / `forget_before`, `PaperManager` refreshing the book each cycle and storing `book_gaps` per run, `App` wiring from `orderbook_root`, "دفتر سفارش" column in the paper tab, ADR 10 §26 limit replaced and §28 extended. Notes: only the last two days of recordings are read; walls older than that are forgotten after a restart.
