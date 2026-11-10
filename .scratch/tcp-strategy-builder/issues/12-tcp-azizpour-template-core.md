# 12: TCP Azizpour Template (core)

**What to build:** A read-only 'TCP Azizpour' Template encoding the blueprint defaults from the Blocks built so far, each Block citing its source video(s). Users can clone it into their own document. From this ticket on, every new Block ticket also adds its Block to the Template, enabled or disabled as the blueprint says.

**Blocked by:** 06 (Risk governor), 07 (Profit Chain and position management), 08 (Pre-Trade Checklist and candidate journal), 10 (3-SMA system and full Candle Setup), 11 (Levels, touches, boxes and breakout confirmation)

**Status:** resolved

- [x] Template is listed, read-only, and clonable via CLI, API and UI
- [x] Timeframe roles: HWC weekly/daily, MWC 4H/daily, LWC 15m; management on 4H closes
- [x] Each Block records its source video number(s)
- [x] End-to-end scenario tests: a Candle Setup long that fills, ladders out and trails; a setup cancelled by an invalidation close; a first-touch breakout refused; a Choppy regime with no orders; a losing streak that drops risk and then halts
- [x] Template backtests are trials of a separate hypothesis family; no pre-registration is changed

Spec: `.scratch/tcp-strategy-builder/spec.md`

## Resolution

`strategy/templates.py`; ADR 10 §16. Notes: the HWC is `D1` (weekly is a parameter change); Confirmations got `only_setups` so the candle and box checks do not judge each other's setups; the first-touch scenario lowers `box_breakout.min_touches` because, as shipped, a box needs three touches before the touch-count rule can refuse a first touch.
