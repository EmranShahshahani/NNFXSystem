# 02: Pending stop-market orders

**What to build:** An engine can ask for a pending stop-market order instead of a market entry: trigger price plus buffer, expiry in bars, cancel when a candle closes beyond an invalidation price, and optional OCO pairing. The backtest broker and the paper broker fill these the same way, following ADR 09.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Engines can emit a pending-order intent and a cancel intent; existing market-entry engines are unaffected
- [ ] A long stop fills at max(trigger, open) when the bar trades through it; a gap through the trigger fills at the open
- [ ] If a stop-loss and a target are both inside one bar, the stop is assumed hit first
- [ ] A pending order is cancelled when a bar closes beyond its invalidation price before it fills, and when it expires
- [ ] In an OCO pair, the first fill cancels the other
- [ ] Every placement, fill, cancellation and expiry is journaled; the parity test shows backtest and paper produce identical events

Spec: `.scratch/tcp-strategy-builder/spec.md`
