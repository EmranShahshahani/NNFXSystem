# 20: Dominance, ALT/BTC and screener

**What to build:** Market Filter Blocks: dominance series import (BTC.D, USDT.D, TOTAL2/3), the Dominance Regime (BTC-led, Altseason, Altcoin Flush) deciding BTC vs altcoins and direction, the Relative-Strength Sieve (ALT/BTC trend, optional ALT/ETH or ETH/BTC; cross pairs derived when missing), and a daily screener (24h volume >= 1,000 BTC, positive 24h and 7d vs BTC) producing a watchlist of at most 3-5 assets.

**Blocked by:** 09 (Market structure and wave cycles), 12 (TCP Azizpour Template (core))

**Status:** ready-for-agent

- [ ] Missing dominance data makes the Block not-applicable and flags the run incomplete
- [ ] Regime matrix matches the blueprint table
- [ ] Screener runs from exchange ticker data and is tested offline
- [ ] Fixtures per rule; Template updated

Spec: `.scratch/tcp-strategy-builder/spec.md`
