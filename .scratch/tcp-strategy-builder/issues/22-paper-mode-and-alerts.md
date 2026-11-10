# 22: Paper mode and alerts

**What to build:** A user can run a Strategy Document in paper mode on live Nobitex 15m data on the beta server, and receive alerts (in-site and Bale; Telegram via an external relay later) when a Setup Candidate appears and when a Trigger is placed, filled, cancelled or expires.

**Blocked by:** 12 (TCP Azizpour Template (core))

**Status:** resolved

- [x] Paper runs use the same harness as backtests; parity test over recorded bars
- [x] Per-user paper runs can be started and stopped from the UI
- [x] In-site alert feed and Bale bot delivery, each switchable per user
- [x] Alert delivery failures are retried and logged, never block trading decisions

Spec: `.scratch/tcp-strategy-builder/spec.md`

## Resolution

`strategy/paper.py` (`PaperManager`: per-user runs on the live harness with the document engine, state on disk, `LiveBars` from Nobitex), `alerts.py` (alerts from journaled cycles, per-user in-site feed and Bale with retries, failures logged, delivery off the trading path), endpoints `/api/paper/{runs,start,stop}` and `/api/alerts{,/settings}`, the "معاملهٔ کاغذی" tab, `nnfx ui --paper-interval`, deploy volumes and `NNFX_BALE_TOKEN`, ADR 10 §26. Notes: order-book Blocks in paper runs still see no book (honestly `book_missing`); Bale is tested offline only; closes by stop or target are not alerted.
