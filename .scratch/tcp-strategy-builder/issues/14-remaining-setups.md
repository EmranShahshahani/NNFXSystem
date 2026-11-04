# 14: Remaining setups

**What to build:** Setup Blocks for Engulfing (body covers the previous full range, after prior weakness), Giant Indecision Reversal (range and volume above the last 10 bars, entry beyond its opposite side after higher-timeframe weakness), Absorption Wick, the LA layered setup (higher low inside a box, faster pushes up), Dow continuation, binary scenario mode (OCO stop-buy and stop-sell around a box with volume and RSI conditions), momentum-continuation mode, and chase blocking after outsized impulse bars. Each is added to the Template per the blueprint.

**Blocked by:** 10 (3-SMA system and full Candle Setup), 11 (Levels, touches, boxes and breakout confirmation), 12 (TCP Azizpour Template (core))

**Status:** ready-for-agent

- [ ] Each setup emits candidates with trigger, invalidation and stop per the blueprint
- [ ] Binary scenario uses OCO from ticket 02
- [ ] Chase blocking refuses entries after a bar whose range exceeds a parameter multiple of normal
- [ ] Fixtures for fire / no-fire per setup; Template updated

Spec: `.scratch/tcp-strategy-builder/spec.md`
