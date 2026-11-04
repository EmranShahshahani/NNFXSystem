# 22: Paper mode and alerts

**What to build:** A user can run a Strategy Document in paper mode on live Nobitex 15m data on the beta server, and receive alerts (in-site and Bale; Telegram via an external relay later) when a Setup Candidate appears and when a Trigger is placed, filled, cancelled or expires.

**Blocked by:** 12 (TCP Azizpour Template (core))

**Status:** ready-for-agent

- [ ] Paper runs use the same harness as backtests; parity test over recorded bars
- [ ] Per-user paper runs can be started and stopped from the UI
- [ ] In-site alert feed and Bale bot delivery, each switchable per user
- [ ] Alert delivery failures are retried and logged, never block trading decisions

Spec: `.scratch/tcp-strategy-builder/spec.md`
