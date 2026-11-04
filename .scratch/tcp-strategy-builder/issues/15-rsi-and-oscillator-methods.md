# 15: RSI and the eight oscillator methods

**What to build:** Confirmation and Exit Blocks for the eight oscillator methods: overbought/oversold as momentum, 50/0 inflection, extreme-zone crossovers with a synthetic half-period signal line, horizontal levels on the oscillator, Bollinger on RSI (re-entry setup and exhaustion exit), cycle-length recalibration, MF scaling, and divergences with a pivot in the extreme zone; plus the multi-timeframe RSI cascade for entries and holding. Oscillators never trigger on their own.

**Blocked by:** 09 (Market structure and wave cycles), 12 (TCP Azizpour Template (core))

**Status:** ready-for-agent

- [ ] Each method is a separate Block with parameters
- [ ] Unbounded oscillators use rolling 200-bar extremes for their zones
- [ ] The registry refuses an oscillator Block in a trigger role
- [ ] Fixtures per method; Template updated

Spec: `.scratch/tcp-strategy-builder/spec.md`
