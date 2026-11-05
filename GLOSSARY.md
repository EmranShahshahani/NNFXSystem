# Glossary

Domain language for the NNFX platform and the Strategy Builder. Use these terms in
specs, tickets, tests and code. Source for Trade City Pro (TCP) terms:
`docs/sources/tcp-blueprint/`.

## Platform

- **Engine**: a pure function that turns history, open positions, account state, config and engine state into a Decision. No I/O, no clock.
- **Harness**: the loop that feeds an Engine and executes its Decision against a Broker. One harness serves backtest, paper and live.
- **Broker**: executes intents. BacktestBroker (simulated), PaperBroker (simulated, persistent), live adapters (not built).
- **Trial**: one evaluated configuration on one data segment; counted in the research log.
- **Holdout**: the data segment opened once, ever, per market.
- **Base Timeframe**: the one intraday timeframe a feed delivers (M15 or H1); every higher timeframe is resampled from it.
- **Timeframe View**: a higher-timeframe frame (H1, H4, D1, W1) built from the Base Timeframe. A bar reads a view only "as of" its own close, so it sees only higher bars already closed.
- **Pre-registration**: a frozen file fixing a hypothesis and its trial budget before results are seen.

## Strategy Builder

- **Strategy Document**: a user's strategy as data: an ordered set of Blocks with parameters, timeframes and risk rules. Versioned and content-hashed. Never code.
- **Fingerprint**: the content hash of a resolved Strategy Document; every result and Trial of the document carries it.
- **Strategy Engine**: the one engine that interprets any Strategy Document (`DocumentEngine`), on the shared harness.
- **Block**: one configurable rule from the Block Library, of one Block Kind. Every number in a Block is a parameter with a default.
- **Block Kind**: Context, Setup, Confirmation, Execution, Stop, Exit, Risk, Market Filter.
- **Template**: a read-only Strategy Document users clone and customise. "TCP Azizpour" is the first.
- **Setup Candidate**: what a Setup Block emits when its pattern completes: direction, trigger price, invalidation price, proposed stop, tags.
- **Confluence Score**: the summed weight of a Setup Candidate's passing Confirmation checks (each weighs 1 by default, so usually their count); it selects the Risk Tier. Not-applicable checks never count.
- **Decision Path**: a candidate's way through context → confirmations → risk → stop → order, with the first refusal and the stages it skipped.
- **Justified / Unjustified Stop**: a loss on a setup that passed every applicable check, versus one placed although a soft check failed (a rule break to review).
- **Pre-Trade Checklist**: the ordered list of Confirmation and Context checks a Setup Candidate must pass; any hard-fail aborts it.

## Trade City Pro terms

- **HWC / MWC / LWC**: High, Medium and Low Wave Cycle: macro trend timeframe (weekly/daily), structure timeframe (daily/4H), execution timeframe (15m).
- **Second Wave**: the continuation impulse after the first breakout leg; the preferred place for setups.
- **Candle Setup**: TCP's flagship 15m entry candle: long rejection wick, small opposite wick, 7 SMA behind the wick and never through the body.
- **Trigger**: a pending stop-market order just beyond a level (setup high/low or box edge). Price must come to it.
- **Invalidation**: the price at which the setup's thesis is dead; a close beyond it cancels a pending Trigger and anchors the stop.
- **Box**: a horizontal consolidation range with counted touches on its edges.
- **Touch**: a test of a level that does not close beyond it. 1st touch: no breakout trade; 3rd–4th: preferred.
- **3-SMA System**: SMA 7 (momentum, setup anchor), SMA 25 (structure, holding), SMA 99 (macro baseline, "black hole").
- **Choppy Regime** ("bazar-e chert"): SMAs flat and entangled; breakout orders disabled.
- **Profit Chain** ("zanjire-ye sood"): the partial take-profit ladder (default 35% at 2R, 40% at 5R, 15% at 10R, 10% runner).
- **Runner**: the last fraction of a position, trailed behind higher-timeframe swings.
- **Management timeframe**: the timeframe role whose closes drive position management (conditional breakeven, the Runner trail); the MWC unless the document sets `timeframes.management`.
- **Conditional breakeven**: once the first Profit Chain step has filled, the stop moves to entry only when a new swing has been confirmed on the management timeframe since the entry.
- **Swing (pivot)**: a bar whose low (high) is strictly below (above) the `pivot_bars` bars on each side; it is confirmed, and readable, only `pivot_bars` bars later.
- **Counter-trend mode**: a Profit Chain mode with no Runner: the whole position closes at 2R, or at the first structural boundary between 2R and `counter_trend_max_r`.
- **Spot recycling record**: the Capital Recycling rule as a ledger: when a whole position closes at `recycle_min_r` R or more, its net profit is recorded as moved from futures to spot. Sizing is unchanged; the equity curve is split into trading and spot.
- **Exit Plan**: a position's exit steps, each closing a fraction of the original size at an R multiple, plus the Runner fraction; together they sum to 1. The Profit Chain is one Exit Plan.
- **R**: the planned stop distance (planned entry to stop). Exit steps and results are measured in R.
- **Risk Tier**: risk per trade chosen by confluence: 0.25%, 0.50%, 0.75%, 1.0%.
- **Streak Governor**: rules that cut risk or halt trading after consecutive losses.
- **Leverage Governor**: caps leverage so liquidation sits beyond the stop with a safety margin (max leverage < 1 / (stop% × 1.5)).
- **Loss Limits**: realised losses for the day (default 1.5%) or week, measured against that period's starting balance, halt new entries (24 h, or until Monday).
- **Performance Governor**: a rolling win rate below 40% over 50 trades, or a drawdown beyond 6% (until a new equity high), cuts risk to 0.25%.
- **Equity Milestone**: risk is sized on equity that moves only in ±10% steps from the initial equity.
- **Dominance Regime**: BTC-led, Altseason, or Altcoin Flush, from BTC/USDT trend and BTC.D trend.
- **Relative-Strength Sieve**: altcoin selection by ALT/BTC trend (and ALT/ETH or ETH/BTC).
- **MF (Multiplier Factor)**: higher-timeframe minutes ÷ chart minutes; scales an indicator period to mirror a higher timeframe.
- **Order Book Source**: provider of order-book snapshots (live exchange, recorded, or fixture).
- **Wall**: a resting limit-order cluster, large relative to the book's own depth, that persists across snapshots. It ends **consumed** (price traded through it), as a **Spoof** (it vanished or stepped back while price approached) or **faded** (pulled while price moved away). A level that spoofed is **suspect** for a while.
- **Depth to move**: the size a market order must take to push price x% from the best level.
