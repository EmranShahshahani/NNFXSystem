# 15: RSI and the eight oscillator methods

**What to build:** Confirmation and Exit Blocks for the eight oscillator methods: overbought/oversold as momentum, 50/0 inflection, extreme-zone crossovers with a synthetic half-period signal line, horizontal levels on the oscillator, Bollinger on RSI (re-entry setup and exhaustion exit), cycle-length recalibration, MF scaling, and divergences with a pivot in the extreme zone; plus the multi-timeframe RSI cascade for entries and holding. Oscillators never trigger on their own.

**Blocked by:** 09 (Market structure and wave cycles), 12 (TCP Azizpour Template (core))

**Status:** resolved

- [x] Each method is a separate Block with parameters
- [x] Unbounded oscillators use rolling 200-bar extremes for their zones
- [x] The registry refuses an oscillator Block in a trigger role
- [x] Fixtures per method; Template updated

Spec: `.scratch/tcp-strategy-builder/spec.md`

## Resolution

`strategy/oscillators.py` (nine Confirmation Blocks, all `oscillator = True`; `register` refuses that flag on Setup and Execution kinds), `profit_chain` options `rsi_exhaustion_exit` and `hold_while_rsi_role`, the Template rows (disabled), ADR 10 §19. Notes: unbounded zones are 0.8 of the prior 200-bar extremes; trendlines on the oscillator are not built (horizontal levels only); the exhaustion exit does not also require price at resistance.
