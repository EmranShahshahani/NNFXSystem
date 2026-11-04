# 17: Volume and trend health

**What to build:** Blocks for the four-state volume matrix, effort vs result (absorption and vacuum), climax detection (volume >= 3-5x baseline with outsized range), low-volume reversal, a 200-bar volume profile, and trend health: swing amplitude decay, impulse vs correction duration, body-to-range decay, close placement progression, colour ratio over 20 bars, and channel excursion as exhaustion.

**Blocked by:** 09 (Market structure and wave cycles), 12 (TCP Azizpour Template (core))

**Status:** ready-for-agent

- [ ] Volume baselines are relative (no absolute volume constants) and pass the gates
- [ ] Trend-health flags can block continuation entries and tighten stops
- [ ] Climax can trigger profit-taking as an Exit Block
- [ ] Fixtures per metric; Template updated

Spec: `.scratch/tcp-strategy-builder/spec.md`
