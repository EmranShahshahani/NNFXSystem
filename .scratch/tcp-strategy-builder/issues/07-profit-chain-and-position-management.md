# 07: Profit Chain and position management

**What to build:** Strategy Documents get the Profit Chain and position-management Blocks: a configurable ladder (default 35% at 2R, 40% at 5R, 15% at 10R, 10% Runner), no full close below 2R, breakeven at 2R only if a new structural pivot has formed, Runner trailing behind higher-timeframe swings, management on a chosen timeframe (default 4H closes), counter-trend mode, and the futures-to-spot recycling record.

**Blocked by:** 05 (Strategy Document tracer bullet)

**Status:** ready-for-agent

- [ ] Ladder steps and Runner fraction are parameters; the 10R step offers 15% (default) or 20%
- [ ] No exit rule may close the whole position below 2R
- [ ] Conditional breakeven moves the stop only when a new confirmed pivot exists after entry
- [ ] The Runner trails behind confirmed swing points of the management timeframe
- [ ] Counter-trend mode disables the Runner and closes 100% at 2R or the first structural boundary
- [ ] Optional recycling record moves realised profit to a spot ledger on +5R..10R closes
- [ ] Harness-level tests reproduce a full ladder-out and a trailing exit

Spec: `.scratch/tcp-strategy-builder/spec.md`
