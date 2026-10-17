# Trade City Pro (ترید سیتی پرو) — Named Strategies, Setups and Rules

Research method note: WebFetch and curl could not reach any target host from this environment. tradingview.com, outlierkit.com and leemeenal.app all failed with DNS ENOTFOUND or a proxy 403 on CONNECT. So **every finding below comes from search-engine snippets and titles** of TradingView ideas, YouTube titles, leemeenal.app (Trade City Pro's video hub, "لیمینال") and the Telegram index. None of it comes from reading full pages or watching videos. Quotes are snippet text, which a summarizing search layer may have paraphrased. Labels used: **[Q]** = quoted or near-quoted from a TCP-authored snippet; **[T]** = inferred from a title only; **[I]** = my inference.

## 1. Named strategies/setups and their mechanical rules (context, trigger, SL, TP, invalidation, timeframes)

### Takeaway
TCP's method is a discretionary price-action "trigger" system. The trader marks a range/box or key S/R levels by eye, often on 1h for BTC daily analysis. The "trigger" (تریگر) is a stop-order breakout of a level: stop-buy above resistance, stop-sell below support. It is confirmed by rising volume, RSI momentum (RSI 50 and 70/30 levels) and a setup candle (کندل ستاپ). Fake breakouts back into the range (ستاپ فیک) are traded as reversal setups. Dow-theory structure (HH/HL) gives context. When the price triggers have already fired, a secondary set of "momentum triggers" (RSI breakouts, SMA7/25/99 pullbacks) is used. Publicly indexed sources do not give the exact parameters for each part of the "استراتژی ترید ارشیا عزیزپور" series.

### Cited Findings
**The "استراتژی ترید ارشیا عزیزپور" (Arshia Azizpour trading strategy) series**
- [T] YouTube parts exist with these titles: "استراتژی ترید ارشیاعزیز پور پارت 1" — [YT Part 1](https://www.youtube.com/watch?v=5RtgblzXQ7E); Part 2 (short) — [YT Part 2](https://www.youtube.com/shorts/arrZBYX0gpc); Part 4 — [YT Part 4](https://www.youtube.com/watch?v=O5CAWmov9K8); "آموزش تحلیل‌ تکنیکال : استراتژی ترید ارشیاعزیز پور پارت 6" — [YT Part 6](https://www.youtube.com/watch?v=fHr00Y01K5s). There is also a live-class version, "لایو آموزشی ارزدیجیتال : پارت 1 استراتژی ترید ارشیاعزیزپور" — [YT live Part 1](https://www.youtube.com/watch?v=3qKc3jOqxjg).
- [T] Part 2 is listed on leemeenal as "Arshia Azizpour trading strategy Part 2 | Dow Theory (تئوری داو)", which suggests Part 2 covers Dow-theory structure — [leemeenal long-video list p4](https://leemeenal.app/videos/trade-city-pro/long-video/page/4/).
- [T] According to the search summary, titles in the series cover trading volume (حجم معاملات), momentum indicators (اندیکاتورهای مومنتومی) and market structure. One title reads "هر چی از ساختار بازار می‌شناسی بنداز دور" ("throw away everything you know about market structure"). The summary implies parts up to roughly 7 — [search context, YT Part 6](https://www.youtube.com/watch?v=fHr00Y01K5s); [outlierkit channel page (not fetchable)](https://outlierkit.com/channel/tradecitypro).
- Related shorts: "بهترین روش رسم حمایت و مقاومت" (best way to draw S/R) — [YT short](https://www.youtube.com/shorts/uxScNYVTZC4); "دقایقی با ارشیا عزیزپور" (psychology/discipline series) — [YT](https://www.youtube.com/watch?v=cMa9IqiUid8), [YT short](https://www.youtube.com/shorts/d2fWXd0bleY).

**Trigger (تریگر) = level-break entry via stop order**
- [Q] BTC Daily Analysis #114 (1h chart): after a strong up-move, BTC formed a range between ~108,617 and 110,256. "110,256" is named as the **long trigger**, and a higher low above 108,617 "would raise the odds of a breakout." "If this trigger is activated, it's crucial that volume rises as well." The post is aimed at the New York session — [TradingView: TCP BTC Daily Analysis 114](https://tw.tradingview.com/chart/BTCUSDT/SC0AeFnh-TradeCityPro-Bitcoin-Daily-Analysis-114).
- [Q] Older TCP idea: short "if price breaks below 59,270", next support 54,368. TCP adds that its triggers may not suit inexperienced traders and are personal opinion — [TradingView BTCUSDT ideas p2](https://www.tradingview.com/symbols/BTCUSDT/ideas/page-2/?sort=recent).
- [Q] BTC idea: a break below 81,464 "could start a move lower", target 75,471. Listed TP 83,741 (+1.9%) and SL 80,125 (-2.5%), "or an earlier exit on an opposite-side signal" — [TradingView BTCUSDT ideas p2](https://www.tradingview.com/symbols/BTCUSDT/ideas/page-2/?sort=recent). (Snippet summary; the long/short direction of those TP/SL numbers is unclear.)
- [T/Q] leemeenal has a video titled "آموزش استاپ بای و استاپ سل؛ چطور از حرکت‌های شارپ بازار جا نمونیم؟" (stop-buy/stop-sell: how not to miss sharp moves). Per the snippet it also covers where to place stop-losses, and it stresses volume and momentum — [leemeenal stop-buy guide](https://leemeenal.app/video/stop-buy-stop-sell-trading-guide/).
- [Q] "A breakout above resistance can serve as a long trigger, and a rise in volume plus a candle setup can strengthen the move" — [leemeenal altcoins while BTC ranges](https://leemeenal.app/video/altcoin-analysis-bitcoin-range/). Another video: "تحلیل بیت کوین امروز؛ تریگر لانگ و شورت و فرصت‌های آلت‌کوین" — [leemeenal long/short triggers](https://leemeenal.app/video/bitcoin-analysis-long-short-altcoins/).

**Candle setup (کندل ستاپ) and why not to "memorize" it**
- [Q/T] Video "تحلیل بیت کوین امروز؛ چرا نباید کندل ستاپ را حفظ کنیم؟" (why you shouldn't memorize the candle setup). Its point: a candle that looks like a setup is not automatically an entry trigger; momentum and market structure must be read too — [leemeenal candle-setup](https://leemeenal.app/video/bitcoin-analysis-candle-setup/).
- [Q] "Breaking resistance or seeing a setup candle alone is not enough for entry; volume and the speed (شتاب) of the move matter" — [leemeenal momentum video](https://leemeenal.app/video/bitcoin-analysis-momentum/).
- [Q] Wait for "a pullback, volume confirmation, and a candle setup" before acting — [leemeenal what-to-do-with-dollar](https://leemeenal.app/video/what-to-do-with-dollar/).

**Fake setup (ستاپ فیک) / fakeout**
- [T/Q] One leemeenal video reviews an OP trade and how "ستاپ فیک" (fake setup) created an entry opportunity. Another BTC video covers "important zones, fake setup and position management" — [leemeenal momentum video](https://leemeenal.app/video/bitcoin-analysis-momentum/); [leemeenal TCP hub](https://leemeenal.app/trade-city-pro/).
- [Q] TCP Daily Analysis #369 describes confirmation as a "candle close back inside the range, plus volume or momentum shift" — [TradingView BTCUSDT ideas](https://www.tradingview.com/symbols/BTCUSDT/ideas/). This is the closest mechanical definition of a fake-breakout confirmation found.
- [Q] TCP USD/CAD idea titled roughly "USDCAD, Breakout or fake fakeout?" (about 2 years old) cites Dow theory, the absence of divergence and a trendline test as factors — [TradingView USDCAD ideas](https://www.tradingview.com/symbols/USDCAD.10.CFD/ideas/).
- [Q] ONE idea: "after the trendline break, a double top and a fakeout in November" — [TradingView ONEUSDT ideas p4](https://www.tradingview.com/symbols/ONEUSDT/ideas/page-4/).

**Range/box trading (رنج / محدوده)**
- [T] YouTube: "تکنیک های ترید در رنج های بازار ، بعد از صدها معامله این هارو فهمیدم" (range-trading techniques learned after hundreds of trades). The snippet treats a range as a rectangle pattern — [YT range techniques](https://www.youtube.com/watch?v=0m2ODWrHWq0).
- [Q] Daily Analysis #379: "Bitcoin is still trading within the 81,646–87,016 range, and trading volume is decreasing" — [TradingView BTCUSDT ideas](https://www.tradingview.com/symbols/BTCUSDT/ideas/).
- [Q] SOL idea "TradeCityPro SOL Holds PRZ as Bulls Eye Range Breakout" gives a range-breakout entry and a stop rule: "if you have already bought SOL, you can set your stop-loss if the price closes below this area" — [TradingView SOL PRZ](https://my.tradingview.com/chart/SOLUSDT/6gRQOtEz-TradeCityPro-SOL-Holds-PRZ-as-Bulls-Eye-Range-Breakout).
- [T] A leemeenal/TCP video covers why breaking a long range can produce a sharp move — [search summary, leemeenal hub](https://leemeenal.app/trade-city-pro/).

**Momentum triggers (secondary entries when price triggers are already gone)**
- [Q] "the main triggers had already been activated, and it might be too late to enter a position. However, you could still enter trades using momentum triggers such as RSI and SMA." In the same post, "the RSI dropped below level 50, so the RSI trigger had not yet fired." Also: "The SMA99 is getting closer to the price… If this happens and the price builds a structure after the pullback, it could offer a good long entry" — [TradingView TCP BTC Daily 71](https://my.tradingview.com/chart/BTCUSDT/sGZUIBfO-TradeCityPro-Bitcoin-Daily-Analysis-71) / [Daily 185](https://my.tradingview.com/chart/BTCUSDT/K5yQYNTo-TradeCityPro-Bitcoin-Daily-Analysis-185). (The snippet cited these posts together, so attribution to exactly one of them is uncertain.)
- [Q] "All the primary price-based triggers have already been activated, so if you're not already in a position, you'll need to rely on momentum indicators." Options given: a breakout above an RSI-based level, or a pullback to SMA25 followed by a confirmation candle. Another post: price "pulling back multiple times to SMA7 and moving again with confirmation candles", and the same approach "can work with SMA25 or SMA99" — [TCP BTC Daily 98](https://my.tradingview.com/chart/BTCUSDT/H1dYFSUV-TradeCityPro-Bitcoin-Daily-Analysis-98); [Daily 54](https://my.tradingview.com/chart/BTCUSDT/d5cg3dP9-TradeCityPro-Bitcoin-Daily-Analysis-54); [Daily 70](https://my.tradingview.com/chart/BTCUSDT/JZ5ZyQjf-TradeCityPro-Bitcoin-Daily-Analysis-70).
- [Q] ARB idea: pullback to a trendline with RSI bouncing from 50; "If today's candle can hold above the SMA25, the price can move toward 0.6164" (daily) — [TradingView ARBUSDT ideas](https://www.tradingview.com/symbols/ARBUSDT/ideas/?sort=recent&video=yes).

**Dow theory (داو, سقف و کف)**
- [Q] The "TradeCityPro Academy: Dow Theory" Parts 1–3 on TradingView cover the six principles. Part 2: averages must confirm each other. Part 3: volume, where a rally on thin volume "may be a fluke or manipulation" — [Dow Part 1](https://www.tradingview.com/chart/BTCUSDT/SgGwaMbT-TradeCityPro-Academy-Dow-Theory-Part-1/); [Dow Part 2](https://www.tradingview.com/chart/BTCUSDT/ZGIOpRoI-TradeCityPro-Academy-Dow-Theory-Part-2/); [Dow Part 3](https://www.tradingview.com/chart/BTCUSDT/t8byOg6O-TradeCityPro-Academy-Dow-Theory-Part-3/).
- [Q] Daily #114 uses a "higher low above 108,617" as a breakout-probability booster, which applies Dow HL logic to trigger quality — [Daily 114](https://tw.tradingview.com/chart/BTCUSDT/SC0AeFnh-TradeCityPro-Bitcoin-Daily-Analysis-114).

**Support/resistance**
- [T] "TradeCityPro Academy: Support & Resistance Part 1/2", which the search summary says draws on the book *The Handbook of Technical Analysis* plus TCP's own experience — [S/R Part 1](https://www.tradingview.com/chart/BTCUSDT/KDFKCuwt-TradeCityPro-Academy-Support-Resistance-Part-1/); [S/R Part 2](https://www.tradingview.com/chart/BTCUSDT/SDlsvQbA-TradeCityPro-Academy-Support-Resistance-Part-2/).

**Risk/money management**
- [Q] Risk Management lesson: start at **0.5% risk per trade** and keep a trading journal — [TCP Academy Risk Management](https://www.tradingview.com/chart/BTCUSDT/zApQnqon-TradeCityPro-Academy-Risk-Management/).
- [Q] Money Management lesson: a futures position-sizing example with a $1,000 account, 0.5% risk and 10x leverage — [TCP Academy Money Management](https://www.tradingview.com/chart/BTCUSD/ANXXXHiL-TradeCityPro-Academy-Money-Management/). Companion script: "TCP Money Management indicator (Crypto Version)" — [TV script](https://www.tradingview.com/script/zSsk5nXf-TCP-Money-Management-indicator-Crypto-Version/).

### Inferences
- [I] A mechanical reading of the core "trigger" setup, assembled from the snippets:
  1. Context: mark a range/box or the recent swing high and low on the working timeframe (often 1h for BTC). Dow structure (HH/HL vs LH/LL) gives the bias.
  2. Trigger: a stop-buy above the range high or resistance (long), or a stop-sell below the range low or support (short).
  3. Confirmation: rising volume on the breakout, RSI pushing through 50 (or into 70+ for longs or below 30 for shorts), and a strong setup candle.
  4. SL: the most explicit rule is "close below the area" (the broken level or range). The opposite side of the range or the last swing is also plausible.
  5. TP: the next S/R level, or "early exit on opposite signal".
  6. Invalidation: candle close back inside the range with volume or momentum shift, which is the fake-setup condition and can itself be traded in the opposite direction.
- [I] Fake setup (ستاپ فیک) most likely means: price breaks out of the box, then a candle closes back inside the range together with a volume or momentum shift. The trader then enters toward the other side of the range or in the original direction. Exact entry and SL rules are unverified.
- [I] Every part depends on levels chosen by eye ("important zone", ناحیه مهم), so the system is discretionary at its core. Trigger levels are only mechanical after the box is drawn.

### Gaps
- The content of each "استراتژی ترید ارشیا عزیزپور" part (1–7) could not be read. Only titles are known (Part 2 = Dow theory). No transcripts were reachable.
- No exact definition was found for "ستاپ فیک" entry, stop or target. No exact TP rule (R-multiple vs next level) was found either.
- Scalping vs swing variants: none were found as named setups.

## 2. Indicators and settings, and how they are used

### Takeaway
Confirmed indicators are RSI (key levels 50 and 70/30 "overbuy/oversell"), volume (rising volume required on triggers), and SMAs 7, 25 and 99 (the Binance default MA set) used as pullback and dynamic-support levels. RSI is used both as a filter/confirmation and as a "momentum trigger" (RSI breaking a level). No evidence was found that TCP uses Stoch RSI or MACD. The RSI period is not stated in any snippet.

### Cited Findings
- [Q] RSI 50 as a trigger line: "the RSI dropped below level 50, so the RSI trigger had not yet fired" — [Daily 71](https://my.tradingview.com/chart/BTCUSDT/sGZUIBfO-TradeCityPro-Bitcoin-Daily-Analysis-71).
- [Q] RSI 70 "Overbuy" zone: "RSI has exited the Overbuy zone and is now cooling off… bullish momentum has weakened" — [Daily 114](https://tw.tradingview.com/chart/BTCUSDT/SC0AeFnh-TradeCityPro-Bitcoin-Daily-Analysis-114). On the 1-hour chart, "buying volume has increased significantly, while RSI has also established above 70 and entered the overbought zone" — [TradingView BTCUSDT ideas](https://www.tradingview.com/symbols/BTCUSDT/ideas/). This suggests TCP treats RSI above 70 as momentum confirmation rather than as a sell signal [I].
- [Q] RSI oversold on 1h as a possible upward-breakout cue (Daily #368) — [TradingView BTCUSDT POLONIEX ideas p13](https://www.tradingview.com/symbols/BTCUSDT/ideas/page-13/?exchange=POLONIEX).
- [Q] RSI break below 50 "would strengthen the corrective scenario"; SMA99 and the Fib 0.382 level are support targets (XLM) — [TradingView XLMUSDT ideas p3](https://www.tradingview.com/symbols/XLMUSDT/ideas/page-3/?exchange=BITRUE).
- [Q] SMA7, SMA25 and SMA99 are used as pullback levels with confirmation candles — [Daily 98](https://my.tradingview.com/chart/BTCUSDT/H1dYFSUV-TradeCityPro-Bitcoin-Daily-Analysis-98); [Daily 54](https://my.tradingview.com/chart/BTCUSDT/d5cg3dP9-TradeCityPro-Bitcoin-Daily-Analysis-54).
- [Q] Volume must rise when a trigger activates — [Daily 114](https://tw.tradingview.com/chart/BTCUSDT/SC0AeFnh-TradeCityPro-Bitcoin-Daily-Analysis-114). Falling volume inside a range is noted — [BTCUSDT ideas](https://www.tradingview.com/symbols/BTCUSDT/ideas/).
- [Q] Divergence is used as a factor; "lack of divergence" counted as bullish in the USDCAD idea — [USDCAD ideas](https://www.tradingview.com/symbols/USDCAD.10.CFD/ideas/).
- [Q] Bitcoin dominance (BTC.D) acts as a filter for altcoins: altcoin buys should wait until BTC dominance starts to drop — [search summary of TCP posts, Daily 70](https://my.tradingview.com/chart/BTCUSDT/JZ5ZyQjf-TradeCityPro-Bitcoin-Daily-Analysis-70).
- [Q] Correlation analysis appears in Daily #368: SOL vs BTC returns over 90 bars correlate at 0.885, and ETH at 0.797/0.844 — [BTCUSDT POLONIEX ideas p13](https://www.tradingview.com/symbols/BTCUSDT/ideas/page-13/?exchange=POLONIEX).
- [Q] TCP's own TradingView scripts are the "TCP Market Session Indicator / Session Analyzer" (draws Asia, Europe and US session ranges) and the "TCP Money Management indicator" — [TCP scripts list](https://in.tradingview.com/scripts/tradecitypro/); [TCP Market Session](https://www.tradingview.com/script/Xzep6F2j-TCP-Market-Session-Session-Analyzer/).

### Inferences
- [I] SMA 7/25/99 are Binance's default MA lengths, which suggests TCP charts on Binance defaults. RSI is probably the default 14, but that is unverified.
- [I] Indicator roles: RSI 50 = momentum filter or trigger; RSI 70/30 = momentum confirmation, or a "cooling off" warning on exit from the zone; volume = mandatory breakout confirmation; SMAs = dynamic pullback entries; divergence = secondary context.

### Gaps
- No snippet states the RSI period, a volume MA length, or whether "rising volume" means above a volume MA. There was no evidence on Stoch RSI or MACD use, so absence cannot be confirmed either.

## 3. Markets, timeframes, and rule-based vs discretionary

### Takeaway
The focus is crypto: Bitcoin daily analysis (numbered 1 to 380+), altcoins (SOL, ARB, XLM, OP, ONE) and BTC dominance. There is occasional forex (USDCAD) and dollar commentary. BTC daily analyses work on the 1h chart with session timing (NY session). Higher-timeframe 4h/daily posts provide context and supply/demand zones. Trigger levels and confirmations are rule-like. Level selection, structure reading and "candle setup" judgment are discretionary, and TCP explicitly says not to apply candle setups by rote.

### Cited Findings
- [Q] BTC daily analysis on the 1h timeframe, targeting the New York session — [Daily 114](https://tw.tradingview.com/chart/BTCUSDT/SC0AeFnh-TradeCityPro-Bitcoin-Daily-Analysis-114).
- [Q] TCP's 4-hour posts follow a zone-based style with supply/demand areas, trendlines and breakout/rejection levels — [BTCUSDT ideas](https://www.tradingview.com/symbols/BTCUSDT/ideas/).
- [Q] Daily candle used for SMA25 hold confirmation (ARB) — [ARBUSDT ideas](https://www.tradingview.com/symbols/ARBUSDT/ideas/?sort=recent&video=yes).
- [T] leemeenal titles: "تحلیل آلت کوین امروز؛ ۱۰ فرصت وقتی بیت کوین رنج است" (10 altcoin opportunities while BTC ranges) — [leemeenal](https://leemeenal.app/video/altcoin-analysis-bitcoin-range/); "تحلیل بیت کوین امروز و حمایت ۸۰ هزار دلار" — [leemeenal](https://leemeenal.app/video/bitcoin-analysis-80k-support-altcoins/); "با دلار چه کنیم؟" (USD/IRR context) — [leemeenal](https://leemeenal.app/video/what-to-do-with-dollar/).
- [Q] Forex: USDCAD breakout/fakeout idea — [USDCAD ideas](https://www.tradingview.com/symbols/USDCAD.10.CFD/ideas/).
- [T] Course playlist "آموزش تحلیل تکنیکال از 0 تا 30 درصد" — [leemeenal playlist](https://leemeenal.app/playlists/trade-city-pro/playlist0-30/). "آموزش تحلیل تکنیکال پارت ۴" (S/R) — [leemeenal](https://leemeenal.app/video/support-and-resistance-technical-analysis/). Telegram channels — [t.me Tradecity_pro](https://t.me/s/Tradecity_pro?after=8999); [t.me tradecitypro_education](https://t.me/s/tradecitypro_education).
- [Q] Discretion warning: the candle-setup video says a setup-looking candle is not automatically a trigger; momentum and structure must be read — [leemeenal candle-setup](https://leemeenal.app/video/bitcoin-analysis-candle-setup/).
- Brand caution: Trader's Union rates a different broker, "Tradecity" (tradecity.co), as a scam. That broker is unrelated to TradeCityPro's analysis accounts — [TradersUnion](https://tradersunion.com/scam-or-safe/tradecity-review/).

### Inferences
- [I] Multi-timeframe use appears to be: 4h/daily for zones and trend, then 1h for the box and trigger. A lower timeframe (15m/5m) might be used for refined entries, but nothing found confirms this.
- [I] Rule-based components that could be coded: stop-order break of box high/low; volume > some volume average; RSI vs 50 and 70/30; price pullback to SMA7/25/99 plus a confirmation candle close; SL on a candle close beyond the broken zone; 0.5% risk sizing; fakeout = close back inside the range.
- [I] Discretionary components: choosing the box or "important zone", judging "structure built after pullback", candle-setup quality, and BTC.D and correlation context.

### Gaps
- No quantitative backtest or performance record for TCP setups was found.
- No explicit scalping/day/swing variant naming was found. Explicit higher-to-lower timeframe rules were not found either.
- Gold and other non-crypto markets are not confirmed beyond one forex idea and USD commentary.
