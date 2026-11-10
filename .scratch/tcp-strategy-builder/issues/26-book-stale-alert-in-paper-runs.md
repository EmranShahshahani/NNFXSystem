# 26: Alert when the order book goes stale in a Paper Run

**What to build:** When a Paper Run's document uses order-book Blocks and the recorder stops delivering fresh books for a run's symbol for longer than the Blocks' allowed age, the user is told once per outage through the usual channels (in-site feed, Bale). The run keeps going: while there is no book its order-book Blocks act as their plain counterparts and candidates are marked `book_missing`, as in a backtest with a gap. A second alert says when books are back.

**Blocked by:** 25 (Order-book Blocks see the book in Paper Runs)

**Status:** ready-for-agent

- [ ] One `book_stale` alert per symbol per outage and one recovery alert, deduplicated across restarts and replayed cycles like other alerts
- [ ] The run continues through the outage with its decisions marked `book_missing`; it is not stopped
- [ ] Runs whose documents have no order-book Block never raise it
- [ ] Alert delivery failure never affects decisions (as for the other alerts)

Spec: `.scratch/tcp-strategy-builder/spec.md` (story 109)
