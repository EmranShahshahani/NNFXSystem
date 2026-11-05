# 07: Profit Chain and position management

**What to build:** Strategy Documents get the Profit Chain and position-management Blocks: a configurable ladder (default 35% at 2R, 40% at 5R, 15% at 10R, 10% Runner), no full close below 2R, breakeven at 2R only if a new structural pivot has formed, Runner trailing behind higher-timeframe swings, management on a chosen timeframe (default 4H closes), counter-trend mode, and the futures-to-spot recycling record.

**Blocked by:** 05 (Strategy Document tracer bullet)

**Status:** resolved

- [x] Ladder steps and Runner fraction are parameters; the 10R step offers 15% (default) or 20%
- [x] No exit rule may close the whole position below 2R
- [x] Conditional breakeven moves the stop only when a new confirmed pivot exists after entry
- [x] The Runner trails behind confirmed swing points of the management timeframe
- [x] Counter-trend mode disables the Runner and closes 100% at 2R or the first structural boundary
- [x] Optional recycling record moves realised profit to a spot ledger on +5R..10R closes
- [x] Harness-level tests reproduce a full ladder-out and a trailing exit

Spec: `.scratch/tcp-strategy-builder/spec.md`
