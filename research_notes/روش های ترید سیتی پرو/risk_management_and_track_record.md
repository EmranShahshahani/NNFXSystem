# Trade City Pro (ترید سیتی پرو): Risk Management, Position Management, Track Record and Business Model

Method note: WebFetch and curl could not reach t.me, telegram.me, tradingview.com, outlierkit.com or web.archive.org from this environment (DNS failure or proxy 403). So **every finding below comes from search-engine snippets or summaries**, not from reading the full page. Treat numbers as "quoted in the snippet". Each one should be checked against the live page before anyone relies on it. Labels used: **[Quoted]** means the text appeared in a snippet attributed to a TCP-owned page. **[Inferred]** means it is my reasoning.

## 1. Concrete capital/risk rules (risk per trade, R:R, leverage, number of positions, loss limits)

### Takeaway
TCP's English "TradeCityPro Academy" posts on TradingView give a specific tiered model. Risk per trade runs from 0.1% to 1% of capital and depends on how many checklist confirmations the setup has. Risk sits under a **daily risk limit**, with examples of 1% and 1.5%, plus a **monthly drawdown stop** (example: 10%). They also publish a TradingView position-size indicator that sizes from capital, risk %, stop % and leverage, with up to 5 TP targets. I found no explicit maximum leverage and no fixed maximum number of concurrent positions.

### Cited Findings
- **Risk = the loss if the stop is hit, not the position size.** The academy defines risk as the capital you lose when the stop loss is hit [Quoted] — [TradeCityPro Academy: Risk Management (TradingView)](https://www.tradingview.com/chart/BTCUSDT/zApQnqon-TradeCityPro-Academy-Risk-Management/)
- **Four setup tiers by confirmations (risk per trade as % of main capital)** [Quoted, per search summary of the post] — [TradeCityPro Academy: Risk Management](https://www.tradingview.com/chart/BTCUSDT/zApQnqon-TradeCityPro-Academy-Risk-Management/)
  - *Very Risky* (1–2 confirmations): "Trade with less than 0.1%–0.25% of your main capital", ideally in a separate test account.
  - *Risky* (some confirmations, key ones missing): 0.25%–0.5%.
  - *Normal* (most checklist items, about 6–7 of 10): 0.5%–0.75%. Normal trades should be most of the day's activity.
  - *Confident* (all major confirmations plus 8–9 of 10 checklist items): "Use 0.75%–1% of your capital for these trades." 1% is the ceiling.
- **Daily risk budget:** don't spend the whole daily limit on the first trade. With a 1.5% daily limit, for example, keep some in reserve in case the first trade stops out [Quoted/summarised] — [TradeCityPro Academy: Risk Management](https://www.tradingview.com/chart/BTCUSDT/zApQnqon-TradeCityPro-Academy-Risk-Management/)
- **Daily risk limit defined** as the most you accept losing before ending the day. Per-position risk sits inside it. With a 1% daily limit, one position might risk 0.25%, 0.5% or 1% depending on how many trades you plan [Quoted/summarised] — [TradeCityPro Academy: Money Management (TradingView)](https://www.tradingview.com/chart/BTCUSD/ANXXXHiL-TradeCityPro-Academy-Money-Management/)
- **Monthly drawdown cap:** example of stopping for the month after a 10% loss [Quoted/summarised] — [TradeCityPro Academy: Money Management](https://www.tradingview.com/chart/BTCUSD/ANXXXHiL-TradeCityPro-Academy-Money-Management/). One search summary said it found no TCP monthly cap, which conflicts with this. The summary of the Money Management post itself does mention it, so it should be checked on the page.
- **Persian Telegram daily-loss heuristic:** "اگر بیشتر از ۳٪ سرمایه امروز وارد ضرر شدین حتما ویدیو مدیریت سرمایه و ریسک به ریوارد داخل کانال آموزش نگاه کنید" ("if you have lost more than 3% of your capital today, be sure to watch the money-management and risk-to-reward video in the education channel"). This frames 3% a day as an alarm level, not as a stated rule [Quoted] — [Trade City Pro Telegram (indexed page)](https://telegram.me/s/Tradecity_pro?before=9669); education channel: [t.me/s/tradecitypro_education](https://t.me/s/tradecitypro_education)
- **Position-size formula / indicator:** "TCP | Money Management indicator | Crypto Version" on TradingView handles spot, perpetual futures and leverage tokens. It uses capital, risk %, leverage and up to **five take-profit targets with partial closes**. The quoted formula is: "Position Size = (Capital × Risk %) ÷ (Stop Loss % × Leverage)" [Quoted] — [TCP Money Management indicator (TradingView)](https://www.tradingview.com/script/zSsk5nXf-TCP-Money-Management-indicator-Crypto-Version/); [Turkish mirror](https://tr.tradingview.com/script/zSsk5nXf-TCP-Money-Management-indicator-Crypto-Version/). A YouTube tutorial also presents this TCP indicator as calculating position size, stop and R:R automatically (seen only in a search summary, no direct URL).
- **R:R:** TCP-format signal blocks reportedly list entry, stop, several targets and an R/R value. One BTC example: entry 84,161, stop 83,679, R/R = 2 — [BTCUSDT ideas listing (TradingView)](https://www.tradingview.com/symbols/BTCUSDT/ideas/page-6/). **Attribution uncertain:** the snippet came from a multi-author ideas listing.

### Inferences
- [Inferred] The house model is "fixed-fractional risk scaled by setup quality, under a daily and a monthly loss budget". Leverage only sets margin, because size comes from stop distance. In their formula the "× Leverage" term returns margin (collateral), not notional exposure. A backtest should size by risk %, not by leverage.
- [Inferred] A reasonable parameterisation for reconstruction: risk 0.5% on Normal setups and 1% on Confident ones, a 1–1.5% daily stop, a 10% monthly stop, and R:R of about 2 or more per target ladder.
- [Inferred] The number of concurrent positions is controlled indirectly through the daily risk budget (for example 1.5% daily / 0.5% per trade, so about 3 losing trades a day). No explicit cap was found.

### Gaps
- No explicit maximum leverage (for example "max 10x") found. No explicit maximum number of open positions.
- No weekly loss limit found.
- I could not read the full TradingView academy posts or the Persian YouTube videos on مدیریت سرمایه (money management). The exact wording and any minimum R:R (for example "at least 1:2") are unverified.

## 2. Open-position management (ریسک فری "risk-free" / breakeven stop, سیو سود "save profit" / partial take-profit, پله‌ای "stepped" / trailing)

### Takeaway
Evidence is thin. The TCP indicator supports up to five partial-close targets, so stepped profit-taking (سیو سود پله‌ای) is built into their tooling. Their BTC updates show indicator-based exits, such as holding a long while RSI stays overbought. I found no TCP-specific rule for when to move the stop to breakeven (ریسک فری کردن).

### Cited Findings
- Up to 5 TP targets with partial closes in the TCP money-management indicator [Quoted] — [TCP Money Management indicator](https://www.tradingview.com/script/zSsk5nXf-TCP-Money-Management-indicator-Crypto-Version/)
- Exit rule seen in TCP BTC updates: keep a long open "as long as RSI remains in the overbought zone, and taking profit once RSI exits the overbought zone" [Quoted; from search summary of TCP TradingView posts] — e.g. [TradeCityPro Bitcoin Daily Analysis 38](https://tw.tradingview.com/chart/BTCUSDT/p88KAF1A-TradeCityPro-Bitcoin-Daily-Analysis-38), [Daily Analysis 35](https://tw.tradingview.com/chart/BTCUSDT/vUGRpN9z-TradeCityPro-Bitcoin-Daily-Analysis-35) (exact post for this quote not pinned down)
- Order-cancellation logic: "I'm expecting a strong reaction in the body of the bullish engulfing candle. If it falls too deep and doesn't recover, I'll cancel the order." [Quoted, tradecitypro on BINANCE:BTCUSDT] — [tradecitypro TradingView profile](https://www.tradingview.com/u/tradecitypro/)
- "Trigger" framing: updates say outright whether a trigger exists, e.g. "for a new position, we currently don't have a trigger" and "we have a new trigger today" [Quoted] — [tradecitypro TradingView profile](https://www.tradingview.com/u/tradecitypro/)
- Telegram reminders to keep stops: "اگر پوزیشن لانگ دارین حد ضرر فراموش نکنید" ("if you have a long position, don't forget your stop loss") [Quoted] — [Trade City Pro Telegram](https://telegram.me/s/Tradecity_pro?before=9669)
- Generic Persian definitions, **not TCP**, for context: ریسک فری = move the stop to entry or into profit. سیو سود = close part of the position to lock in gains. The common combination is to close part at TP1 (one source says ≥50%) and move the rest to breakeven — [khanesarmaye: risk-free](https://khanesarmaye.com/risk-free/), [khanesarmaye: save-profit](https://khanesarmaye.com/save-profit/)

### Inferences
- [Inferred] TCP's practice probably follows the Iranian-community norm: partial close at a target, then a breakeven stop, with multi-target ladders as in their indicator. This is not confirmed from TCP's own text.

### Gaps
- No TCP-specific rule found for ریسک فری timing (for example "at 1R" or "after TP1"), partial percentages per target, or a trailing-stop method.
- No guidance found on scaling in (پله‌ای ورود, stepped entry).

## 3. Publication channels, business model, verifiable track record

### Takeaway
TCP publishes free analyses on Telegram (@Tradecity_pro, about 76k members), the education channel @tradecitypro_education, YouTube, Instagram (about 173k), X (@Tradecityproio) and TradingView (numbered "TradeCityPro Bitcoin Daily Analysis #N" ideas, which have passed #380). Revenue appears to come from a paid Discord ($35 is cited, but only from a Forex City Pro Telegram post), exchange affiliate links, and an academy/platform (Leemeenal/لیمینال). **No audited or aggregated performance record was found.** The numbered, timestamped TradingView ideas are the best material for reconstructing calls, but many are analysis "triggers" rather than full entry/stop/target signals.

### Cited Findings
- Telegram @Tradecity_pro: about 76,476 subscribers; slogan "🐋 جایی که زندگی رو ترید میکنیم !" ("where we trade life"); links to Instagram, YouTube and the support bot @Leemeenal_bot — [t.me/Tradecity_pro](https://t.me/Tradecity_pro), [t.me/s/Tradecity_pro](https://t.me/s/Tradecity_pro)
- Education channel @tradecitypro_education — [telemetr.io listing](https://telemetr.io/en/channels/1354519708-tradecitypro_education/quote), [t.me/s/tradecitypro_education](https://t.me/s/tradecitypro_education)
- Forex sister channel "Forex city pro" (about 994 members): "تحلیل ها به پوزیشن ختم میشوند" ("the analyses end in positions"). Its content is gradually being moved to the main channel — [t.me/s/Forex_citypro](https://t.me/s/Forex_citypro?q=#eurjpy)
- **Discord price:** "هزینه اشتراک دیسکورد 35 دلار هست" ("the Discord subscription fee is $35"). Sign-up is by form, then team review and an email [Quoted from Forex City Pro Telegram] — [t.me/s/Forex_citypro](https://t.me/s/Forex_citypro?q=#eurjpy). The billing period (monthly or one-off) is not shown in the snippet. An English search found no official TCP Discord page. The public "TRADE CITY" Discord servers are an unrelated gaming community — [discordbotlist (unrelated)](https://discordbotlist.com/servers/trade-city-652200725656371203)
- Affiliate ties: the channel archive has a post promoting an exchange through an affiliate link (search summary) — [t.me/s/Tradecity_pro](https://telegram.me/s/Tradecity_pro?before=18068)
- Self-description on YouTube: free education in technical analysis and crypto trading, "به جای وعده‌های غیرواقعی، دانش و ابزار…" ("instead of unrealistic promises, knowledge and tools…") — [YouTube @Tradecitypro](https://www.youtube.com/@Tradecitypro/videos)
- LinkedIn: listed as an investment-advice firm founded in 2018, Istanbul HQ, small headcount — [LinkedIn](https://www.linkedin.com/company/tradecitypro)
- Instagram about 173K followers; the profile name shows "لیمینال" (Liminal/Leemeenal) — [Instagram](https://www.instagram.com/tradecitypro/); playlist mirror on leemeenal.app — [leemeenal.app playlist](https://leemeenal.app/playlists/trade-city-pro/playlist0-30/)
- Founder: ارشیا عزیزپور (Arshia Azizpour) appears in the series "دقایقی با ارشیا عزیزپور" ("A few minutes with Arshia Azizpour") on why TCP was founded, with crypto experience "از ۲۰۱۷ تا ۲۰۲۶" ("from 2017 to 2026"), and in a strategy series "استراتژی ترید ارشیاعزیزپور" ("Arshia Azizpour's trading strategy") — [X post](https://x.com/Tradecityproio/status/1809265298299597293), [YouTube: 2017–2026](https://www.youtube.com/watch?v=Jx36Wr9Idn4), [Strategy part 4](https://www.youtube.com/watch?v=O5CAWmov9K8), [Strategy part 3](https://www.youtube.com/watch?v=rui0-OuNWmY)
- TradingView numbered daily BTC analyses (e.g. #35, #38, #369, #379, #380). #379: "Bitcoin is still trading within the 81,646–87,016 range… breakdown below 81,646 much more likely". #369 listed TP targets and "a stop loss of $87,300 (worst case)". #380 discussed CPI — [Daily Analysis 38](https://tw.tradingview.com/chart/BTCUSDT/p88KAF1A-TradeCityPro-Bitcoin-Daily-Analysis-38), [Daily Analysis 35](https://tw.tradingview.com/chart/BTCUSDT/vUGRpN9z-TradeCityPro-Bitcoin-Daily-Analysis-35), [BITFINEX:BTCUST ideas listing](https://www.tradingview.com/symbols/BTCUST/ideas/?video=yes)
- Self-reported result, unverified: "I took that BTC short on 1min time frame and it gave me 400+ points target" — [tradecitypro TradingView](https://www.tradingview.com/u/tradecitypro/)
- Altcoin idea example: "TradeCityPro | ALTUSDT Analysis Good Spot Buying Opportunity?" — [ALTUSDT.P ideas](https://www.tradingview.com/symbols/ALTUSDT.P/ideas/page-2/?sort=recent). The stop 0.035 / target 0.05555 in that listing belongs to another author.

### Inferences
- [Inferred] Track-record reconstruction is feasible from the TradingView ideas. They are timestamped and cannot be edited after publishing, which is TradingView policy. They are also sequentially numbered, so gaps can be spotted. Telegram posts can be edited, so they are weaker evidence. Many posts are conditional "trigger" analyses (if X breaks, long). A tester would need to codify triggers instead of reading fixed signals.
- [Inferred] Business model: free content funnels to a paid Discord, an academy/indicators (Leemeenal), and exchange affiliate commissions. Affiliate income creates an incentive for frequent and leveraged trading, which slightly conflicts with the conservative risk tiers they teach.

### Gaps
- No performance statistics (win rate, monthly P&L, drawdown) found from TCP or from any third party.
- I could not verify whether Discord signals are published later, or whether paid members' calls differ from free ones.
- The $35 price comes from a single Telegram snippet. Its period and currency terms are unconfirmed.

## 4. Independent opinions / criticism

### Takeaway
I found **no independent reviews, scam reports or performance audits** of Trade City Pro in Persian or English. Searches for "نظرات" (reviews), "کلاهبرداری" (scam) and "review" returned only TCP's own content. The one user comment surfaced was about bugs in website sign-up and login.

### Cited Findings
- No credible fraud reports were found. Results were dominated by TCP's own videos. One YouTube comment under a BTC analysis video reported problems with site sign-up and login — [YouTube: تحلیل بیت‌کوین ترید سیتی پرو (Trade City Pro Bitcoin analysis)](https://www.youtube.com/watch?v=k-iky1UKo68)
- Outlierkit has a YouTube channel analysis/valuation page for tradecitypro, but it could not be fetched — [outlierkit](https://outlierkit.com/channel/tradecitypro)

### Inferences
- [Inferred] With no third-party verification, reliability has to be judged by backtesting their published rules and calls ourselves. Absence of criticism is not evidence of profitability.

### Gaps
- Trustpilot, Reddit, Persian forums and Telegram review groups: nothing indexed was found. Outlierkit metrics were not readable.
