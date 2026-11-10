# 16: MACD, ROC and ADX/DMI

**What to build:** Blocks for MACD (ignore crossovers near zero, histogram deceleration as a profit-taking warning), ROC/MOM (4H ROC at its 200-bar ceiling disables 15m longs and takes profit; ROC box-breakout confirmation), and ADX/DMI (separated DI with rising ADX allows stop orders, tangled DI requires a body close; ADX above 45-50 and curling down tightens stops and takes profit).

**Blocked by:** 12 (TCP Azizpour Template (core))

**Status:** resolved

- [x] Each rule is a switchable Block with blueprint defaults
- [x] The ADX order-type switch changes the Execution behaviour of the same candidate
- [x] Fixtures per rule; Template updated

Spec: `.scratch/tcp-strategy-builder/spec.md`

## Resolution

`strategy/momentum.py` (`macd_cross`, `roc_ceiling`, `roc_box_breakout`), `adx_order_type` in `library` with `OrderSpec.market` in the engine, `profit_chain` options `macd_decel_exit`, `roc_ceiling_exit`, `adx_exhaustion`, Template rows (disabled), ADR 10 §20. Notes: DI/ROC/MACD numbers are my defaults (the blueprint gives none); the tangled-DI "body close" is a market entry once a close is beyond the invalidation level; MF scaling of MACD/SMA is not built.
