# 24: Order-book snapshots for paper-run symbols

**What to build:** The order-book recorder in the deployment records the Nobitex `/USDT` symbols that paper runs trade, under the same symbol names, and the server can read those recordings. The deployment's recorder and the UI server see the same snapshot directory, so a Paper Run has recorded books to read (ticket 25 wires them into its decisions). Today the recorder's default symbols are `/IRT` ones, so no snapshot matches a paper symbol, and the server has no access to the recordings.

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] The deployment defaults and the example environment record the paper-run `/USDT` symbols, and recorded files are named by exactly the symbol a Paper Run uses (tested)
- [x] The server accepts a recorded-books directory (flag and environment variable) and the deployment mounts the recorder's volume into the server read-only
- [x] Without the option nothing changes: a Paper Run still has no book
- [x] The deployment guide (Persian) explains the symbols and the shared directory

Spec: `.scratch/tcp-strategy-builder/spec.md` (stories 108, 109; ticket 22 limits)

## Resolution

`paper_symbols` (the one list of paper-run symbols, used by the server and the tests), deployment recorder defaults and `.env.example` now include `BTC/USDT` and `ETH/USDT`, `nnfx ui --orderbook DIR` / `NNFX_ORDERBOOK` into `App.orderbook_root`, the recorder volume mounted read-only into the app, Persian guide, ADR 10 §28. Notes: the directory is only handed to the server here (reading it into decisions is ticket 25); an existing deployment must restart the recorder to pick up the new symbols.
