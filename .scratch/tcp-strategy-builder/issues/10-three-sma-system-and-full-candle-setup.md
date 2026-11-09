# 10: 3-SMA system and full Candle Setup

**What to build:** The full 3-SMA context (alignment with slopes, Choppy Regime, 99 SMA direction filter, overextension guard, SMA 7 flattening stops entries, SMA 25 flattening triggers profit-taking, crossovers as hold-confirmation only) and the full Candle Setup (wick >= 1.5-2x body, small opposite wick, SMA 7 behind the wick and never through the body, SMA 7 sloping with the trade, Second Wave, RSI 14 entering >70/<30, volume conditions, trigger at high/low +/- buffer, cancel on invalidation close).

**Blocked by:** 09 (Market structure and wave cycles)

**Status:** resolved

- [x] Each 3-SMA rule is its own Block or parameter, switchable
- [x] Choppy Regime disables breakout orders until separation resumes
- [x] Candle Setup geometry and SMA 7 placement rules match the blueprint defaults
- [x] Second Wave detection uses confirmed structure from ticket 09
- [x] RSI and volume conditions are Confirmation Blocks attached by default (the UI sample document attaches them; the Template, ticket 12, will too)
- [x] Fixtures where each rule makes the setup fire and not fire (every Block rule has a fire/not-fire fixture; the harness-level ones are the Second Wave, Choppy Regime, 99 SMA filter, overextension guard, SMA slope gate, crossover and the SMA 25 exit, the rest are on Block output)

Spec: `.scratch/tcp-strategy-builder/spec.md`
