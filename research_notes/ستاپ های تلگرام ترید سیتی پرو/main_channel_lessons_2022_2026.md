# Trade City Pro main channel (@tradecity_pro), 2022–2026: rules for a mechanical backtest of the current method

Source: `data/cache/telegram/main_edu_B_2022_2026.jsonl` (604 posts, 2022-01-01 to 2026-10-14), read in full.
Post URL pattern: `https://t.me/tradecity_pro/<id>`. Some rules are only stated in posts not tagged as education, so
`main_all.jsonl` (2022 onward) was also searched by keyword (risk %, ستاپ, کندل ستاپ, سیو سود, ریسک فری, استاپ بای,
SMA, RSI, دامیننس, نیویورک, لورج, قانون …). Posts from that search are marked **[ctx]**.

Tags: **[M]** mechanical as stated · **[O]** operationalisable (definition and small parameter grid proposed) ·
**[D]** discretionary (cannot be coded faithfully; leave out or proxy). Quotes are short excerpts, not whole posts.
Glosses are mine. Nothing here is a rule unless a post states it. Proposals are marked "Proposal".

---

## 0. What the file actually contains (read this first)

- **410 of 604 posts are image-only** (text is just `#آموزشی @tradecity_pro`, Feb–Oct 2023, a daily lesson series, including
  "اناتومی کندل" 10656 and quizzes 11633, 11733, 11821, 12333, 12430). Their content is in the images and **could not be
  read**. This is the largest gap.
- Mid-2023 to 2024: mostly YouTube video announcements (forex sister channel @forex_citypro: S/R, trendlines, MA,
  MACD, RSI, Bollinger, zigzag, fractal, MQL4 EA building, backtesting). These are titles only, with no rules.
- Late 2023: crypto glossary posts (DeFi, wallets, Wei…). Not relevant.
- **2025-02 to 2026-10: the useful part.** Worked trade examples and daily analysis posts by Arshia Azizpour and
  team (signed "MRA" = Mohammadreza, also "سامان جلیلیان"), plus the "استراتژی ترید ارشیا عزیزپور" video series
  (parts 1–6, Oct–Nov 2025; posts only promote the videos) and the Sept 2026 "challenge" days 2 (Dow), 5 (money
  management), 6 (dominance), 7 (probability). The strategy can be pieced together from repeated phrases across
  ~120 analysis posts. No post gives it in one complete, numbered form.
- **KBSM** appears only once, in a fan poem: «برخورد کردم به استراتژی کی بی اس ام» (10146, 2022-12-01, "I came across
  the KBSM strategy"). There is no definition anywhere in 2022–2026 text. **[D] / unknown.**
- Not found anywhere in 2022–2026 text: **Stoch RSI, volume MA, SMA 99 used as a signal (only once, as context),
  daily/monthly loss limits, the 24h pause after 3 losses, a fixed number of open positions.**

---

## 1. Core definitions used by the current method (vocabulary the rules rely on)

| Term | Meaning as used (evidence) | Tag |
|---|---|---|
| تریگر (trigger) | A horizontal price level. A break of it opens a position: «با شکست 0.0855 پوزیشن شورت باز کنیم» (26489, 2026-06-05). Triggers are drawn at recent swing highs/lows, box edges, trendline-break levels | [O] |
| تریگر اصلی / تریگر ریسکی / زودهنگام (main / risky / early trigger) | Every analysis lists a "risky/early" trigger (near level, small stop, lower probability) and a "main" trigger (structural level, more confirmation): «تریگر 128.27 اولین تریگریه… اما تریگر اصلی 141.82 خواهد بود. تریگر اولمون ریسکی و احتمال استاپ خوردنش بیشتره اما چون استاپ کوچیک تری بهمون میده… ریسک به ریوارد بیشتری» (27331, 2026-08-31, "first trigger is risky but has a smaller stop and higher R:R") | [O] |
| باکس رنج / محدوده (range box) | Horizontal range with a top (سقف), bottom (کف) and midline (میدلاین). Breakout of either side gives a trade | [O] |
| فیک / فیک بریک اوت (fake breakout) | Price closes beyond a level, then fails to hold and comes back: «کندل زیر این ناحیه کلوز داد ولی نتونست تثبیت بده و مجدد به بالای این ناحیه اومد» (21119, 2025-03-11) | [O] |
| تثبیت (consolidation/acceptance beyond a level) | A candle close beyond the level (implied throughout). Not defined numerically | [O] |
| کندل ستاپ (candle setup) | Arshia's candle pattern with SMA 7 (and 25). Entry is a stop order beyond the candle's shadow, stop behind the candle (see §3.2) | [O] |
| مومنتوم (momentum) | Read from RSI levels (entry into overbought/oversold, holding 50), candle size and volume | [O] |
| ضعف روند (trend weakness) | Falling volume, smaller green candles, shorter legs, RSI divergence: «حجم در کل این مدت کاهشی بوده… سایز کندل های سبز کوچکتر شده و موج های حرکتی، کوتاه تر شدن» (26156, 2026-05-07) | [O] |
| کندل نهنگی (whale candle) | One huge breakout candle. A breakout like this "can't be caught" with a breakout entry (26038), so an early trigger or stop order is preferred | [O] |
| سیو سود (save profit) | Partial take-profit | [O] |
| ریسک فری (risk-free) | Stop moved to entry | [M] |
| واچلیست (watchlist) | Weekly list of coins built on Sunday (§7) | [O] |

---

## 2. Market context filters (before any trigger)

### 2.1 Trade with the trend; counter-trend is reduced-risk only
- «طبق استراتژی من، پوزیشن هایی که باز میکنم باید در راستای روند باشه چون تریگرهای راحت و ریسک به ریواردهای بیشتری میتونیم داشته باشیم» (27331, 2026-08-31). Gloss: positions must follow the trend. **[O]**
- «ترید خلاف جهت روند در بلند مدت بیشتر باعث ضرر میشه» (27331, same post). Gloss: his journal shows counter-trend trades lose over time. **[O]**
- Counter-trend is allowed only with capped risk: «چون خلاف جهت رونده و ماکسیموم ریسکی که من درگیر این پوزیشن میکنم تا زمانی که روند نزولیه 0.25% خواهد بود» (26593, 2026-06-15). Gloss: counter-trend trades get at most 0.25% risk. **[M]**
- Counter-trend means a small stop and a fast partial: «اگه قراره روی اون با این تریگر پوزیشن شورت باز کنیم بهتره استاپ لاس کوچیک همراه با سیو سود سریع رو داشته باشیم ( مینیموم ریسک به ریوارد 2 )» (26043 [ctx], 2026-04-28). **[O]**
- The fake-breakout (V) setup against main momentum gets a small spot size: «چون پوزیشن خلاف جهت مومنتوم اصلی مارکت بوده با اسپات کوچک میزاشتیم» (21119, 2025-03-11). **[O]**
- 2022 statement of the same idea: «در جهت روند ترید کنید» (9215, 2022-05-09). **[O]**

Proposal (trend state, Dow-based, which matches §2.2): a swing-pivot trend on the analysis timeframe (4H default). Up = last
swing high > previous swing high and last swing low > previous swing low. Down = the reverse. Otherwise range.
Grid: pivot strength k ∈ {2, 3, 5} bars each side; analysis TF ∈ {4H, 1D}.

### 2.2 Dow theory defines trend change and invalidation
- Trend reversal needs a lower high (for longs): «هنوز هم داو تاییده خروج نداده و برای این اتفاق نیاز به سقف هم سطح یا پایین تر برای اولین نشانه های تغییر روند خواهد بود» (22838, 2025-07-09). Gloss: exit or trend change needs an equal or lower high. **[O]**
- No longs until the high that created the last lower low is broken: «تا زمانی که بالای 90278 نرفتیم پوزیشن لانگ معنی نداره… طبق داو سقفی که باعث شده ما کف پایین تری رو ثبت کنیم دقیقا همین مقاومته» (25436, 2026-01-26). **[M]** given pivots.
- The main reversal confirmation is a higher high and higher low beyond the trigger: «تایید اصلی صعودی شدن… با زدن یه سقف و کف بالاتر از 0.08385» (26627, 2026-06-19). Also «صبر میکنم قیمت یه سقف و کف پایینتر بزنه و بعدش شورت باز میکنم» (25981, 2026-04-25). **[O]**
- Accumulation box at market bottoms: entry is the box breakout, not the bottom. «شکست سقف باکس رنج می‌تونه تأیید مهمی باشه که این محدوده واقعاً یک Accumulation Zone بوده… به‌جای اینکه بخوایم دقیقاً کف بازار رو پیش‌بینی کنیم، می‌تونیم منتظر تأیید بمونیم» (27344, 2026-09-01). Volume falls inside the box and rises on the breakout. **[O]**

### 2.3 BTC dominance (BTC.D) and altcoin selection
- Dominances checked in the pre-trade routine: «تحلیل دامیننس‌ها (BTC.D, USDT.D, TOTAL2, TOTAL3)» (23061, 2025-07-26). OTHERS.D is also used (25754 [ctx]). **[O]**
- BTC.D falling → trade alts long. BTC.D rising → BTC, or alts whose BTC pair is rising: «در صورت ریزشی شدن دامیننس بیتکوین من هیچ توجهی به بیتکوین نمیکنم و سراغ ادامه دادن پوزیشن لانگ روی آلت کوین ها میکنم ولی در صورتی که… دامیننس بیتکوین صعودی باشه میانگین جدیدی روی بیتکوین خواهم داشت» (23029, 2025-07-23). **[O]**
- «دامیننس بیتکوین ما داره به رشد… ادامه میده , پس یعنی فعلا تمرکز ها روی بیتکوینه حالا اگه کوینی به Pair بیتکوین صعودی باشه رشد شارپ تری رو خواهد داشت» (22732, 2025-06-26). **[O]**
- Shorts in a falling market with BTC.D rising go on an altcoin: «میتونیم با شکست 88963 پوزیشن شورت باز کنیم و در صورتی که دامیننس بیت کوین توی این شرایط صعودی باشه… بهتره پوزیشن خودمون رو روی یک آلت کوین باز کنیم» (25418, 2026-01-24). Also: BTC.D up and BTC red → short alts (25911 [ctx]). **[O]**
- Short candidates are BTC, or alts whose BTC pair is falling, when BTC.D is losing support and BTC is weak (25703, 2026-03-28). **[O]**
- Dominance confirmation is required for an alt long: «من خودم تا زمانی که تاییدیه دامیننس رو نگیرم با این تریگر پوزیشن باز نمیکنم» (27711 [ctx], 2026-10-13). **[O]**
- Check that BTC.D and BTC move together at the moment a trigger breaks: «فقط لحظه شکست تریگر ها نیازه چارت اون رو بررسی کنید که ببینید همزمانی دارن یا خیر» (25657, 2026-03-02). **[O]**
- When BTC.D is rising, spot buying is pointless: «اسپات باز این دامیننس بیت کوین فعلا معنی نداره دیر تر می خریم ۳۰ درصد دیرتر می خریم ولی مطمعن می خریم» (22639, 2025-06-15). **[O]**
- When BTC.D is in a range (25752, 2026-04-04: box 58.34–60.77 for over 6 months), BTC and alts move together. A breakdown below 58.34 then 57.49 makes the dominance trend down. **[O]**
- ETH/BTC used the same way: ETH outperforms when ETHBTC rises, so short BTC rather than ETH (25714, 2026-03-31). **[O]**

Proposal (codable dominance regime): BTC.D trend from the §2.1 pivot rule on 1D (or EMA slope as a fallback). Coin-to-BTC
strength = the coin/BTC pair trend on 4H/1D. Regime table:
BTC.D down → alt longs allowed, alt shorts blocked. BTC.D up and BTC up → BTC longs, plus alts with a rising BTC pair. BTC.D up and
BTC down → alt shorts preferred. BTC.D range → no filter. Grid: TF ∈ {4H, 1D}; pivot k ∈ {3, 5}.
Data need: BTC.D history (TradingView CRYPTOCAP:BTC.D).

### 2.4 No-trade conditions (hard filters)
- **Inside a range box, no trades (or risky trades only):** «داخل باکس من خودم پوزیشن باز نمیکنم اما از شکست 0.3224 میتونیم بعنوان تریگر ریسکی شورت برای پوزیشن کوتاه مدت استفاده کنیم» (27029, 2026-08-03). «هر پوزیشنی که داخل باکس 63879 تا 74967 باز میشه،پوزیشن ریسکی ایه و با ریسک کم و سیو سود سریع باید باز بشه» (25702, 2026-03-26). MRA: «تا زمانی که داخل محدوده رنج 63 تا 69 حضور داریم احتمالا کاری انجام ندم» (25657). **[O]**
- **No-trade zone after a big daily candle:** «کندل روزانه بیتکوین… حرکت بزرگی‌کرده و به احتمال زیاد میخواد استراحت کنه… نو ترید زون هستش» (10879, 2023-03-03). **[O]** Proposal: block entries for N bars after a daily candle with range > m·ATR(14). Grid: m ∈ {2, 2.5, 3}; N ∈ {1, 2} days.
- **Right after a big run, no entry ("you missed it"):** «الان دیگه جای جذابی برای ورود نیست» (20794, 21174, 2025-02/03). New entries only after a correction plus a new setup: «برای پوزیشن جدید باید صبر کنیم قیمت یه اصلاحی بده و بعدش توی موج بعدی صعودی با کندل ستاپ و مومنتوم پوزیشن باز کنیم» (26311, 2026-05-21). **[O]**
- **No momentum, no trigger:** «برای لانگ هم فعلا مومنتوم صعودی ای داخل مارکت وجود نداره و پس صبر میکنیم تا اول مومنتوم وارد بشه بعدش دنبال تریگر میگردیم» (25705 [ctx], 2026-03-29). **[O]**
- **No volume, no position:** «تا وقتی حجم وارد مارکت نشده پوزیشنی باز نکنم» (25999, 2026-04-26). **[O]**
- **Strong resistance just overhead blocks a long:** «بهتره که SMA بالاسر قیمت نباشه چون در ادامه میتونه مانع حرکت قیمت باشه» (25795, 2026-04-09). Also 26612: resistance zone above → high fake probability. **[O]**
- **Stop too large means wait (Rule 6):** «قانون ۶ ارشیا عزیزپور : وقتی استاپ پوزیشن که می خوام باز کنم زیادی بزرگه ( از نظر ساختاری) یا هنوز نقطه ورودم نرسیده یا نقطه ورودم رد شده در هر صورت باید صبر کنم» (25630 [ctx], 2026-02-27). **[O]** Proposal: skip if stop distance > s·ATR(14, trigger TF) or > p% of price. Grid: s ∈ {1.5, 2, 3}.
- Examples of skipping on stop size: «تنها پوینت منفی ای که این تریگر داره اینه که سایز استاپمون درحال حاضر خیلی بزرگه» (27600, 2026-09-28). «فعلا توی این تایم فریم خیلی جای استاپ خوبی نداریم… اما در تایم فریم های پایینتر میتونیم با شکست این لول پوزیشن باز کنیم» (27087, 2026-08-08). If the stop is too large on the analysis TF, the trigger can move down a timeframe. **[O]**
- **Trigger invalidation:** a trigger is only valid while price holds the structure: «تریگر 10.674 هم تا وقتی بالای 10.07 هستیم معتبر هست و اگر این حمایت از دست بره دیگه این تریگر برامون اعتبار نداره» (27577, 2026-09-25). Also 27323 and 27589. **[M]** once levels are defined.

---

## 3. Named setups and entry triggers

### 3.1 Breakout trigger (the default entry) — entered with stop-buy / stop-sell orders
- «داخل استراتژی ترید بریک اوت خودمون خیلی وقته که مارکت نمیزنیم و همه پوزیشن ها عملا با استاپ بای باز میشن» (23423, 2025-08-25). Gloss: in the breakout strategy all positions are opened with stop-buy (stop entry) orders, never market orders. **[M]**
- «این کار فقط قرار دادن یه استاپ لاس و استفاده از تریگر به جای مارکت باز کردن پوزیشنه ! که اکثر اوقات باعث میشه استاپ لاس کمتر بخورید» (20910 [ctx], 2025-03-01). **[M]**
- Stop orders are placed when price approaches the level, after checking the order book; the level can move to where the order-book liquidity sits (27498, 27192, 27143, 27159 [ctx/edu]). «تو اردر بوک تا محدوده 0.00292 اردر فروش زیاد هست و یه محدوده مقاومتی بین این دوناحیه میتونیم درنظر بگیریم» (27143, 2026-08-13). **[D]** (no order-book history). Proxy: treat the trigger as a zone [level, level + z·ATR]. Grid: z ∈ {0, 0.25, 0.5}.
- Trigger TF choices seen: 15m, 1H, 4H, 1D (spot). Example: «بعد از شکست تریگر 82510 به همراه کندل اینگولف پوزیشن ما فعال شد» (21174, 2025-03-13, BTC 15m). **[O]**

Proposal (mechanical breakout entry): on trigger TF T ∈ {15m, 1H, 4H}, the trigger level is the last confirmed swing high
(long) or swing low (short) of the current structure, or the range-box edge. Entry is a stop order at level + tick. Grid:
pivot k ∈ {2, 3, 5}; entry buffer ∈ {0, 0.1·ATR}. Optional "close beyond" variant (تثبیت) vs. touch variant, which tests
the 2021 "pullback" rule against the current "stop-order" rule.

### 3.2 Candle setup (کندل ستاپ) — Arshia's own candle trigger
- Uses SMA 7, and SMA 25 alignment raises win rate: «برای کندل ستاپ ارشیا عزیزپور ما بیشترین استفاده رو از SMA 7 داریم و… زمانی که SMA 25 نیز همراه ماست وین ریت بالاتری خواهیم داشت» (23522 [ctx], 2025-09-02). **[O]**
- Order placement: «پوزیشن لانگ RENDER همراه کندل ستاپ 4 ساعته خودش که استاپ بای رو بالای Shadow اون و استاپ لاس رو پشت کندل قرار دادیم» (26143 [ctx], 2026-05-06). Gloss: stop-buy above the setup candle's upper shadow, stop-loss behind (below) the candle. **[M]** once the candle is defined.
- Prerequisites listed in the setup video promo: «کندل‌شناسی… قدرت خریدار و فروشنده… حمایت و مقاومت… مووینگ اوریج‌ها» and «شاید قبل از رسیدن به ستاپ اصلی، ۲ تا استاپ بخوری» (23118 [ctx], 2025-07-30: "you may take 2 stops before the main setup"). **[D]** for the candle's exact shape (the shape is only in videos).
- Uses: (a) an early entry before a level that would break with a whale candle: «اگر قبل از شکست کندل ستاپ زده بشه میتونیم با کندل ستاپ هم پوزیشن باز کنیم» (26556, 2026-06-11). «با استاپ بای و یا کندل ستاپ قبل شکست میتونیم پوزیشن زودهنگام باز بکنیم» (26941, 2026-07-24). (b) Entry on a pullback to SMA 7/25: «میانگین های 25 و 7 هم شیبشون رو به پایین شده و پولبک قیمت به این میانگین ها رو میتونیم با کندل ستاپ پوزیشن باز کنیم؛ اما این تریگر ریسکی تر خواهد بود» (26038, 2026-04-28). Also 26040 [ctx]. (c) A continuation entry after a correction (26311). (d) It keeps the stop small: «کندل ستاپ هم بهمون داد که سایز استاپمون کوچیک تر بشه» (18047 [ctx], 2024-09-03). **[O]**
- Lineage: the 2023 videos «آموزش ستاپ ترید ارشیا عزیزپور بر اساس پرایس اکشن و کندل شناسی و مووینگ اورج» (12049, 2023-05-16) and the 2024 «آموزش کندل ستاپ» (18641) descend from the 2021 indecision-candle stop-order trigger. Also «ایندیسیژن قرمز» (a red indecision candle) is used as a profit-save signal on BTC 4H (12557 [ctx], 2023-06-23).

Proposal (codable candle setup; it must be validated against the videos):
- Long: SMA7 slope > 0 (optionally SMA25 slope > 0 and SMA7 > SMA25); the setup candle is a small-bodied/indecision or
  pullback candle whose low touches or comes within d·ATR of SMA7 (or SMA25), closing above SMA7 (or SMA25).
- Entry: buy-stop at the candle high (shadow) + tick, valid for n bars. Stop: candle low − tick (plus an optional buffer).
- Short: mirror.
- Grid: body/range ≤ {0.3, 0.5}; d ∈ {0, 0.25·ATR}; SMA25-alignment filter on/off; order validity n ∈ {1, 2, 3} bars;
  TF ∈ {15m, 1H, 4H}.

### 3.3 Fake-breakout setup (استراتژی/تریگر فیک, "V-pattern")
- Definition and trigger: «در تایم فریم 15دقیقه یه حمایت مهم… داشتیم که کندل زیر این ناحیه کلوز داد ولی نتونست تثبیت بده و مجدد به بالای این ناحیه اومد… آخرین سقفی که قبل از شکست 526.54 زده شده بود،ناحیه 540.33 بود و با شکست این ناحیه میتونستیم تایید فعال شدن V-pattern و… تایید فعال شدن تریگر شکست فیک رو بگیریم» (21119, 2025-03-11). Gloss: after a close below support and a reclaim, the long trigger is the break of the last swing high made before the breakdown. **[M]** given pivots.
- Management in that example: small spot size because it was against momentum. RSI overbought → save or close when RSI returns to normal. It reached R:R 4. **[O]**
- Short mirror: «در صورتی که مقاومت 107950 فیک بریک اوت اتفاق بیوفته یا با شکست تریگر 106680 میتونیم پوزیشن شورت باز کنیم» (22748, 2025-06-28). **[O]**
- "Fake trigger" on ETH: after failing to hold the 2375 break, a break of 2313 activates «تریگر فیک» short (25912, 2026-04-19). **[O]**
- Fake of a range top raises the odds of a bottom break (and vice versa): «معمولا زمانی که از سقف باکس فیک بریک اوت اتفاق میوفته و به کف حمایتی باکس میرسیم احتمال شکست از کف حمایتی بیشتر و بیشتر میشه مخصوصا زمانی که… وقتی که به سمت حمایت حرکت میکنیم حجم در حال افزایشه و از اون که بلند میشیم حجم در حال کاهش» (25436, 2026-01-26). Also 25418, 22732 (fake of box bottom → top breakout more likely), 26650 SEI. **[O]**
- Fake-breakout trigger as the first long trigger: «برای پوزیشن لانگ دقیقا اولین تریگر ما فیک بریک اوت حمایت 0.2052 هست» (26006 [ctx], 2026-04-26). **[O]**
- Forex team version: «کندل سبز رنگ نشون دهنده برگشت به بالای سطحه… استاپ لاس زیر کندل باشه و تارگت هم ریسک به ریوارد 2 تا 3 باشه… کندلی که نشون دهنده فیک بودن شکست هست نباید کندل ضعیفی باشه» (14733 [ctx], 2023-12-12). **[O]**

Proposal: level L = swing low (long case) with ≥ t touches. A fake = a close < L, then within w bars a close > L. Trigger =
max(high) between the last swing high before the breakdown and the breakdown bar. Entry = buy-stop at the trigger. SL = the
low of the fake move. Grid: w ∈ {1, 3, 5}; t ∈ {1, 2}; TF ∈ {15m, 1H, 4H}. Variant (forex 14733): enter at the close of the
reclaim candle if its body ≥ b·ATR (b ∈ {0.5, 1}), SL under the candle, TP ∈ {2R, 3R}.

### 3.4 Range box (باکس رنج) breakout, nested boxes, midline
- Long ranges create smaller boxes, so trade the small box with less risk and add on the main level: «وقتی باکس های رنج طولانی میشن در تایم های کوتاه مدت خودشون تلاش برای ساخت یک باکس میکنن… ما سعی میکنیم با شکست های باکس رنج کوچک تر خودمون اون هم با ریسک کمتر پوزیشن خودمون رو باز کنیم و صرفا با شکست لول های اصلی نقطه ورودی دوباره داشته باشیم و حجم بیشتری به پوزیشن وارد کنیم» (22748, 2025-06-28). **[O]** This is a scale-in rule: the small-box break is an initial low-risk entry, the main-level break is an add.
- Dow box-to-box: «بعد خروج از باکس اولین پوزیشن خودمون رو میتونستیم با استاپ لاس کف باکس باز کنیم… تریگر مجدد ما برای ترید شکست همین باکس بود» (22838, 2025-07-09). Gloss: the first entry is the box breakout with SL at the box bottom. The re-entry/add is the breakout of the next consolidation box. **[M]** given box detection.
- Higher lows inside the box mean a top breakout is likely: «اگر قیمت داخل باکس شروع به ایجاد کف های بالاتر بکنه احتمال شکست سقف باکس خیلی زیاد میشه… هرچقدر که این حجم بیشتر کم بشه، حرکت بعدی قیمت شارپ تر و نزدیک تر خواهد بود» (27029, 2026-08-03). Also 26650. **[O]**
- A long box neutralises momentum, so both sides become tradable: «با طولانی شدن این باکس از لحاظ زمانی، مومنتومی که داخل مارکت بود میشه گفت کاملا خنثی شده» (26650, 2026-06-22). **[O]**
- In a range, oscillators are not useful: «چون مارکت رنجه تاییدیه اوسیلاتورهای مومنتومی خیلی بدردمون نمیخورن» (27159, 2026-08-15). The SMAs also go flat in a long range: «بقیه SMA ها خاموشن چون رنج قیمت خیلی طولانی شده» (25795). **[O]** Proposal: disable the RSI filter when the range regime is active.
- Box first target is a one-box-height measured move: «اولین تارگت ما 0.1767 مقاومت پیش رو و ریسک به ریوارد 1 باکس هست» (25989 [ctx], 2026-04-25). **[O]**
- Box from the top: big stop; box from below: small stop and early save: «از بالا با استاپ بزرگ و از از پایین با استاپ کوچیک که زود سیو سود کنید» (18827 [ctx], 2024-10-23). **[O]**
- Midline support is bullish: «حمایت از میدلاین باکس» (25418, 23294). **[O]**

Proposal (box detector): over the last N bars on TF, (max−min) ≤ r·ATR(14)·√N, or Donchian width ≤ x% for ≥ N bars, with
≥ 2 touches per side. Grid: N ∈ {20, 40, 80}; r ∈ {1.5, 2, 3}; touches ∈ {2, 3}.

### 3.5 Pullback / retest entry (now secondary)
- After a breakout is missed: «اگر با شکست محدوده پوزیشن باز نکردید میتونید روی پولبک و یا با کندل ستاپ پوزیشنتون رو باز کنید» (26252 [ctx], 2026-05-16). Channel pullback entry on ETH (25714). **[O]**
- Pullback with falling volume, then a sharp move with rising volume, confirms the breakdown (23294, 2025-08-14). **[O]**

### 3.6 Momentum trigger (RSI)
See §5. «چون پوزیشن براساس مومنتومه، ممکنه شاهد ریزش شارپ باشیم پس بهتره که استاپ کوچیک بزاریم که در این صورت ریسک به ریوارد بالا بگیریم؛ ورود RSI به اورسل اولین نشونه شروع حرکت شارپ خواهد بود» (26264, 2026-05-16). Momentum positions use a small stop, and the partial is taken when momentum fades: «برای سیو سود هم اگر مومنتوم از مارکت رفت یا کم شد سیو سود انجام بدیم» (26051 [ctx], 2026-04-29). **[O]**

### 3.7 Level-touch rules (which touch to trade)
- Do not trade the first touch of a level: «توی برخورد اول این تریگر منطقی نیست و من خودم صبر میکنم از برخورد دوم به بعد در صورت شکستش پوزیشن باز میکنم» (25840, 2026-04-12). **[M]** given touch counting.
- A single-touch zone gets low risk: «به دلیل تک برخورد بودن ناحیه ریسک کم وارد معامله کنید» (25438 [ctx], 2026-01-26, gold). **[O]**
- Few touches of a daily resistance means expect several retests and false stops: «فعلا تعداد برخورد هامون به مقاومت کم هست و احتمال داره قیمت چند بار دیگه این ناحیه رو تست کنه» (27466, 2026-09-09). **[O]**
- Wait for a new reaction to locate a level before trading it: «نیاز به برخورد جدید دارم تا بتونم برای حمایت جدید خودم تصمیم گیری کنم» (25436). Also 25958. **[O]**
- The second touch weakens the opposing orders, so break odds rise (25869, 2026-04-15). **[D]/[O]**
- Probability framing: «چند بار میارزه که برای شکست این ناحیه استاپ بخورم؟» … «اگر اون تریگر… پتانسیل شروع یک روند شارپ داشته باشه، پس میارزه که حتی 5بار هم استاپ بخوریم؛ اما اگر یک تریگر ریسکی در تایم فریم های پایینتر باشه… شاید نیارزه» (27469, 2026-09-09). Gloss: decide in advance how many re-entries a level deserves: up to 5 for a major HTF level, fewer for LTF risky triggers. **[O]** Proposal: a re-entry budget per level: major (1D/1W) level ≤ {3, 5}; 4H ≤ {2}; 1H/15m ≤ {1}.

Proposal (touch definition): a touch = a bar whose high (resistance) is within τ·ATR of the level without closing beyond it, with
touches separated by ≥ g bars. Grid: τ ∈ {0.1, 0.25}; g ∈ {3, 5}.

---

## 4. Volume rules
- Breakouts need rising volume. Without it, the trade is very risky: «هم برای تریگر لانگ و هم برای تریگر شورت باید تاییدیه حجم رو داشته باشیم و حجم باید افزایش پیدا بکنه؛ در غیر این صورت پوزیشن هایی که باز میکنیم خیلی ریسکی خواهند بود» (25954, 2026-04-22). **[O]**
- A low-volume breakout is likely fake: «اگه قیمت با همین حجم کم بخواد از این باکس چه از بالا چه از پایین خارج بشه، احتمال فیک شدن حرکت بالا خواهد بود» (25981, 2026-04-25). **[O]**
- Volume–price divergence means a high fake probability: «اگر حجم با قیمت واگرایی داره باشه احتمال فیل شدن پوزیشن ها خیلی افزایش پیدا میکنه» (27050, 2026-08-05). Long trigger only «به شرطی که واگرایی حجم نداشته باشیم» (25920, 2026-04-20). **[O]**
- Healthy trend: volume falls on corrections and rises on impulse legs (27577, 27466, 2026-09). **[O]**
- Falling volume during a long range means the next move is near and sharp (27029, 26575 LINK triangle, 27050). **[O]**
- Volume weakness inside a long breakout → reduce risk, do not skip: «حجم یکم داره کم میشه… این موضوع باعث میشه یکم ریسکمون رو کم کنیم اما همچنان شکست 0.3342 تریگر خیلی خوبی» (25955, 2026-04-22). **[O]**

Proposal: volume confirmation = breakout-bar volume ≥ v × SMA(volume, n) **(the channel never names a volume MA; this is my
proxy)**. Grid: v ∈ {1.0, 1.2, 1.5}; n ∈ {20}. Divergence = price makes a higher high while the volume SMA(n) over the leg
< the previous leg. Risk modifier: volume weak → risk × 0.5 instead of skipping (test both).

---

## 5. Indicators and settings

### 5.1 RSI — momentum levels (period not stated; assume default 14, test 14 only unless videos say otherwise)
The current method draws **horizontal S/R lines on RSI itself** and treats breaks of them as momentum triggers. Fixed levels
used repeatedly:
- **Entry into overbought (>70) = long momentum confirmation, not a sell signal.** «یادتونه همه می گفتند ورود به اور بای یعنی فروش ولی من گفتم یعنی خرید؟» (18749 [ctx], 2024-10-13). «ورود RSI به اوربای همچنان تریگر مومنتومی خوبی برای لانگ خواهد بود» (26122, 2026-05-04). Many examples (25869, 25954, 27143, 27296, 27323, 27546). **[M]**
- **Entry into oversold (<30) = short momentum confirmation**: «اگر RSI بتونه زیر ناحیه 30 تثبیت بده و وارد اورسل بشه، احتمال وقوع سناریوی نزولی افزایش پیدا میکنه» (27087, 2026-08-08). Also 26489, 26556, 27041. **[M]**
- **50 = trend/momentum pivot**: «روی RSI هم یه حمایت خیلی مهم در ناحیه 50 داریم؛ توی این موج صعودی هربار RSI به این ناحیه رسیده حمایت شده» (25955). «RSI هم زیر ناحیه 50 تثبیت داده» → lost up-momentum (25970). Down momentum = RSI boxed 30–50: «RSI یه باکسی بین 30تا 50 تشکیل داده و نتونسته بالای ناحیه 50 خودش رو تثبیت کنه» (27041, 2026-08-04). Long breakout odds rise while RSI stays 50–70 (27444). **[M]**
- **Custom RSI levels taken from RSI's own swing points** (examples: 45.50, 44.33, 45, 72.73, 74.64, 60, 54.46 divergence trigger, 81.65, 75.58 "over-extend"): «اگر قیمت از این خط روند حمایت بشه و RSI زیر 45.50 نیاد، مومنتوم صعودی پابرجا خواهد بود» (25834). «شکست ناحیه 72.73 در RSI… تایید ورود به اوربای» (25869). «تریگر فعال شدن واگرایی این اوسیلاتور،54.46 هستش» (26156). **[O]** Proposal: RSI level = the most recent RSI swing high/low (pivot k=3) on the trigger TF. A momentum trigger is a break of it. Fallback: fixed {30, 45, 50, 55, 70}.
- **Price breakout + RSI move must coincide**: a breakout fails when RSI cannot enter overbought: «برای ادامه حرکت و شکست 77777 نیاز به مومنتوم داشتیم و این مومنتوم با شکست 72.73 در RSI به وجود میومد اما RSI بالای این ناحیه تثبیت نداد» (25920). After a long breakout, «RSI هم نتونست وارد اوربای بشه… احتمال فیک شدن 80418، افزایش پیدا کرده» (26125). **[O]** Proposal: after entry, if RSI does not exceed 70 within q bars, tighten the stop or take the partial. Grid: q ∈ {3, 6, 12}.
- **RSI in an uptrend correction**: «زمانی که روند صعودیه و RSI وارد اورسل میشه میتونیم انتظار داشته باشیم که در انتهای اصلاح هستیم» (27446 [ctx], 2026-09-07). **[O]** (a trend-pullback long filter)
- RSI divergence = trend weakness (26156, 27565). **[O]**

### 5.2 RSI-based profit management
- «یکی از روش های سیو سودمون وقتی RSI وارد اوربای میشه اینه که صبر کنیم RSI از اوربای خارج بشه و بعدش پوزیشن رو سیو سود کنیم» (27444, 2026-09-07). Gloss: when RSI enters overbought, hold. Save on the RSI exit back below 70. **[M]**
- «در صورتی که RSI وارد اوربای بشه شخصا تا وقتی داخل اوربای هست سیو سود نمیکنم» (27296, 2026-08-27). **[M]**
- Shorts mirror this: save when RSI exits oversold (27120 [ctx]). **[M]**
- 2025 version: «اوسیلاتور RSI وارد Overbuy شده و برای سیو سود و یا بستن پوزیشن میتونیم از بازگشت RSI به محدوده عادی تایید بگیریم» (21119). **[M]**

### 5.3 Moving averages
- **SMA 7** is the primary MA for the candle setup. **SMA 25** alignment raises win rate (23522). **[O]**
- **SMA 7 and 25 slope** gives direction for pullback entries (26038, 26040). **[O]**
- **SMA 25** as dynamic support that re-ignites momentum: «اندیکاتور SMA25 میتونه با رسیدن به قیمت، مومنتوم صعودی رو مجدد وارد قیمت کنه» (26896 [ctx], 2026-07-21). **[O]**
- **SMA 99** as a long-term momentum/resistance filter: «اندیکاتور SMA99 شیب نزولی داره و نشون دهنده مومنتوم نزولیه… با شکست SMA یه حرکت صعودی… و با ریجکت شدن از SMA، یه حرکت نزولی» (25795, 2026-04-09). **[O]** (7/25/99 are the Binance default SMAs, which matches the brief's premise.)
- MA20, MA50/200 golden cross are only mentioned generically (23522). Not part of the rules.

### 5.4 Other indicators (mentioned only, no settings in text)
- MACD (videos 12819/12868; definitions 23472). ADX: «اندیکاتور adx اندیکاتور rsi و macd بنداز دور» (20918, 2025-03-02, video title: an ADX video promoted as replacing RSI/MACD). ROC oscillator on 4H for entries/saves (10879, 2023-03-03). Fibonacci 0.382 and extensions (23278, 25702). Bollinger (12991). Pivot points (11565). **[D]** for all (settings unknown).
- Order book liquidity is used to adjust levels (§3.1). **[D]**

---

## 6. Stops, targets, R:R

### 6.1 Stop placement
- Candle setup: stop behind the setup candle (26143). Box breakout: stop at the opposite box edge, or at the box bottom for the first Dow entry (22838). Breakout: «استاپ لاس پشت کندل» (25436, 2026-01-26, 4H). **[M]**
- Spot buys give two stops, "risky" (near structure) and "safe" (deeper structure): «با استاپ باس سیف 104 دلار و ریسکی 143 دلار میتونید خرید اسپات داشته باشید» (22992, 2025-07-21). Also 23278, 23294, 26335 [ctx]. **[O]** Proposal: risky stop = last minor swing (k=2), safe stop = last major swing (k=5) on the spot TF (1D/1W).
- Momentum or LTF trades: small stop, fast save: «تریگر رو داریم توی تایم فریم 15دقیقه میگیریم پس قرار نیس انتظار داشته باشیم مارکت خیلی حرکت کنه؛ استاپ رو کوچیک میزاریم و سریع هم سیو سود میکنیم» (26627, 2026-06-19). **[O]**
- Breaking daily/weekly levels is volatile, so use wider stops: «شکست مقاومت های روزانه و هفتگی معمولا دارای نوسانه و نباید استاپ لاس خیلی ریسکی بزارید» (25825 [ctx]). Also 25918: «نیازه استاپ لاس مطمعن تری قرار بدید». **[O]**
- **The stop is always set at the moment of entry (hard rule)**: «پوزیشن باز میکنی هم زمان استاپ هم میزاری هم زمان چون شاید نت قطع بشه» (22639, 2025-06-15). «استاپ نداشتن ممنوع» (22713 [ctx], 2025-06-24). During internet disruption the stop must be a market-type stop: «استاپ لاستون رو قبل از باز کردن پوزیشن ست کنید و حتما تایپ مارکت باشه» (25657, 2026-03-02). **[M]** For the backtest, stop-market fills with slippage.
- In a crash, stops do not protect you; only position sizing does (27415, 2026-09-05, LUNA example). **[M]** See the §8 per-coin cap.

### 6.2 Risk-to-reward
- Minimum R:R 2 for his own crypto trades: «ریسکتون ۱ ریواردتون ۲… این مینیمم ریسک به ریواردی هست که من برای ترید های خودم قائلم» (10710, 2023-02-18). **[M]**
- Rare exceptions below 2R trigger an immediate reverse trade: «شاید از هر ۱۰۰ تا ترید یک ترید رو ریسک به ریوارد پایین تر ببندم که در اون مواقع همون لحظه ترید برعکس باز میکنم» (10710). **[D]**
- Forex minimum 3R. In crypto, 3R usually implies 5R: «در کریپتو… اگر ریسک به ریوارد ۳ رو بخواد بده ریسک به ریوارد ۵ رو هم میده در فارکس مینیمم ریسک به ریوارد من ۳ هستش» (10711, 2023-02-18). **[M]**
- Runner philosophy: after saving at 2R and going risk-free, trail to 10–30R, which happens 2–3 times a month. Most trades close around 5R: «بعد از سید سود رو ریسک به ریوارد ۲ و ریسک فری کردن با دنبال کردن بازار و جابه جا کردن حد ضرر ریسک به ریوارد های ۱۰ ۲۰ ۳۰ میگیرم… ماهی ۲ الی ۳ بار هستش اکثرا در ریسک به ریوارد ۵ بسته میشن» (10711). **[O]**
- He closes at 20–30R without thinking: «من رو ریسک به ریوارد ۲۰ یا ۳۰ بدون تفکر میبندم پوزیشن را» (10711). **[M]** Proposal: hard TP at {20R, 30R}.
- Pre-trade check that 2R is reachable before the next major resistance: «بهتره پوزیشنی که باز میکنیم، قبل از رسیدن قیمت به 2358 به ریسک به ریواردش برسه و سیو سود بشه» (25793, 2026-04-09). **[O]** Proposal: skip if (next HTF resistance − entry) < 2 × (entry − stop).
- Win-rate framing: R:R 1:2 needs > 33% to break even. He claims 50–60% accuracy at 1:2 is enough (10710). **[M]** (useful as a sanity benchmark)

### 6.3 Targets
Targets are the next S/R levels: «اگر قیمت بتونه بالای یک مقاومت تثبیت بده، میتونه تا مقاومت بعدی رو به بالا حرکت بکنه» (27365, 2026-09-03). Measured move = one box height (25989). Fib extensions for spot (23278). **[O]** Proposal: TP1 = max(2R, next pivot level). The runner is managed per §7.

---

## 7. Position management (ریسک فری, سیو سود, پله‌ای, trailing, scaling)

| Rule | Evidence | Tag |
|---|---|---|
| Partial at T1 = 2R: 35% saved (2022 VIP) | «روی تارگت ۱ که ریسک به ریوارد ۲ بوده ۳۵٪ سیو سود هم داشتیم» (8548 [ctx], 2022-01-26). VIP: «اولین تارگت ها همیشه ریسک به ریوارد ۲ هست» (8882 [ctx]) | [M] |
| 2026 rule of thumb: fresh positions save 30% and go risk-free. Old (deep-in-profit) positions take no partial | «۳۰ درصد سیو سود واسه پوزیشن های تازه / هیچی سیو سود واسه پوزیشن های قدیمی / ریسک فری پوزیشن های جدید» (27379 [ctx], 2026-09-03) | [M] |
| At ~5R, save 40% and make it risk-free | «در حال حاضر روی ریسک به ریوارد 5 هست , میتونید 40 درصد سیو سود کنید و از این پوزیشن یه ریسک…» (26181 [ctx], 2026-05-09) | [M] |
| At 2–3R: either save one position or go risk-free | «روی ریسک به ریوارد 2 و 3 حضور دارند , میتونید یکی از اون هارو سیو سود کنید یا کامل ببندید ( من خودم هر دو پوزیشن رو ریسک فری کردم )» (26154 [ctx], 2026-05-07) | [O] |
| Stop to entry instead of a partial (when the market is trending) | «من صرفا استاپ لاس خودم رو روی نقطه ورود قرار دادم و سیو سودی نمیکنم» (22992, 2025-07-21) | [M] |
| Keep a ~10% runner after the main save | «این سیو سود اصلی این پوزیشنمون خواهد بود. من خودم 10% از پوزیشن رو باز نگه میدارم» (26436 [ctx], 2026-06-01) | [M] |
| Save at the next resistance, but don't close all if the entry was good | «من خودم هم این محدوده مقاومتی رو برای سیو سود در نظر می‌گیرم، ولی کل پوزیشنم رو نمی‌بندم چون ورود خیلی خوبی داشتم» (20794, 21174, 2025) | [O] |
| Save at the channel top / major level | «الان که قیمت به سقف کانال رسیده لول خوبی برای سیو سود هست» (26156) | [O] |
| RSI-overbought hold-then-save | §5.2 (27444, 27296) | [M] |
| Momentum trades: save when momentum fades | 26051, 26207 [ctx] | [O] |
| 15m: no save until a red candle | «تا وقتی کندل قرمز نبینم تو ۱۵ دقیقه سیو سود نمی کنم» (27262 [ctx], 2026-08-23) | [M] |
| Exit a long on a close below the last higher low / structure | «اگر از قبل روی سولانا پوزیشن لانگ دارید با تثبیت قیمت زیر 116.28 میتونید پوزیشن رو ببندید» (27565, 2026-09-23). «در صورت شکست 2.756 و بسته شدن کندل هفتگی زیر این حمایت خروج بزنید» (23278, spot weekly) | [M] |
| Range expected → partial | «در صورت داشتن پوزیشن شورت مقداری سیو سود به دلیل اینکه بازار ممکن است ۷۲ساعت در این محدوده بماند جایز است» (10879, 2023-03-03) | [O] |
| No-trend market → early saves | «سیو سود زودهنگام هم داشته باشیم به خاطر اینکه مارکت روندی رو نداره» (25703, 2026-03-28) | [O] |
| Scale-in (pyramiding) on the next trigger | «با شکست 165.49 به پوزیشن دیروز خودم حجم اضافه میکنم و با سودی که از این پوزیشن کردم با شکست 179.71 سولانا خریداری میکنم» (22992). Small-box break → add on the main level (22748). After a risky early trigger, the main trigger confirmed and «فرصت باز کردن یه لانگ دیگه رو داشتید» (20794) | [O] |
| Close a second position at 5R to protect the first | «این پوزیشن دوم الان ریسک به ریوارد ۵ هست اینو کلوز میدم کلا که پوزیشن قبلی رو بتونم باز نگه دارم» (18779 [ctx], 2024-10-16) | [O] |
| Trailing: after risk-free, "follow the market and move the stop" (10711), structurally by Dow (exit on an equal/lower high, 22838) | 10711, 22838 | [O] |
| Bull-run spot exit: stepwise; e.g., withdraw principal at each +100% | «خروج پله‌ای انجام بده (مثلاً هر 100% رشد اصل سرمایه رو خارج کن)» (23210 [ctx], 2025-08-08) | [M] |
| Sometimes neither partial nor stop move | «من نه سیو سود نی کنم نه استاپ جابهجا می کنم» (27196 [ctx], 2026-08-19) | [D] |

Proposal (codable management family, parameter grid):
- A: TP1 at 2R closes f1 ∈ {0, 0.3, 0.35} and moves the stop to breakeven. Runner trails a swing-pivot stop (k ∈ {2, 3}) on the trigger TF, with a hard cap at {10R, 20R, 30R}.
- B: as A, plus a second partial f2 = 0.4 at 5R, keeping a 10% runner.
- C (RSI): no partial while RSI > 70 (long). Partial f ∈ {0.3, 0.5} on the RSI cross back below 70. Breakeven at 2R.
- D (momentum/LTF/counter-trend trades): fixed TP at 2R for the full size.
- Rule mapping: counter-trend, inside-range, weekend, or 15m trigger → D. With-trend 1H/4H → A/B/C.

---

## 8. Capital management (risk %, tiers, caps, leverage)

### 8.1 Risk per trade (evolution)
| Date | Statement | Tag |
|---|---|---|
| 2022-01 | VIP signals sized at 3% risk: «با ریسک ۳٪ مجموع میکنه ۱۰۲٪ ضرر» (8314 [ctx]). «سیگنال دادم تو vip با ریسک ۳٪» (9027 [ctx], 2022-03-27). The 1% vs 3% illustration is in 8526 | [M] |
| 2022-05 | «اگر بیشتر از ۳٪ سرمایه امروز وارد ضرر شدین حتما ویدیو مدیریت سرمایه… نگاه کنید» (9233 [ctx], 2022-05-11). Gloss: a day losing > 3% is a red flag. This is the only daily-loss reference in 2022–2026 | [O] |
| 2024-09 | His own position was meant to be 0.25% risk: «بجا ۰.۲۵٪ ریسک ۲.۵٪ ریسک شده بود» (18323 [ctx], 2024-09-18, "instead of 0.25% risk it became 2.5%" by mistake) | [M] |
| 2024-10 | «مدیریت سرمایه اینشکلی بود که ۱٪ سرمایه بخر من گفتم ۱٪ سرمایه ریسک کن» (18749 [ctx]). Gloss: risk 1% of capital (stop-based sizing), don't "buy with 1%" | [M] |
| 2025-06 | War/internet-outage regime: «ریسک ماکسیمم ۰.۲۵ ٪» (22639, 2025-06-15). Also «حجم ترید کم کنید ولی همراه باشید» | [M] |
| 2026-06 | Counter-trend max 0.25% (26593) | [M] |
| 2026-09 | «ما تلاش می‌کنیم با داشتن مدیریت سرمایه و حدضرر، همیشه کمتر از 1 تا 2 درصد ضرر کنیم» (27415, 2026-09-05). The day-5 video worked example: «با سرمایه ۱۰۰۰ دلاری و ریسک ۱٪» (27460 [ctx]) | [M] |

### 8.2 Risk tiers by setup quality
- «چطور ستاپ‌هات رو با استفاده از ژورنال به خیلی ریسکی، ریسکی، معمولی و سیف تقسیم کنی» (27460 [ctx], 2026-09-08). Gloss: four tiers from the journal: very risky, risky, normal, safe. The exact percentages are only in the video. **[O]**
- He keeps a minimum risk unit: «خودِ پوزیشن هم چون آخر هفته ایم جزو پوزیشن های ریسکی حساب میشه و من با مینیموم ریسکی که توی استراتژیم دارم این پوزیشن رو باز میکنم» (26264, 2026-05-16). **[O]**
- Repeated triggers for "low risk": a risky/early trigger, inside a box, a single-touch level, weekend/Saturday, a low-volume breakout, emotional/news-driven markets («با شکست 80418 با ریسک کم پوزیشن باز میکنیم چون احتمال حرکت هیجانی زیاده», 26122), a coin moving apart from the market (25852 [ctx]), and Dow trend change not yet confirmed («تغییر روند هنوز صورت نگرفته؛ به همین دلیل تریگرهایی که داریم ریسکی ان و باید با ریسک کم پوزیشن باز کنیم», 25840). **[O]**
- He lowered risk when the market gave no confident entries: «ریسکمو کم کرده بودم چون مارکت ورود مطمعن نمیداد» (13834 [ctx], 2023-09-21). **[O]**

Proposal (tier → risk % mapping, my parameterisation, not stated by the channel):
safe = R, normal = 0.75R, risky = 0.5R, very risky = 0.25R, with R ∈ {0.5%, 1%}. Alternative absolute set:
{1%, 0.5%, 0.25%, 0.25%}, which matches the explicit 0.25% "minimum/counter-trend" and the 1% example. Classification:
start at safe and drop one tier per flag: counter-trend (force very risky / 0.25%), inside range, first-touch or single-touch
level, weekend, no volume confirmation, risky/early trigger (not main), trigger TF = 15m. Floor at very risky.

### 8.3 Exposure caps and number of positions
- Don't open on all coins at once. If several, split risk: «حواستون باشه که با همه کوین ها همزمان پوزیشن باز نکنید و اگر هم میخواید رو چندتا کوین پوزیشن باز کنید، ریسکتون رو پخش کنید» (25768 [ctx], 2026-04-06). **[O]** Proposal: total open risk cap ∈ {1%, 2%, 3%}, divided among concurrent trades. Max concurrent ∈ {2, 3, 5}.
- He typically has a few positions at once («اگه مثل من از قبل 2 تا پوزیشن فعال دارید», 26173 [ctx]. «رو اکانت اصلی ۲ تا پوزیشن دارم», 27199 [ctx]). **[O]**
- Spot: notional per coin ≤ 5% of capital (stricter rule), or ≤ 10–20% (normal): «هیچ‌وقت نباید بیشتر از 5 درصد سرمایه در یک کوین درگیر باشه» … «اجازه نمیده که بیشتر از 10 تا 20 درصد سرمایه رو وارد یک کوین کنیم» (27415, 2026-09-05). **[M]**
- High-risk off-strategy exposure (private sales) ≤ 1% of capital (16601 [ctx], 2024-06-16). **[M]**

### 8.4 Leverage
- Leverage is a capital-management tool: it keeps less money on the exchange. Risk still comes from stop-based size: «بهترین استفاده از لورج برای ما مدیریت سرمایه حجم فیوچرز هست ! یعنی دیگه نیاز نیست کل سرمایه ترید خودمون رو وارد صرافی کنیم» (23346, 2025-08-19). **[M]** (For the backtest, leverage is irrelevant beyond margin and liquidation checks. Size = risk$ / stop distance.)
- «ماکسیمم ۵۰۰۰ تا میبری صرافی با لورج ۲۰ راحت مدیریت سرمایه می کنی» (11543 [ctx], 2023-04-07). **[M]** (an exchange-balance practice)
- Examples quote returns at leverage 10 and 30 (20794, 21174). These are illustrative, not rules. **[D]**
- Use isolated margin: implied by the warnings about cross-margin wipe-outs (13960, futures vs spot article). **[O]**

### 8.5 Loss limits / pauses
- No daily or monthly loss limit and no "pause after N losses" appears in 2022–2026 text. The only related items: the 3% daily-loss red flag (9233, 2022), «میتونید تا ۴ تا استاپ راحت ترید کنید» (24732 [ctx], 2025-11-19, about a bonus balance covering 4 losses), the expectation of 2 stops before the setup (23118), and up to 5 stops on a major level (27469). **[O]** Proposal: keep the 2021 rule as a testable option: after L consecutive losses, pause H hours. Grid: L ∈ {3, 4, 5}; H ∈ {0, 24}. Also a daily loss stop at {2%, 3%}.

---

## 9. Timeframes and multi-timeframe workflow
- Top-down: weekly → daily → 4H, with triggers on 4H/1H (and 15m for scalps). Every 2026 BTC post follows «داخل تایم فریم هفتگی… در تایم فریم روزانه… و در نهایت میرسیم به 4 ساعته» (25418, 25436). Pre-trade routine: «چک کردن تایم‌فریم‌های بالا تا پایین» (23061). **[O]**
- HTF veto on an LTF trigger: he skipped a 1H H&S long «چون توی تایم فریم های بالاتر مثل 4ساعته، این حرکت صعودی میتونه یه سقف پایینتری نسبت به 79285 بزنه» (26050, 2026-04-29). **[O]** Proposal: an LTF long requires the HTF (×4 timeframe) trend ≠ down (§2.1).
- LTF breakout of an HTF level: a daily level means a higher chance of LTF false stops (27466, 27577). Use an earlier trigger or wider stop. **[O]**
- If the analysis TF stop is too large, take the trigger on a lower TF (27087). **[O]**
- Spot uses 1D/1W levels. Futures use 4H/1H/15m. The spot trigger sits higher; futures take an earlier trigger: «تریگر خرید اسپات همچنان بالای 110280 هست اما برای فیوچرز زودتر تریگر میگیرم» (22732). **[O]**

Proposal grid: (HTF, trigger TF) ∈ {(1D, 4H), (4H, 1H), (1H, 15m)}.

---

## 10. Sessions, weekdays, weekends, news
- **New York open brings volume, so wait for it on low-volume days**: «احتمال اینکه از تایم نیویورک امروز یا شروع کندل هفتگی جدید، حجم وارد مارکت بشه زیاده» (25999, 2026-04-26). Also 25744 [ctx]. He sits at the chart 1h before the US market opens: «۱ ساعت قبل از باز شدن مارکت آمریکا بشینم پشت چارت» (23079 [ctx], 2025-07-28). Daily analyses are posted at NY time (24253 [ctx]). **[O]** Proposal: session filter. Allow entries only between NY open − 1h and NY open + h. Grid: h ∈ {2, 4, 8}, versus no filter. (NY open = 13:30 UTC in summer, 14:30 UTC in winter, as the US equity open.)
- **Saturday/weekend = low volume, riskier, lower risk**: «امروز شنبه ست و حجم مارکت طبیعیه که کم باش» (25834). «این تریگر، ریسکی تر… چون هم شنبه ست و حجم کمه» (25834). Weekend breakouts are OK only with a volume increase (25981). **[M]** for the day-of-week flag.
- Crypto weekend gap risk is not discussed. The forex weekend rules (13043, 2023-07-27): close trades before the weekend, no new LTF trades Friday afternoon, prefer 4H/1D, keep the stop beyond the average weekly gap. **[M]** (forex only)
- News/war: reduce risk to 0.25%, stops always on the exchange (22639, 22610 [ctx]). «به هیچ عنوان پوزیشنی باز نکنید» during extreme disruption (22613 [ctx]). Emotional, news-driven moves → low risk (26122). **[O]** Proposal: a high-impact news blackout (FOMC/CPI) of ±1h. On/off.
- A weekly-candle open often brings momentum (25712 [ctx], 25999). **[D]**

---

## 11. Routine, watchlist, psychology → hard constraints

| Rule | Evidence | Constraint proposal |
|---|---|---|
| Weekly watchlist on Sunday: top-100 coins on CoinMarketCap, filter by BTC-pair trend aligned with the BTC/BTC.D view, set alarms on USDT charts. Max ~2h of trading per day | «کوین مارکت کپ باز کنید و صرفا ۱۰۰ تا کوین اول چک کنید… کوین هایی با پیر بیت کوین صعودی… بعدش چارت های تتر شون چک می کنیم و آلارم ها رو ست می کنیم» (22542, 2025-06-08) | Universe = top-100 by market cap (point-in-time). Weekly rebalance Sunday. Rank by coin/BTC trend [O] |
| Rule 1: no rushing. Trade only with a checklist | «تا وقتی چک لیست نداری پوزیشن باز کردن خیانت به روح و روانته» (25586 [ctx], 2026-02-21) | All entries must pass the coded checklist (context + trigger + volume + RSI + stop size + R:R) [M] |
| Rule 2: boring markets matter most | 25590 [ctx] | [D] |
| Rule 3: no routine, no edge | 25595 [ctx] | [D] |
| Rule 4: no journaling/chart prep → no trade | «یا حال همشو داری یا هیچ کدوم» (25600 [ctx], 2026-02-24) | [D] (live only) |
| Rule 5: no prediction; plan for every scenario | 25621 [ctx]. Also «پیش‌بینی ممنوع» (22713). Scenario format with both a long and a short trigger in every post (15914, 2024-04-27, four range scenarios incl. fakes) | Always place both side triggers. Let price choose [M] |
| Rule 6: stop too big → wait | 25630 | §2.4 [O] |
| Rule 7: don't be the liquidity taker that moves the market; enter after the big liquidity is lifted | 25645 [ctx] (truncated) | [D] (order-book) |
| Wait for a reversal candle and confirmation at support, never "feel" a level will hold | «یک تریدر منتظر دیدن کندل بازگشتی میشه رو حمایت و تایید میگیره» (15729, 2024-03-31. Reposted 20509, 2025-02-07) | No limit orders at support. Confirmation-only entries [M] |
| Not trading every day/week is normal | «شما قرار نیست هروز ترید کنید حتی قرار نیست هر هفته ترید کنید» (10484, 2023-02-03) | No minimum trade frequency [M] |
| Priorities: 80% money management, 10% emotions, 10% TA | (10484) | — |
| Don't trade outside the strategy | «دلیلی نداره بیرون استراتژی تون ترید کنید» (10523, 2023-02-05). «هر پوزیشنی بیرون از استراتژی خودت ارزش این رو نداره که به استاپ لاس ختم بشه» (21060 [ctx]) | [M] |
| Missing a move is no reason to chase | «سود از دست رفته بهتر از دست دادن سرمایه» (25586). «بازار همیشه هست هیجانی نباشید دوباره ورود میده» (9215) | No late entries. Signal valid ≤ n bars after the trigger [O], n ∈ {1, 2} |
| Don't try to pick the bottom | «سعی نکنید کف بازار تشخیص بدین» (9215) | [M] (no counter-trend limit buys) |
| One focused hour a day | 22644 [ctx] | — |
| Journal everything (excel) | 8853, 10523, 23403 | Log all trades with tier tags (needed for §8.2) |

---

## 12. Evolution and contradictions vs. the 2021 education-channel rules

| 2021 rule | 2022–2026 evidence | Verdict |
|---|---|---|
| Max 3% risk per trade | 2022 VIP still 3% (8314, 9027). From 2024, 0.25% as his own base or minimum unit (18323), 1% as the teaching example (18749, 27460), "< 1–2% loss" (27415), 0.25% cap for counter-trend/war (26593, 22639) | **Tightened.** Test R ∈ {0.25, 0.5, 1}% with 3% as the legacy upper bound |
| Min R:R 2 crypto / 3 forex | Restated exactly (10710, 10711, 2023-02-18). Min 2R also for counter-trend shorts (26043) | **Unchanged** |
| +2R: close ~30% and stop to entry | 2022: 35% at 2R (8548). 2026: 30% on fresh trades + risk-free (27379). 40% at 5R (26181). Sometimes stop to entry with no partial (22992). Old positions get no partial (27379). RSI-OB hold rule overrides (27296) | **Mostly unchanged, more conditional.** Partial size and timing depend on momentum and position age |
| Indecision-candle stop-order trigger | Evolved into the **کندل ستاپ**: stop-buy above the shadow, SL behind the candle, SMA7 (+SMA25) context (23522, 26143). The name «ایندیسیژن» survives only as a profit-save cue (12557) | **Evolved.** Same order mechanics, now MA-anchored |
| Break → pullback → volume trigger | Default is now a **direct breakout via stop orders** (23423, 20910), not waiting for the pullback. Pullback/candle-setup entries are fallbacks after a missed breakout (26252) and are "riskier" (26038). Volume confirmation is still required (25954) | **Contradiction.** Entry timing changed from pullback to breakout. Volume rule retained |
| 3-timeframe structure | Still W → D → 4H analysis with 4H/1H/15m triggers (25418, 26050) | **Unchanged** |
| 24h pause after 3 losses | Not found. Instead: expect 2 stops before the setup (23118), up to 5 stops on a big level (27469), and "trade 4 stops easily" on a bonus balance (24732) | **Not restated, possibly dropped.** Keep as an optional test |
| — (new) | RSI overbought = buy momentum (18749, 2024 onward). Custom RSI levels. Dominance regime filter. New-York volume timing. Weekend risk reduction. Four risk tiers. "Risky vs main trigger". Fake-breakout V setup. Touch counting. Order-book level adjustment | **New since 2022** |

Internal contradictions and tensions in 2022–2026:
1. **Breakout vs. pullback:** "all positions opened with stop-buy" (23423) vs. pullback/candle-setup entries recommended in many posts. Resolution in the text: breakout is primary, pullback is the fallback and lower tier.
2. **First touch:** "don't trade the first touch" (25840), yet XRP "6th touch" (27469) and BTC "try never to miss this break" (25869) imply trading every break of a major level. Resolution: the touch rule applies to risky LTF triggers. Major levels get a re-entry budget.
3. **Partial profits:** 30% fresh / 0% old (27379) vs. "40% at 5R" (26181) vs. "no partial, stop to entry" (22992) vs. "neither" (27196). Treat this as a parameter.
4. **RSI overbought:** it is an entry confirmation (long), and when price is already in overbought on the 4H, "we can't open in this TF" (26210 [ctx]), so drop to 1H. Both are consistent with "enter on the RSI break into OB, not while it is already extended".
5. **Risk %:** 1% example (27460) vs. 0.25% personal unit (18323) vs. "1–2% max loss" (27415). Use a tiered grid.
6. **Spot vs futures triggers differ** for the same coin (22732). The backtest must pick one instrument mode.

---

## 13. Proposed mechanical baseline (built only from the rules above; parameters to grid-search)

1. **Universe & regime:** top-100 coins (weekly). BTC.D regime (§2.3) chooses BTC vs. alts and the allowed direction.
2. **Trend filter:** Dow pivots on HTF (1D or 4H). Trade only in the HTF trend direction, except counter-trend at 0.25% risk with TP = 2R (or skip).
3. **Setups on trigger TF (4H/1H/15m):**
   (a) Breakout of the last swing pivot or box edge via a stop order.
   (b) Candle setup: SMA7 (+SMA25) pullback candle, buy-stop above the shadow, SL below the candle.
   (c) Fake-breakout V: reclaim, then break of the pre-breakdown swing high.
4. **Confirmations:** breakout-bar volume ≥ v·SMA20(vol) (proxy). RSI(14) crosses into > 70 for long / < 30 for short, or holds 50 (variant).
   No volume–price divergence. Not inside a range unless the risky tier applies. Not the first touch for LTF triggers.
5. **Vetoes:** stop distance > s·ATR. Next HTF resistance closer than 2R. Strong resistance or SMA99 overhead (variant). Signal older than n bars.
6. **Risk:** tier the trade (safe / normal / risky / very risky) by the flags in §8.2 (counter-trend, range, weekend, first-touch, no volume, risky trigger, 15m). Risk = tier × R. Total open-risk cap. Spot per-coin notional ≤ 5–20%.
7. **Management:** 2R partial (30–35%) + breakeven. RSI-OB hold (no partial while RSI > 70, save on the exit). Optional 40% at 5R. 10% runner trailed by swing pivots. Hard close at 20–30R. Exit on a close beyond the last opposite swing (Dow).
8. **Time filters:** optional NY-session window. Weekend → down one tier (or require volume).

---

## Summary: the most important codable rules

1. **Entry = break of a pre-drawn trigger level, executed with a stop-buy/stop-sell order, never a market order** (23423, 20910). The trigger is a swing high/low, a box edge or a trendline-break level on 4H/1H/15m.
2. **Trend-aligned only. Counter-trend trades are capped at 0.25% risk** with a small stop and fast partial, minimum 2R (27331, 26593, 26043).
3. **Dow structure decides direction and invalidation:** no longs until price breaks the high that created the last lower low (25436). Reversal confirmed by HH+HL beyond the trigger (26627). Exit or trend-change warning on an equal or lower high (22838).
4. **Candle setup (کندل ستاپ):** SMA7 context (SMA25 alignment raises win rate). Buy-stop above the candle's shadow, stop behind the candle (23522, 26143). Used early, before whale breakouts, and on pullbacks to SMA 7/25 (riskier).
5. **Fake-breakout (V) setup:** a close beyond support or resistance, then a reclaim. The trigger is the swing high (or low) made before the false break (21119). A fake of one box edge raises the odds of breaking the other edge (25436).
6. **Range box:** no trading inside, or only risky trades with low risk and a fast partial (27029, 25702). Trade the box breakout with SL at the opposite edge (22838). In long ranges, trade the inner small box at lower risk and add on the main level break (22748). First target = one box height (25989).
7. **Volume gate:** a breakout needs rising volume. A low-volume or divergent breakout is likely fake, so skip it or cut risk (25954, 25981, 27050, 25955).
8. **RSI momentum (period not stated, assume 14):** entry into > 70 confirms longs and < 30 confirms shorts (18749, 26122, 27087). 50 is the momentum pivot (25955, 27041). Custom RSI swing levels act as triggers (25834, 25869). A price breakout without RSI follow-through is likely to fail (25920, 26125).
9. **RSI-based profit save:** no partial while RSI is in overbought; save when RSI exits it (27444, 27296). Shorts mirror this with oversold.
10. **R:R:** minimum 2R in crypto and 3R in forex (10710, 10711). Check that 2R is reachable before the next major resistance (25793). Close outright at 20–30R (10711).
11. **Management:** at 2R, save 30–35% and move the stop to breakeven (8548, 27379). Old positions take no partial (27379). At about 5R, save 40% and make it risk-free (26181). Keep a ~10% runner (26436). Trail by structure. Exit on a close below the last higher low (27565).
12. **Risk sizing:** risk is stop-based (18749). The example is 1% (27460), the personal minimum unit is 0.25% (18323, 26264), and the stated aim is to lose less than 1–2% per trade (27415). There are four tiers: very risky, risky, normal, safe (27460). Flags that lower the tier: counter-trend, inside a range, weekend, single or first touch, no volume, early or risky trigger, 15m. Split risk across concurrent trades (25768). Spot exposure is at most 5% (strict) or 10–20% (normal) of capital per coin (27415).
13. **Stop placed together with the entry, always a stop-market order; no stop means no trade** (22639, 22713, 25657). If the structural stop is too large, wait or drop a timeframe (25630, 27087).
14. **Touch and re-entry rules:** don't trade the first touch of a level on LTF triggers (25840). A major HTF level can deserve up to about 5 stop-outs, while a risky LTF trigger deserves about one (27469).
15. **Dominance regime:** BTC.D falling → long alts. BTC.D rising → BTC, or alts with a rising BTC pair. BTC.D rising while BTC falls → short alts (23029, 22732, 25418, 25911). No alt long without dominance confirmation (27711).
16. **Time filters:** Saturday/weekend volume is low, so trades are riskier and need a volume increase (25834, 25981, 26264). Volume tends to arrive at the NY open (25999). He prepares 1h before the US open (23079).
17. **Top-down timeframes:** W → D → 4H analysis, triggers on 4H/1H/15m. An HTF can veto an LTF trigger (26050). 15m trades: small stop, fast partial (26627).
18. **Not found in 2022–2026 text (keep only as optional tests):** the 24h pause after 3 losses, daily or monthly loss limits (only "a day losing > 3% is a red flag", 9233), Stoch RSI, volume MA, and any KBSM definition. The 410 image-only lesson posts from 2023 are unread and may hold more.
