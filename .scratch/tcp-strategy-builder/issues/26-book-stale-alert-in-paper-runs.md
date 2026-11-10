# 26: Alert when the order book goes stale in a Paper Run

**What to build:** When a Paper Run's document uses order-book Blocks and the recorder stops delivering fresh books for a run's symbol for longer than the Blocks' allowed age, the user is told once per outage through the usual channels (in-site feed, Bale). The run keeps going: while there is no book its order-book Blocks act as their plain counterparts and candidates are marked `book_missing`, as in a backtest with a gap. A second alert says when books are back.

**Blocked by:** 25 (Order-book Blocks see the book in Paper Runs)

**Status:** resolved

- [x] One `book_stale` alert per symbol per outage and one recovery alert, deduplicated across restarts and replayed cycles like other alerts
- [x] The run continues through the outage with its decisions marked `book_missing`; it is not stopped
- [x] Runs whose documents have no order-book Block never raise it
- [x] Alert delivery failure never affects decisions (as for the other alerts)

Spec: `.scratch/tcp-strategy-builder/spec.md` (story 109)

## Resolution

`book_alert` (`book_stale` / `book_back`), `stale_books` and `BookData.has_snapshot`, `PaperManager` tracking each run's stale symbols (`book_stale` in the run's state, so a restart mid-outage does not alert again), ADR 10 §28. Notes: a run that starts while the recorder is down alerts at its first cycle; staleness is judged at the symbol's latest bar, with the Blocks' largest `max_age_seconds`; without a recordings directory nothing is watched.
