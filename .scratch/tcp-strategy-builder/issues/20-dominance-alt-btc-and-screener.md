# 20: Dominance, ALT/BTC and screener

**What to build:** Market Filter Blocks: dominance series import (BTC.D, USDT.D, TOTAL2/3), the Dominance Regime (BTC-led, Altseason, Altcoin Flush) deciding BTC vs altcoins and direction, the Relative-Strength Sieve (ALT/BTC trend, optional ALT/ETH or ETH/BTC; cross pairs derived when missing), and a daily screener (24h volume >= 1,000 BTC, positive 24h and 7d vs BTC) producing a watchlist of at most 3-5 assets.

**Blocked by:** 09 (Market structure and wave cycles), 12 (TCP Azizpour Template (core))

**Status:** resolved

- [x] Missing dominance data makes the Block not-applicable and flags the run incomplete
- [x] Regime matrix matches the blueprint table
- [x] Screener runs from exchange ticker data and is tested offline
- [x] Fixtures per rule; Template updated

Spec: `.scratch/tcp-strategy-builder/spec.md`

## Resolution

`strategy/market.py` (`MarketData`, `read_market_series`, ratios derived from two pairs when the cross pair is missing, causal and staleness-aware trend), `strategy/dominance.py` (`dominance_regime`: BTC-led / Altseason / Altcoin Flush matrix; `relative_strength`: ALT/BTC sieve with optional ALT/ETH or ETH/BTC), the `market_filter` Block kind with `ContextOutput.available`, `DocumentRun.incomplete` (and the UI notice), `strategy/screener.py` (`screen`, `stats_from_exchange`; offline tests with a fake exchange), Template rows (disabled), ADR 10 §24. Notes: combinations outside the blueprint table restrict nothing; the UI cannot yet upload market series; the screener has no CLI/UI entry yet.
