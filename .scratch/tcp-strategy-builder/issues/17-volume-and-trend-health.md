# 17: Volume and trend health

**What to build:** Blocks for the four-state volume matrix, effort vs result (absorption and vacuum), climax detection (volume >= 3-5x baseline with outsized range), low-volume reversal, a 200-bar volume profile, and trend health: swing amplitude decay, impulse vs correction duration, body-to-range decay, close placement progression, colour ratio over 20 bars, and channel excursion as exhaustion.

**Blocked by:** 09 (Market structure and wave cycles), 12 (TCP Azizpour Template (core))

**Status:** resolved

- [x] Volume baselines are relative (no absolute volume constants) and pass the gates
- [x] Trend-health flags can block continuation entries and tighten stops
- [x] Climax can trigger profit-taking as an Exit Block
- [x] Fixtures per metric; Template updated

Spec: `.scratch/tcp-strategy-builder/spec.md`

## Resolution

`strategy/volume.py` (`volume_matrix`, `effort_result`, `volume_climax`, `low_volume_dip`, `volume_node`), `strategy/health.py` (`trend_health` Context Block with six metrics: swing amplitude, impulse/correction duration, body-to-range, close placement, colour ratio, regression-channel excursion), `profit_chain` options `climax_exit` and `health_exit` (tighten/close/both), Template rows (disabled), ADR 10 §21. Notes: all numbers are my defaults (the blueprint gives few); the channel is a regression channel, not a drawn trendline (ticket 19); curvature and candle uniformity are not built.
