# 12: TCP Azizpour Template (core)

**What to build:** A read-only 'TCP Azizpour' Template encoding the blueprint defaults from the Blocks built so far, each Block citing its source video(s). Users can clone it into their own document. From this ticket on, every new Block ticket also adds its Block to the Template, enabled or disabled as the blueprint says.

**Blocked by:** 06 (Risk governor), 07 (Profit Chain and position management), 08 (Pre-Trade Checklist and candidate journal), 10 (3-SMA system and full Candle Setup), 11 (Levels, touches, boxes and breakout confirmation)

**Status:** ready-for-agent

- [ ] Template is listed, read-only, and clonable via CLI, API and UI
- [ ] Timeframe roles: HWC weekly/daily, MWC 4H/daily, LWC 15m; management on 4H closes
- [ ] Each Block records its source video number(s)
- [ ] End-to-end scenario tests: a Candle Setup long that fills, ladders out and trails; a setup cancelled by an invalidation close; a first-touch breakout refused; a Choppy regime with no orders; a losing streak that drops risk and then halts
- [ ] Template backtests are trials of a separate hypothesis family; no pre-registration is changed

Spec: `.scratch/tcp-strategy-builder/spec.md`
