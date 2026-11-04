# 16: MACD, ROC and ADX/DMI

**What to build:** Blocks for MACD (ignore crossovers near zero, histogram deceleration as a profit-taking warning), ROC/MOM (4H ROC at its 200-bar ceiling disables 15m longs and takes profit; ROC box-breakout confirmation), and ADX/DMI (separated DI with rising ADX allows stop orders, tangled DI requires a body close; ADX above 45-50 and curling down tightens stops and takes profit).

**Blocked by:** 12 (TCP Azizpour Template (core))

**Status:** ready-for-agent

- [ ] Each rule is a switchable Block with blueprint defaults
- [ ] The ADX order-type switch changes the Execution behaviour of the same candidate
- [ ] Fixtures per rule; Template updated

Spec: `.scratch/tcp-strategy-builder/spec.md`
