# 24: Order-book snapshots for paper-run symbols

**What to build:** The order-book recorder in the deployment records the Nobitex `/USDT` symbols that paper runs trade, under the same symbol names, and the server can read those recordings. The deployment's recorder and the UI server see the same snapshot directory, so a Paper Run has recorded books to read (ticket 25 wires them into its decisions). Today the recorder's default symbols are `/IRT` ones, so no snapshot matches a paper symbol, and the server has no access to the recordings.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] The deployment defaults and the example environment record the paper-run `/USDT` symbols, and recorded files are named by exactly the symbol a Paper Run uses (tested)
- [ ] The server accepts a recorded-books directory (flag and environment variable) and the deployment mounts the recorder's volume into the server read-only
- [ ] Without the option nothing changes: a Paper Run still has no book
- [ ] The deployment guide (Persian) explains the symbols and the shared directory

Spec: `.scratch/tcp-strategy-builder/spec.md` (stories 108, 109; ticket 22 limits)
