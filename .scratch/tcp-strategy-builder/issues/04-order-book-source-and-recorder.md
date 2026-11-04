# 04: Order Book Source and recorder

**What to build:** The system can read order-book snapshots from one interface with three providers: live Nobitex, recorded snapshots, and test fixtures. A recorder stores snapshots at a configurable interval (CLI command and a deployable service). Wall detection is relative to the book's own depth and requires persistence across snapshots; walls that step back or vanish as price approaches are classified as spoofs.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] One Order Book Source interface with live-Nobitex, recorded and fixture providers
- [ ] The live provider parses the documented Nobitex order-book response (tested offline)
- [ ] A recorder command stores snapshots for chosen symbols at a configurable interval; the deploy stack can run it as a service
- [ ] Wall detection marks clusters above a configurable depth percentile that persist across N snapshots
- [ ] Spoof classification is tested with fixtures where a wall steps back or disappears as price approaches
- [ ] Depth needed to move price by x% is computable from a snapshot

Spec: `.scratch/tcp-strategy-builder/spec.md`
