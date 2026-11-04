# 01: Intraday base bars and multi-timeframe views

**What to build:** A user can load 15-minute bars (Nobitex and ccxt feeds, CSV import) and the data layer builds 1H, 4H, daily and weekly bars from that one base. Any consumer reading a higher timeframe from a lower-timeframe bar sees only higher bars that have already closed. Existing daily NNFX runs are unchanged.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] 15m base bars can be fetched (Nobitex resolution 15, ccxt 15m) and cached like H1 today
- [ ] 1H/4H/D/W views are resampled from the 15m base with the same close-time labelling contract as the daily bars
- [ ] A lower-timeframe bar can query the latest closed higher-timeframe bar; a test proves an unclosed 4H bar is never visible from a 15m bar inside it
- [ ] The data integrity gates run on 15m input
- [ ] The committed NNFX reference run still reproduces (`nnfx determinism` OK)

Spec: `.scratch/tcp-strategy-builder/spec.md`
