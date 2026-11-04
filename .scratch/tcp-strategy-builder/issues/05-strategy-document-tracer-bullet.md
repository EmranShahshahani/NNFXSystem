# 05: Strategy Document tracer bullet

**What to build:** A user can write a minimal Strategy Document (one Context Block: 3-SMA alignment; one Setup Block: a basic Candle Setup; a stop-market Execution Block; a structural Stop Block; a single 2R exit; fixed risk), validate it, and backtest it from the CLI, the API and a minimal UI form. This establishes the schema, the Block registry, the Strategy Engine, validation messages, fingerprints, trial logging and ADR 10.

**Blocked by:** 01 (Intraday base bars and multi-timeframe views), 02 (Pending stop-market orders), 03 (Fractional exit steps)

**Status:** ready-for-agent

- [ ] Strategy Document schema: metadata, timeframe roles, ordered Blocks `{kind, type, enabled, params}`, risk section; unknown types/params are validation errors with Persian messages
- [ ] Each document version has a stable content-hash fingerprint
- [ ] Block registry with typed contracts per Block Kind; the gate suite (no-lookahead, determinism, price-scale invariance) iterates every registered Block automatically
- [ ] The Strategy Engine interprets a document through the pure decide() contract and journals one record per Setup Candidate
- [ ] `nnfx` CLI, an API endpoint and a minimal UI form run a backtest of a document; each run records a Trial with the fingerprint
- [ ] A harness-level test: hand-built 15m bars produce exactly the expected stop order, fill, stop and 2R exit
- [ ] ADR 10 (Strategy Documents and the Block Library) written

Spec: `.scratch/tcp-strategy-builder/spec.md`
