# 11: Levels, touches, boxes and breakout confirmation

**What to build:** Horizontal levels mapped from higher timeframes with recency weighting and polarity flips, levels owned by the timeframe they were drawn on, touch counting (1st touch: no breakout; 2nd: needs extra confluence; 3rd-4th: preferred), Box detection with volume dry-up, the Box Breakout setup, and breakout confirmations: body close (wicks are sweeps), range >= 1.5x the six-bar average, and N consecutive closes (8 on 15m, 4 on 4H, 2 on daily).

**Blocked by:** 09 (Market structure and wave cycles)

**Status:** ready-for-agent

- [ ] Levels and boxes are causal and pass the gates
- [ ] A 15m close beyond a 4H level does not count as a 4H breakout
- [ ] Touch-count rule enforced with parameters
- [ ] Box Breakout setup emits a candidate with trigger beyond the edge and stop per blueprint
- [ ] Each breakout confirmation is a separate Confirmation Block
- [ ] Two-way box mode (ticket 09): stop-buy and stop-sell triggers at the box extremes when `wave_cycles` reports the box
- [ ] Fixtures for sweep vs breakout, first-touch refusal, and each confirmation

Spec: `.scratch/tcp-strategy-builder/spec.md`
