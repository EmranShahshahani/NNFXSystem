# Trade City Pro Education: trading rules extracted for a mechanical backtest

Source: public Telegram channel "Trade City Pro Education", archived at
`data/cache/telegram/education.jsonl` (378 messages, ids 1–405). Post URL = `https://t.me/Tradecitypro_Education/<id>`.
I read all of it in chunks and checked it against `edu_key.txt`, which is a subset: every id in that file was covered.

Authors who sign posts: **Arshia Azizpour (ارشیا عزیزپور)**, the head trader who writes most of the rules. **Kian Zandi (کیان زندی)**, who writes the psychology posts and "his own strategy". **Yasi Naseri (یاسی ناصری)**, who writes the psychology and timeframe posts.

Before using these notes:
- **Dates.** Posts #4–#97 all carry the date 2021-07-25, even though the channel was created on 2021-07-18. This looks like a bulk import or forward date, so the true order within that block is the id order. Many posts were re-posted on 2021-09-06 with identical text: #162=#43, #166=#142, #167=#143, #169=#144, #170=#145, #171=#146, #172=#147, #173=#149, #176–179=#150–153, #180–181=#38–39, #222–225=#150–153. Below I cite the original id.
- **Content over time.** Rule-bearing text is concentrated in 2021-07-25 → 2021-10-24. After about #266 (2021-10-15) the channel is almost entirely **links to videos** (Aparat/YouTube): chart patterns, trend analysis, psychology, crypto games and NFTs. **Dow theory (7 parts), market phase (3 parts), chart patterns (V, H&S, double top/bottom, triangles, flags), multi-timeframe, stop-loss placement, save-profit, trend-analysis course: all of these are video-only, and their content is not in the archive.** I mark these below and do not infer their content.
- **Indicators.** No indicator settings appear anywhere in the text. Kian's strategy explicitly uses none. One analysis post mentions a "positive divergence on 1h" (#96) without naming the oscillator. Video #237 explains "the indicator under the chart", but its content is not in the archive.

Classification tags:
- **[M] mechanical:** can be coded as stated.
- **[O] operationalisable:** needs a definition we choose. I propose one and give a small parameter grid.
- **[D] discretionary:** cannot be coded faithfully. Optional proxy only.

---

## 1. Capital management (مدیریت سرمایه)

The channel puts capital management above everything else: «80%مدیریت سرمایه 10% کنترل بر روی احساسات 10% تحلیل تکنیکال» (#48, 2021-07-25: "80% money management, 10% emotional control, 10% technical analysis"). The main capital-management video (#31) and the journal/Excel video (#58, #59) are **video/file only**.

| # | Rule (Persian quote) | Post | English gloss | Tag |
|---|---|---|---|---|
| CM1 | «اجازه نداریم بیشتر از ۳٪ ریسک کنیم» … «بیشتر از ۳٪ اجازه ضرر رو کل سرمایه در یک ترید رو نداریم» | #50, 2021-07-25 | Max loss per trade = 3% of total equity. | M |
| CM2 | «در مدیریت سرمایه من اجازه ندارم بیشتر از ۳٪ سرمایه در هر ترید ضرر کنم» | #56, 2021-07-25 | Same 3% cap, restated. | M |
| CM3 | «با ریسک 3% ترید می کنم» | #144, 2021-08-26 | Arshia's standing risk is 3%. | M |
| CM4 | Position size worked examples: «استاپ ما نزدیک ۱.۳٪ بود … با لورج ۱۰ نزدیک ۳۰٪ سرمایه رو وارد پوزیشن کنیم» (#50); «حد ضرر این سیگنال ۰.۴٪ هست با ریسک ۳٪ تقریبا ۹۰٪ سرمایه … اگر لورج ۱۰ باشد» (#68); «با لورج ۱۰ … ۵۰٪ سرمایه رو وارد کردم» (#56) | #50, #56, #68 | Position sizing: margin fraction ≈ risk% / (stop% × leverage), i.e. notional = equity × risk / stop distance. Leverage only changes how much margin is used. | M (code `notional = equity*0.03/stop_pct`) |
| CM5 | «اگر در سیگنال اول ریسک ۳٪ باز کردین دیگر اجازه ندارین سیگنال دیگری را باز کنید» / «۱٪ ریسک برای لایت کوین پس می تونید مانا را با ۲٪ ریسک بگیرید» | #60, 2021-07-25 | **Total open risk is capped at 3%.** Concurrent trades split the 3% budget. | M |
| CM6 | «زمانی هست که سیگنال اول را ریسک فری کنید … حد ضرر بزارید روی نقطه ورود در این صورت می تونید سیگنال بعدی را هم با ۳٪ ریسک» / «یا ۳۳٪ پوزیشن را در سود یا نقطه ورود ببندین و سیگنال بعدی را با ۱٪ ریسک» | #60 | Exceptions to the cap. Once trade 1 has its SL at entry, its risk no longer counts and a new trade may take the full 3%. If 33% of trade 1 is closed instead, the new trade gets 1%. | M |
| CM7 | «اگر می ترسین ۳٪ سرمایه ضرر کنید ۱٪ درگیر کنید اگر ۱٪ هم می ترسین ۰.۵٪» | #264, 2021-10-13 | Later softening: 1% or 0.5% risk is fine and can be scaled up slowly. | M (grid: risk ∈ {0.5, 1, 2, 3}%) |
| CM8 | «اگر سرمایه تون ١٠٠$ هست و استاپتون ٢٠$ … منطقى نيست» / «٣$ حد ضرر … منطقى هست» | #265, 2021-10-14 (Yasi) | $3 of risk on a $100 account (3%) is reasonable. $20 (20%) is gambling. | M (consistent with 3%) |
| CM9 | «دلیل نمیشه که ریسک ترید.هارو بالاتر ببرید تا ضررتون رو یک شب جبران شه» | #38 | Never raise risk after drawdowns, i.e. no martingale. | M (fixed-fraction sizing) |
| CM10 | «تو بایننس گول نخورید بگید مهم نیست 50% ریزش کرد … فرقی با لیکویید شدن نداره» | #38 | A 50% spot drawdown is equivalent to liquidation, so spot positions need stops too. | M |
| CM11 | Leverage values used: 10 (#44, #50, #56, #68), 20 (#52, #68), 25 «با لورج بالاتری وارد ترید شدم ۲۵» (#53) | — | Futures with leverage 10–25. Leverage is an outcome of sizing, not a separate risk rule. | M (cap leverage ≤ 10/20/25; check stop is far from liquidation) |
| CM12 | «مثلا هر ماه نسبت به ماه قبل 5% فقط 5% سود کرده باشید این روتین رو برای 6 ماه حفظ کنید» | #38 | Monthly goal of +5% for 6 months. A benchmark, not an entry or exit rule. | D (reporting KPI) |
| CM13 | Profit distribution: «هر ماه 10% از سود رو پسنداز … نزدیک 60% سود در بالانس باقی میمونه» | #144 | Monthly withdrawal of about 40% of profits. | O (optional backtest variant: withdraw 40% of monthly profit) |
| CM14 | Spot alt-coin hygiene: «سعي كنين كوين هاي ١٠٠ تاي اول كوين ماركت كپ رو خريداري كنين» / shitcoins «١/١٠٠٠ سرمايتون» | #98, 2021-07-26 (Kian) | Universe filter: top-100 by market cap. Shitcoins get at most 0.1% of capital. | M (universe filter) |
| CM15 | «هرجایی بیشتر از ماهی ۳٪ سود میدادن فرار کنید» | #208 | Anti-scam heuristic for investment schemes, not a trading rule. | D |

**Contradictions in capital management**
- The 3% cap is broken in #52 («با لورج ۲۰ … کل سرمایه … ۴٪ کل سرمایه ضرر») and in #41, where the arithmetic implies about 3.6%. The authors treat "≈3%" loosely. → Code a hard 3% and test 1–3%.
- #44–45 runs **three positions at once** as a hedge (see §6) without saying how the 3% budget is split. #60 says the budget is shared. → Apply #60.

---

## 2. Risk-to-reward (ریسک به ریوارد)

| # | Rule | Post | Gloss | Tag |
|---|---|---|---|---|
| RR1 | «این سیگنال ها ریسک به ریوارد زیر ۱ دارند با این سیگنال ها ترید نکنید» | #34, 2021-07-25 | Do not trade below RR 1 (earliest, weakest version). | M |
| RR2 | «با سیگنال ها و تحلیل هایی که ریسک به ریوارد زیر ۲ دارند ترید نکنید» | #37 | **Minimum RR = 2.** This is the standing rule from here on. | M |
| RR3 | «به هیچ وجه … سیگنال هایی که ریسک به ریوارد زیر ۲ دارند ترید نکنید» | #70 | Restated firmly. | M |
| RR4 | «تارگت ۱ حد اقل ریسک به ریوارد ۲ داره» | #117, 2021-08-05 | **TP1 itself must be ≥ 2R.** The filter applies to the first target, not the last. | M |
| RR5 | «اگر مطمئن نبودید تریدی که می خواین انجام بدین ریسک به ریوارد مناسبی نداره هیچ پوزیشن باز نکنید» | #39 | If you cannot confirm RR ≥ 2, skip the trade. | M (skip if RR to first target < 2) |
| RR6 | «ریسکتون ۱ ریواردتون ۲ … ⁣این مینیمم ریسک به ریواردی هست که من برای ترید های خودم قائلم» | #151, 2021-08-27 | 1:2 is Arshia's personal minimum. Break-even win rate is 33%. | M |
| RR7 | «شاید از هر ۱۰۰ تا ترید یک ترید رو ریسک به ریوارد پایین تر ببندم که در اون مواقع همون لحظه ترید برعکس باز میکنم» | #151 | Rarely (about 1/100) a trade is closed below 2R, and only when he immediately opens the opposite trade, i.e. a reversal signal. | O (exit-on-opposite-signal → stop-and-reverse; optional) |
| RR8 | «در فارکس مینیمم ریسک به ریوارد من ۳ هستش» / «در کریپتو … اگر ریسک به ریوارد ۳ رو بخواد بده ریسک به ریوارد ۵ رو هم میده» | #152 | **Forex: minimum RR = 3.** Crypto: minimum 2. | M (min_RR: crypto 2, forex 3) |
| RR9 | «۱ … ۱ … مگر در بازار رنج که استراتژی مخصوص خودشون در بازار رنج دارند» | #151 | RR 1:1 is only for pros with a separate range strategy. No range strategy is given. | D |
| RR10 | «من رو ریسک به ریوارد ۲۰ یا ۳۰ بدون تفکر میبندم پوزیشن را» | #152 | **Hard take-profit for the runner at 20–30R.** | M (runner TP ∈ {20R, 30R, none}) |
| RR11 | «اکثرا در ریسک به ریوارد ۵ بسته میشن … ماهی ۲ الی ۳ بار … ۱۰ تا ۳۰» | #152 | Typical outcome distribution: most runners close around 5R, with 10–30R 2–3 times a month. Use as a sanity check on backtest output. | D (expectation) |
| RR12 | Self-reported win rate «وین ریت من از ۶۰ الی ۷۰ درصد» | #65 | Claimed 60–70%. A benchmark only, not verifiable here. | D |

---

## 3. Stop-loss (حد ضرر / استاپ لاس / sl)

| # | Rule | Post | Gloss | Tag |
|---|---|---|---|---|
| SL1 | «شما باید در ترید هاتون حد ضرر داشته باشید لطفا اینو به عنوان یک اصل قبول کنید» | #38 | Every trade has a stop. | M |
| SL2 | «منطقی باشد (حد ضرر 30%  کاملا اشتباه هست و همینطور حد ضرر 0.6%)» | #88, 2021-07-25 | Stop distance must be "logical": 30% is too wide and 0.6% too tight (crypto, intraday context). | O: reject if stop_pct > X or < Y. Grid: min ∈ {0.3, 0.6, 1.0}%, max ∈ {5, 10, 15}%, or express in ATR (0.5–3×ATR) |
| SL3 | «حد ضرر جایی باید گذاشته شود که فروشنده ها یا خریدار ها به راحتی حد ضرر شما رو فعال نکنند» | #88 | Place the stop where it is costly for the market to reach. | O (beyond a validated swing/zone + buffer) |
| SL4 | «حد ضرر شما باید در نزدیکی نقطه عطف باشه … اگر فعال شد قیمت مسیر حرکتش عوض شود» | #88 | Stop goes at the invalidation pivot: if hit, the structure has changed. | O (stop beyond the last swing low (long) / swing high (short), pivot length n ∈ {3, 5}) |
| SL5 | Example: the 2% stop is too close, «دومین حد ضرر که 4% بالا تر هستش حد ضرر عقلانی هست» (chart image) | #90 + photo #89 link | Prefer the stop beyond the structure (4%) over the nearby one (2%). | O |
| SL6 | Indecision trigger: «حد ضرر این کندل عموما زیر شدو خود کندل قرار میگیرد» | #85 | **Stop below the shadow (wick) of the indecision candle** (above it for shorts). | M |
| SL7 | Breakout/retest (تثبیت): «با استاپ زير شدو ي او كندل قبلي كه پولبك بوده» | #143, 2021-08-23 (Kian) | Stop below the wick of the pullback candle. | M |
| SL8 | Kian strategy: «استاپ هم زير اون كندل پر قدرت ميذارم» | #124, 2021-08-11 | Stop below the full-body breakout candle. Unclear whether at its low or its body. | O (low of candle; variant: 50% of body) |
| SL9 | «استاپ رو بايد بالاي شدو در يك ناحيه خوب حمايتي و يا مقاومتي گذاشته بشه … اگر استاپ هم بخواين بيارين تو سود باز بايد همراه اين ناحيه هاي درست شده بيارين پشت شدو هاي اونها» | #132, 2021-08-12 (Kian) | Stop beyond the wick of a good zone. **Trail the stop behind the wicks of newly formed zones.** | O (trailing stop = last confirmed pivot low − buffer) |
| SL10 | «استاپ مطمئن ميشه زير كف هايي كه ساخته شده (… زير شدو ها باشه يا كندل ها)، اين در صورتي هست كه كفى كه ساخته معتبر باشه» | #149, 2021-08-26 (Kian) | Stop or trail under valid higher lows, either the wick or the body (chart-dependent). | O (variant flag: wick vs body-low) |
| SL11 | «قبل از اينكه پوزيشني باز كنيد اول حد ضررتون رو مشخص كنيد،نه حد سودتون رو» | #265 (Yasi) | Define the stop before the target. In code: size from the stop. | M |
| SL12 | Stop-loss video «آموزش اینکه چطوری و کجا حد ضرر قرار بدین» | #238, 2021-09-21 | **Video only.** Content not in the archive. | — |

**Contradiction on stop width.** #88 calls a 0.6% stop illogical. Yet VIP examples use 0.2% (#52) and 0.4% (#68) stops, and VIP 15m signals have «حد ضرر شون زیر ۱٪» (#203, 2021-09-06). The 15m entry timeframe explains the difference: the stop width rule is relative to timeframe. → Express it in ATR of the entry timeframe instead of fixed percentages.

---

## 4. Entry triggers / setups (تریگر / ستاپ / استراتژی)

### 4.1 The official "strategy so far": two triggers (#87, 2021-07-25, Arshia)
> «از استراتژی ما تا الان فقط 2 تریگر برای سیستم معاملاتی داریم
> تریگر 1 — 1.خرید با کمک کندل ایندیسیژن بر روی حمایت 2.فروش با کمک کندل ایندیسیژن زیر مقاومت
> تریگر 2 — 1.فروش در صورت شکسته شدن حمایت(برای پوزیشن بهتر در پولبک) 2.خرید در صورت شکسته شدن مقاومت(برای پوزیشن بهتر در پولبک)»
> «به جز این حالت ها ما هیچ پوزیشن باز نمی کنیم … حتی شده برای 1 ماه ترید نمیکنیم»

Gloss: there are only two triggers. Trigger 1 is an indecision candle at support (long) or resistance (short). Trigger 2 is a break of S/R, entered on the pullback. Nothing else is traded, even if that means a month without a trade. **[M as a whitelist; components are O]**

The promised "personal strategy" of Arshia (#4: «در انتها استراتژی شخصی من قرار خواهد گرفت»; #311, 2021-11-28: «چارت پترن ها رو خوب ببینید بعدش از استراتژی خودم میتونم مطلب قرار بدم») **was never published in this channel.**

### 4.2 Trigger 1: indecision candle (کندل ایندیسیژن / «کندلی که تصمیم نگرفته»)
| # | Rule | Post | Gloss | Tag |
|---|---|---|---|---|
| T1a | Definition (support case): «فروشنده ها قیمت را تا محدوده حمایتی پایین اوردن … خریدار ها … قیمت به سمت بالا بازگرداندند … با سبز بسته شدن کندل و اون شدو ی بلند» | #81 | A candle that pushes into support, leaves a **long lower wick**, and **closes green**. The resistance case is mirrored. | O |
| T1b | «قوانین کندل ها فقط در نقاط مهم صدق می کند مثل: روی حمایت ، روی مقاومت ،روی روند … اگر نقاطی غیر از اینها بود اون کندل هیچ اهمیتی نداره» | #81 | It is valid only at S/R or on a trendline. | O (needs an S/R definition, §5) |
| T1c | «ما روی کندل ایندیسیژن هیچ ترید نمی کنیم … اوردر خرید خودمون بالای شدوی ایندیسیژن قرار میدیم» | #82 | Never enter on the candle itself. Place a **buy-stop above its high (upper wick)**. | M |
| T1d | «ما برای ترید منتظر بسته شدن کندل ایندیسیژن میمونیم … پوزیشن شورت خودون رو زیر شدو ایندیسیژن قرار میدیم» / «وقتی کندل بعدی از کندل ایندیسیژن پایینتر اومد … تریگرش می خوره» | #83 (resistance → short), #84 (support → long) | Wait for the candle to close. **Sell-stop below its low** (short at resistance) or buy-stop above its high (long at support). Fills when the *next* candle breaks it. | M |
| T1e | SL: «زیر شدو خود کندل» | #85 | Stop at the other extreme of the indecision candle. | M |
| T1f | Target: «در صورت برگشت قیمت به طور معمول تا اولین مقاومت قیمت بالا میرود» / «به طور معمول تا اولین حمایت میره» | #82 | TP = first opposing S/R. | O (nearest opposing zone, §5) |
| T1g | «در هر تایم فریمی نسبت به همون تایم فریم معتبر هستش ولی انتظار خودتون به اندازه تایم فریم باشه یعنی اگر در ۱۵ مین این کندل را دیدین انتظار حرکت ۱۰٪ نداشته باشید» | #85 | Works on any timeframe, but the expected move scales with the timeframe. | O (see TF5) |
| T1h | «یک تریدر منتظر دیدن کندل بازگشتی میشه رو حمایت و تایید میگیره» | #43 | General rule: wait for a reversal candle at support before buying. | O |
| T1i | Edge claim: «فقط فقط حمایت و مقاومت را بلد بودم و همین یدونه کندل … ماهی ۱۰ تا پوزیشن میداد این استراتژی که نزدیک ۳۰٪ سود» | #86 | Claimed about 10 trades/month and about 30%/month from S/R + indecision alone. | D (benchmark) |
| T1j | Indecision videos | #99, #100 | **Video only.** Chart images are tradingview links (#81–#84). | — |

**Proposed operational definition (indecision candle):**
- Long setup: lower wick ≥ `k_wick` × body and lower wick ≥ `w_frac` × range, close > open (green). Optionally require close in the upper `c_pos` of the range.
- Grid: `k_wick` ∈ {1.0, 1.5, 2.0}, `w_frac` ∈ {0.4, 0.5, 0.6}, `c_pos` ∈ {none, 0.5}.
- Must touch a support zone (low ≤ zone_top and close ≥ zone_bottom).
- Short setup: mirror at resistance. #83 does not require a red close for the short; test "any colour" vs "red".
- Order: stop order at high + tick (long), valid for `n_valid` ∈ {1, 2, 3} following candles, else cancel.
- SL: low − buffer (`buf` ∈ {0, 0.1, 0.25} × ATR14).
- TP1: next opposing zone. Skip the trade if (TP1 − entry)/(entry − SL) < 2 (RR4).

### 4.3 Trigger 2: break of S/R, entered on the pullback (شکست + پولبک / تثبیت)
| # | Rule | Post | Gloss | Tag |
|---|---|---|---|---|
| T2a | «فروش در صورت شکسته شدن حمایت(برای پوزیشن بهتر در پولبک)» | #87 | Short after support breaks, preferably on the pullback (long is mirrored). | O |
| T2b | «منظور از تثبيت دادن … شكست يك مقاومت يا يك حمايت استاتيك و يا دايناميك وقتي اتفاق ميفته منتظر باشيم پول بك به اون سطح داشته باشيم و بعد يه كندل خوب پر جون با حجم خوب به اون سمت ديده بشه … ميتونيم وارد پوزيشن بشيم با استاپ زير شدو ي او كندل قبلي كه پولبك بوده» | #143, 2021-08-23 (Kian) | **Confirmation (تثبیت): break → pullback to the broken level → strong, high-volume candle in the breakout direction → enter. Stop under the pullback candle's wick.** Static or dynamic levels, i.e. horizontal lines or trendlines. | O |
| T2c | Example (chart): «حمایت شکسته شده و پولبک زده و در محدوده پولبک کندل ایندیسیژن داریم با تریگر کندل ایندیسیژن وارد پوزیشن می شیم» | #90 | Combined T1+T2: an indecision candle in the pullback zone after a break is the entry. | O |
| T2d | Exception, entering on the break without a pullback: «صبر کردیم که قیمت به بالای مقاومت برسه و ما بالای مقاومت پوزیشن لانگ باز کردیم … چرا منتظر شکست مقاومت و پولبک نموندیم؟ چون … در تایم فریم ۱۵ دقیقه جلوی حرکت رو گرفته بود و موجب فشردگی قیمت شده بود» | #49 | After a long compression under resistance (15m), enter immediately above resistance (breakout stop order) instead of waiting for the pullback, because "the spring" releases with no pullback. | O (compression = N bars with range < X·ATR under the level) |
| T2e | «همه ي اين سوال ها جوابش كندل خوب با بادي خوب با حجم خوب هستش … هيچ ناحيه ي حمايتي و مقاومتي معتبر نيستند تا كندل خوبي در اون ناحيه ديده نشده» | #134, 2021-08-16 | No zone counts until a good candle (big body, good volume) confirms the reaction or break there. | O |
| T2f | Break/retest video «#پولبک #تریگر» S/R part 2 | #80 | **Video only.** #86 promised «تریگر های حمایت و مقاومت»; they appear only in the video. | — |

**Proposed operational definition ("good / full-body candle with good volume" = کندل فول بادی / پر جون با حجم خوب):**
- body/range ≥ `b` ∈ {0.6, 0.7, 0.8}.
- range ≥ `r` × ATR14, `r` ∈ {1.0, 1.25, 1.5}.
- volume ≥ `v` × SMA20(volume), `v` ∈ {1.2, 1.5, 2.0}.
- Breakout = close beyond the level by ≥ `e` × ATR, `e` ∈ {0, 0.1, 0.25}.
- Pullback = a later candle trades back within `p` × ATR of the level (`p` ∈ {0.25, 0.5}) without closing back through it by more than `q` × ATR. Allow `max_wait` ∈ {5, 10, 20} bars.

### 4.4 Kian Zandi's "own strategy" (price action: trendline + zone breakout), #124, 2021-08-11
> «خطوط حمايت و مقاومت رسم ميكنم و اون ها رو طبق برخورد هايي كه داشتند اعتبار سنجي ميكنم»
> «خطوط ترند هاي صعودي و نزولي ايم هم كه بشكنه … و از اون ناحيه مهم ام … هم بزنه بيرون با يه كندل فول بادي يه خوب و حجم خوب ، پوزيشنم رو به طرف بازار باز ميكنم»
> «تيپي هم يا كف اول يا سقف اول بر اساس سمت بازار ٣٠ ٪ خارج ميشم و استاپ نقطه ورود و تيپي ٢ بر اساس شرايط بازار»
> «استاپ هم زير اون كندل پر قدرت ميذارم … بدون استفاده از هيچ انديكاتور»

Rule structure:
- Zones are validated by their number of touches.
- Entry: a trendline break **and** a break out of the key zone by a full-body candle with good volume. Enter in the breakout direction.
- SL: under the power candle.
- TP1: the first prior swing high (long) or swing low (short). Close 30% there and move SL to entry.
- TP2: discretionary.
- The example chart is photo only (#125, #126).

Coding: **[O]**. Zone validation = touches ≥ `t` ∈ {2, 3}. Trendline = line through the last 2 pivot highs (for a long, a descending line) with pivot length `n` ∈ {3, 5}. TP2: trail per SL9, or fixed R ∈ {3, 5}.

### 4.5 Other entry filters
| # | Rule | Post | Gloss | Tag |
|---|---|---|---|---|
| E1 | «لطفا لطفا پیشواز پترن نرید … منتظر باشید پترن اتفاق بیفته تایید بده … خط گردن شیکست» | #103 | Never anticipate a pattern. Enter only after confirmation, e.g. the neckline break. | M (as a principle: entries only on a closed break) |
| E2 | «اگر كويني مثبت چند درصد رشد كرد بعد رشدش تازه نريم بخريمش» | #75 | Don't chase a coin after it has already pumped several %. | O (skip long if return over the last N bars > X%; N ∈ {6, 24} bars, X ∈ {5, 10, 20}%) |
| E3 | «هیچ وقت تکرار می کنم هیچوقت هیجانی وارد پوزیشن نشید» | #48 | No impulsive entries. | D (implicitly enforced by mechanical rules) |
| E4 | «به اخبار اصلا گوش نكنين و تكنيكال خودتون رو قوي كنين» (#75); news-trading avoidance video (#290) | #75 | Pure technicals. No news-based entries. | M (no news filter needed) |
| E5 | «سعي كنين از ماركت كمتر استفاده كنين» | #105, 2021-07-31 | Prefer limit orders because market orders pay higher fees. | M (fee model: maker for limit entries, taker for stop orders) |
| E6 | Alt rotation: «بيتكوين بعد صعود ميره تو اصلاح و رنج كه كه الت پارتي شروع ميشه» | #121, 2021-08-08 | When BTC pauses after a rally, look for lagging alts. | D (dominance video #259 is video only) |
| E7 | «یک سیگنال خريد لغو شده ميتوان يك سيگنال فروش … باشد» | #114 | A failed long signal can become a short signal (Excavo quote). | O (stop-and-reverse variant, cf. RR7) |

---

## 5. Support/resistance zones (حمایت/مقاومت, ناحیه‌های حمایتی/مقاومتی) and timeframes

| # | Rule | Post | Gloss | Tag |
|---|---|---|---|---|
| Z1 | «حمایت و مقاومت … یکی از اسون ترین و هم چنین پر کاربرد ترین ابزار های ترید» / «همیشه باید حمایت و مقاومت ها رو داشته باشید. همیشه باید خط روند های جدید بکشید» | #39, #48 | S/R and trendlines are the core tools. | O |
| Z2 | «ناحيه هاي حمايتي و مقاومتي … از تايم فريم هاي بالا به پايين بياين» / «مقاومت ها و حمايت ها تو تايم فريم هاي بالا تر بسيار معتبر تر هستند» | #142, 2021-08-23 | Draw zones from the higher timeframes down. Higher-timeframe zones are stronger. | O (weight zones by source TF; use only zones from TF ≥ analysis TF) |
| Z3 | «چارت تون پر از اين حمايت مقاومت ها باشه از ماهانه تا ١٥ دقيقه» | #142 | Zones from monthly down to 15m. | O |
| Z4 | Zone validity by touches (#124); by a confirming candle (#134) | — | See §4.3–4.4. | O |
| Z5 | S/R videos parts 1 and 2 | #77, #80 | **Video only.** | — |

**Proposed S/R zone construction:**
- Pivot highs/lows with lookback `n` ∈ {3, 5, 10} on the "analysis" TF and the higher TF.
- Cluster pivots within `w` × ATR (`w` ∈ {0.25, 0.5}).
- Zone valid if touches ≥ `t` ∈ {2, 3}.
- A zone flips role after a confirmed break (T2).

### Timeframes (تایم فریم‌ها)
| # | Rule | Post | Gloss | Tag |
|---|---|---|---|---|
| TF1 | «هر كسي ٣ تايم فريم رو بايد براي خودش مشخص كنه ، يك تايم فريم ديد بزرگ … تايم فريم بعدي تحليل روش انجام ميشه … و … كوچيك ترين … نقطه ورود» | #127, 2021-08-11 (Kian) | Three timeframes: big-picture, analysis (zones), and entry. | M |
| TF2 | «مثلا تايم فريم ١ روز - ٤ ساعت - ١ ساعت . يا ٤ ساعت - ١ ساعت - ٣٠ مين . و يا ١ ساعت - ٣٠ مين - ١٥ مين» | #127 | Allowed triads: (1D, 4H, 1H), (4H, 1H, 30m), (1H, 30m, 15m). | M (grid over these 3 triads) |
| TF3 | «دوستاني كه اسپات كار ميكنند تايم فريم ماهانه و هفتگي روزانه بايد معيارشون باشه» | #127 | Spot uses (1M, 1W, 1D). | M |
| TF4 | «بيشتر از اون ٣ تا رو ديگه چك نكنين … اگر تايم نقطه ورودتون ١٥ مين هست ديگه نرين تو ٥ مين و ١ مين» | #127 | Never look below the entry TF. | M |
| TF5 | «اگر تو ٤ ساعت رو يك كندل فول بادي ورود كردين توقع تون اندازه ٢ تا ٤ ساعت خوب باشه نهايتا … اگر ٣٠ مين ورود كردين اندازه ٢،٣ تا ٣٠ مين توقع داشته باشين … البته بازار گاوي و خرسي باشه داستان فرق ميكنه» | #127 | In a normal market, expect a move worth about 2–4 entry-TF candles, so don't set "space" targets. Bull and bear markets are exceptions. | O (cap TP at `m` × average candle range of the entry TF, `m` ∈ {2, 3, 4}; or a time stop of `m` ∈ {4, 8, 12} bars; disable in trending regime) |
| TF6 | «هرچي تايم فريم كوچيك تر بشه،ريسك بيشترى داره،چون شكست هاي فيك توش بيشتر هست» | #273, 2021-10-24 (Yasi) | Lower timeframes have more fake breakouts. | D (an argument for higher TF / confirmation) |
| TF7 | Arshia's own trading goes down to 1m (#202: «تا تایم فریم ۱ دقیقه هم پایین میاد»). VIP signals are 15m, 1H, 4H and daily (#203). | — | Context only. | — |
| TF8 | Multi-timeframe video | #159 | **Video only.** | — |

---

## 6. Position management (ریسک فری, سیو سود, پله‌ای)

«مديريت پوزيشن هست نه ورود به يه پوزيشن» (#110, 2021-08-02, Kian: "it's position management, not entry"). The position-management and save-profit videos (#136/#161, #276) are video only.

| # | Rule | Post | Gloss | Tag |
|---|---|---|---|---|
| PM1 | «من خودم در ریسک به ریوارد ۲ فقط ۳۰٪ پوزیشن را میبندم و حد ضرر را میارم نقطه ورود» | #70 | **At +2R: close 30%, move SL to entry (risk-free).** This is the core management rule. | M |
| PM2 | «تارگت ۱ ما الان ریسک به ریواردش نزدیک ۴ هست ولی روی ریسک به ریوارد ۲ خودم اعلام کردم ۳۰٪ پوزیشن ببندن و حد ضرر بزارند نقطه ورود» | #117 | Same rule. The partial is taken at 2R even when TP1 is further away. | M |
| PM3 | «اکثرا روی ریسک به ریوارد ۲ نزدیک ۳۰ الی ۴۰٪ پوزیشن بسته میشه و ما بقیشو برای ریسک به ریوارد های بالاتر باز نگه میداریم» | #203, 2021-09-06 | Partial of 30–40% at 2R. The rest runs. | M (grid: partial ∈ {30, 33, 40}%) |
| PM4 | VIP signal management: «تارگت ۱ نزدیک ۳۳٪ ببندین و حد ضرر بزارین نقطه ورود ، تارگت ۲ نبندین اصلا ، تارگت ۳ کلا ۳۰٪ باز نگه دارین» | #203 | TP1: close 33% and SL → BE. TP2: close nothing. TP3: keep 30% open, i.e. close about 37% at TP3. | M (alternative ladder) |
| PM5 | «۳۰٪ پوزیشن را در ریسک به ریوارد ۵ بستیم و حد ضرر گزاشتیم روی نقطه ورود … بقیه پوزیشن باز نگه داشتیم … ریسک به ریوارد ۳۵» | #68 | Example: 30% at 5R plus BE, runner closed at 35R. | D (example) |
| PM6 | «ماکسیمم کاری که می تونید بکنید این هستش که حد ضرر بزارین روی نقطه ورود و منتظر تارگت خودتون با ریسک به ریوارد ۲ باشید» / «نباید زود تر از موعد پوزیشن خودتون رو ببندین» | #47 | **Do not close before target.** The only allowed pre-target action is moving SL to entry. | M (no discretionary early exit) |
| PM7 | «بعد از سید سود رو ریسک به ریوارد ۲ و ریسک فری کردن با دنبال کردن بازار و جابه جا کردن حد ضرر ریسک به ریوارد های ۱۰ ۲۰ ۳۰ میگیرم» | #152 | After the 2R partial and BE, trail the stop to catch 10–30R. | O (trail = SL9 pivot trail; variants: ATR chandelier k ∈ {2, 3}) |
| PM8 | «تو بازار گاوي … و بازار خرسي … فقط سيو سود كنين و استاپ رو رو نقطه ورود بگذارين و رهاش كنين» | #129, 2021-08-11 | In strong trending markets: take partial profit, SL at entry, let it run. | O (regime filter, e.g. price vs. EMA200 on HTF plus ADX > 25) |
| PM9 | Save-profit (سیو سود): «وقتي داريم ميريم بالا يه كف و سقف بالا تر ميزنيم … توى سقف بالاترى كه زديم يه مقدار سيو سود ميكنيم،كه وقتى ميخواد بازار بره يه اصلاح … تو اون كف پايينى باز يه مقدار به پوزيشن اضافه ميكنيم» | #149, 2021-08-26 (Kian) | In a long: scale out a bit at each new higher high and scale back in at the next higher low (pyramid/rotation). | O (fraction per step ∈ {10, 20}%) |
| PM10 | «تو ريسك به ريوارد ٢ يه مقدار از پوزيشن رو سيو سود كنيد … براساس استراتژي خودتون» | #149 | Alternative: partial at 2R, size left to you. | M (= PM1) |
| PM11 | «اون ارز داره ميره بخوره به يه مقاومت و … نميدونيد قدرت بازار … پس اينجا بايد يه مقدارى سيو سود انجام بديد» | #149 | Take a partial when price approaches the next opposing zone. | O (partial when price is within `d` × ATR of the next zone, `d` ∈ {0.25, 0.5}) |
| PM12 | Staircase buying in spot (خرید پله‌ای): «اصلا تو بازار نزولي كه ما خريد نميكنيم منظور تو بازار صعودي هست اون هم با استاپ لاس» / «حد ضرر ١٠ درصد اسپاتي» / «بعد از هر اصلاح يه خريد در كف جديد مي كنيم … استاپ هم كه همراه خريد پله مياريم بالا» / exit «در سقف اول يه پله و سقف دوم … كل سرمايه رو خارج ميكنيم» | #145, 2021-08-26 (Kian) | Spot, uptrend only. Split capital into tranches. Buy the first tranche with a 10% stop. Add a tranche at each new higher low after a correction and raise the stop each time. Exit stepwise once structure turns: sell one tranche at the first lower high and everything at the second lower high. | O (tranches ∈ {3, 4, 5}; uptrend = HH/HL by pivots n ∈ {5, 10} on 1D) |
| PM13 | Closing about 80% of shorts at a strong support: «۸۰٪ پوزیشن های شورت خودمو بستم … محدوده حمایتی قوی» | #96 (analysis) | Example of a large partial at a strong HTF zone. | D |

**Contradictions in position management**
- PM6 says never close before target, yet PM9/PM11 tell you to take partial profit when approaching resistance. → Implement PM1 as the base and PM11 as an optional variant.
- TF5 caps expectations at 2–4 entry candles, while PM7/RR10 let runners go to 10–30R. TF5 itself exempts bull and bear markets, and PM8 says let it run in those. → Use a regime switch: in the normal regime cap TP per TF5; in the trending regime use the runner and trail.
- Partial size drifts between sources: 30% (#70, #117), 33% (#60, #203), 30–40% (#203).

---

## 7. Hedging (پوشش ریسک), an occasional technique

| # | Rule | Post | Gloss | Tag |
|---|---|---|---|---|
| H1 | «۲ تا سیگنال لانگ دادیم و یه سیگنال شورت به صورت همزمان … چون حداقل ریسک به ریواردی که ترید میکنیم ۲ هست باعث میشد که ضرر اون ۲ تا آلت کوین پوشش داده بشه» | #44 | When going long alts **before** a resistance break, based only on trend strength, also short BTC as a hedge: 2 alt longs plus 1 BTC short. | O |
| H2 | «قبل از شکست مقاومت و فقط بر پایه قدرت روند درحال وارد شدن به پوزیشن بودیم نیاز بود که ریسک … به مینیمم … تبدیل کنیم» / «اگر تحلیلمون بر اساس ریزش بود … ۲ تا پوزیشن شورت و یک پوزیشن لانگ» | #45 | Use the hedge only for pre-breakout (anticipatory) entries. A bearish view mirrors it: 2 shorts plus 1 long. | O |
| H3 | «توجه کنید اینکار نیاز به تجربه خیلی زیاد … فقط روی کاغذ برای خودتون انجام بدین» | #45 | Advanced. Paper-trade only. | D |
| H4 | «ایندفعه بیت در حال رنج زدن بود و هیچ روند خاصی نداشت که من بتونم حد ضرر درست براش تعیین کنم … توانایی پوشش ریسک نداشتیم» → wait for the break | #49 | No hedge when BTC is ranging. In that case wait for an actual break. | O |

Recommendation: exclude hedging from the first backtest. It conflicts with E1 and T2, which say not to enter before the break.

---

## 8. Range / fake breakouts / stop hunting (رنج, فیک, استاپ هانتینگ)

| # | Rule | Post | Gloss | Tag |
|---|---|---|---|---|
| R1 | «وقتي بازار يه جا گير ميكنه تو يه باكس … هم بالاي اون ناحيه كلي استاپ هست … يك بار … از بالا ميزنه … دوباره بر ميگرده … اين قدر ادامه پيدا ميكنه تا قدرت يكي بيشتر بشه كه اون وقت حركت شارپي خواهد بود» | #132 | In a box range, both sides get stop-hunted repeatedly until one side wins and a sharp move follows. | D |
| R2 | «وقتى بازار ميوفته توى يه باكس رنج احتمال اينكه از هر طرف بشكونه و بعدش حركت شارپي داشته باشيم خيلي زياده … زير اون ناحيه … كندل بستيم ولى نريخت و در اصطلاح فيك اوت كرد» / «وقتي بازار يه جا گير ميكنه حواستون بيشتر باشه» | #147, 2021-08-26 | Inside ranges even a candle close beyond the box can be a fake-out. Be extra careful. | O (in a detected range, require a pullback confirmation per T2b rather than a close-only break; or skip ranges) |
| R3 | «وقتی این ۲ تا کندل قبل از کندل آخر دیدیم ازون تایم فریم دور میشیم و در اون تایم فریم ترید نمیکنیم» | #146 (photo) | When a specific two-candle stop-hunt pattern appears, stop trading that TF. **The pattern is only in the photo.** It may be two opposite long-wick candles; that reading is unconfirmed. | D (could proxy: two consecutive candles with wicks > X·ATR on both sides → pause TF for N bars) |
| R4 | «فعلا پوزیشن باز نمیکنم تا فردا تشخیص بدم که بازار قراره رنج بشه برای چند روز یا روند خواهیم داشت» | #96 | Do not trade while undecided between range and trend. | O (regime filter) |
| R5 | Range/stop-hunt video | #174 | **Video only.** | — |

---

## 9. Dow theory, market phase, chart patterns, trend analysis: video only

- **Dow theory (داو جونز / داو تئوری), 7 videos:** #107, #108, #118, #120, #123, #128, #133 (2021-08-01 → 08-16). Text only says: «داو تئوری شما رو ازین مشکلات نجات میده» for closing early, stop placement and getting excited (#119). After the videos: «خودتون باید بتونید … توی فیوچرز پوزیشن باز کنید تارگت در بیارین حد ضرر در بیارین» (#133). **No rules are in the text.** A standard Dow implementation (HH/HL vs LH/LL by pivots) would be *our* assumption, consistent with #145 and #149, which use higher highs/lows.
- **Market phase (مارکت فیز), 3 videos:** #239, #252, #257. «داو تئوری صرفا ۱ بخش از ۹ بخش مارکت فیز بود» (#239). No rules in the text.
- **Chart patterns:** episode 0 (#266), V pattern (#272), head & shoulders (#277), double top/bottom (#287), triangles (#300), flags (#309), plus #330 and #337 (untitled). All are **video links only**. The only text rule is E1 (#103): wait for confirmation, i.e. the neckline break.
- **Trend analysis course (ترند آنالیز):** #356–#359 (2022-01-15), video only.
- **Dominance (BTC.D, TOTAL2, USDT.D):** #259 text only lists the three series. «می تونید زمان شروع شدن آلت سیزن ها را تشخیص بدین»: video only.

---

## 10. Psychology rules that become hard constraints

| # | Rule | Post | Gloss | Tag |
|---|---|---|---|---|
| P1 | «بعد از ۳ تا حد ضرر باید حداقل ۲۴ ساعت از بازار فاصله بگیرم» | #65, 2021-07-25 | **After 3 stop-losses, pause ≥ 24 h.** The text does not say whether they must be consecutive; the context is three VIP losses in a row. | M (circuit breaker: after 3 consecutive losses, no new entries for 24h. Variants: 3 losses within a rolling 24h; pause ∈ {24, 48}h) |
| P2 | «revenge trade … بزرگترین اشتباه … پس من ترید نمیکنم حتی اگر بازار تمام نکات استراتژی من را داشته باشه» | #65 | No revenge trades. The cooldown overrides valid signals. | M (part of P1) |
| P3 | «بعد از ضرر و سود زياد يك هفته كار نكنين» | #64 (Kian) | After a large loss **or** a large win, pause for one week. | O (large = single-trade PnL ≥ `X`% of equity, X ∈ {5, 10}%, or ≥ `k`R, k ∈ {5, 10}; pause 7 days) |
| P4 | «شما قرار نیست هروز ترید کنید حتی قرار نیست هر هفته ترید کنید» | #48 | Trading every day or every week is not required. | D (no minimum-activity rule; supports strict filters) |
| P5 | «دلیلی نداره هروز ترید کنیم … مخصوصا در بازاری که شرایطش معلوم نیست» | #227, 2021-09-08 | Skip unclear markets even when 15m signals fire everywhere. | O (regime filter, cf. R4) |
| P6 | «به جز این حالت ها ما هیچ پوزیشن باز نمی کنیم … حتی شده برای 1 ماه ترید نمیکنیم» | #87 | Setup whitelist only. | M |
| P7 | «اگه حال روحي تون خراب باشه … فقط با ضرر همراه ميشه» / «صبح ها و شب ها كه تازه از خواب بيدار شدن و دارند ميخوابند» | #267, 2021-10-16 (Kian) | Don't trade in a bad mood or right after waking or before sleep. | D (could proxy with a session filter; nothing concrete in the text) |
| P8 | «اگه موقعيت تريد از دست رفت ولش كنيد» | #267 | If an entry was missed, don't chase it. | M (stop order valid only for `n_valid` bars, cf. T1) |
| P9 | «امان از انتقام … از يه جهت مثلا فقط لانگ» | #267 | No revenge in one direction, e.g. insisting on longs after the market turned short. | O (after P1 trigger, optionally block same-direction trades longer) |
| P10 | «استراتژی تون رو تو دمو امتحان كنين و بعد اگه سود ده بود فقط طبق اون عمل كنين … نه … بازار خوبه ديگه اينجا اهرم مون رو بالا ببريم» | #101, 2021-07-29 | Demo-test first. Then follow the rules exactly, with no ad-hoc leverage increases. | M (fixed parameters) |
| P11 | «ریسک به ریوارد برای 100 ترید انجام بدین نه 5 ترید» / «برای 100 تا ترید … با مدیریت سرمایه ترید کنید» | #39 | Judge the system over 100+ trades. | M (evaluation: minimum sample of 100 trades) |
| P12 | «اگر با ریسک به ریوارد ۲ ۷ بار حد ضرر خوردین … کافیه ۳ دفعه سود کنید» | #264 | Accept losing streaks. | D |
| P13 | Journal: «اگر تنبلی کنید و ژورنال پر نکنید هیچوقت به موفقیت نخواهید رسید» | #58 | Keep a trade journal. The Excel file is not in the archive. | M (trade log output) |
| P14 | Watchlist size: Arshia went from 70 to 20 coins and back to 70 (#199). Video «واچ ليست زياد چه ضرر هايي» (#286). | — | No numeric rule in the text. | D |

---

## 11. Changes over time / contradictions (summary)

1. **Minimum RR:** < 1 forbidden (#34) → < 2 forbidden (#37, #70, #117, #151), and 3 for forex (#152).
2. **Risk per trade:** a hard 3% (#50, #56, #60, #144). Exceeded in one example (4%, #52). Later "1% or 0.5% if afraid" (#264).
3. **Stop width:** "0.6% is illogical" (#88) vs. 0.2–0.4% and < 1% stops on 15m VIP signals (#52, #68, #203). → Treat as relative to timeframe (ATR-based).
4. **Breakout entry:** pullback/retest preferred (#87, #143) vs. immediate breakout on compression (#49) and immediate entry on the breakout candle in Kian's strategy (#124).
5. **Indecision fill:** "next candle above the shadow" (#82) vs. "wait for close, then stop order" (#83, #84). These are compatible: a stop order placed after the indecision candle closes.
6. **Exit philosophy:** "don't close before target, only BE" (#47) vs. partials at higher highs and near resistance (#149), and the TF-limited expectation (#127) vs. let 10–30R runners go (#129, #152).
7. **Partial size at 2R:** 30% (#70, #117), 33% (#60, #203 TP1), 30–40% (#203).
8. **Simultaneous positions:** shared 3% budget (#60) vs. a 3-position hedge (#44, #45).
9. **Content shift:** after Oct 2021 the channel moves to video links and then to crypto games/NFT promotions (#297–#403). No trading rules after #273.

---

## 12. Proposed baseline system for the backtest (built only from the rules above)

- **Universe and market:** crypto futures (Binance-style), top-100 coins (CM14). Forex variant: min RR 3.
- **Timeframes:** triad ∈ {(1D, 4H, 1H), (4H, 1H, 30m), (1H, 30m, 15m)}. Zones come from the HTF and analysis TF. Entries come from the entry TF only (TF1–TF4).
- **Setups (whitelist):**
  - **T1:** indecision candle at a zone → stop order at the high (long) or low (short). SL at the opposite wick. TP1 = next opposing zone.
  - **T2:** break → pullback → confirmation candle (full body, volume) → enter. SL at the pullback candle's wick.
  - Optional **K:** Kian's trendline and zone breakout with a full-body, high-volume candle.
- **Filters:**
  - Skip if RR to TP1 < 2 (crypto) or < 3 (forex).
  - Skip if the stop distance falls outside [a, b] × ATR.
  - Skip chases: return over the last N bars > X%.
  - Optional regime filter that skips ranges.
- **Sizing:** risk = 3% of equity (grid 0.5–3%). Total open risk ≤ 3%, and a trade whose SL is at BE frees its budget (CM5, CM6). Leverage cap 10–20.
- **Management:**
  - At +2R: close 30% and move SL → entry (PM1).
  - The remainder trails behind new pivot lows/highs (SL9, PM7).
  - Hard runner TP at 20–30R (RR10).
  - Variant: TF5 cap of 2–4 entry-TF candles in the non-trending regime.
- **Circuit breakers:** 3 consecutive losses → 24 h pause (P1). A trade worth ≥ X% (win or loss) → 7-day pause (P3, optional).
- **Fees:** maker for limit entries, taker for stop entries and stops (E5).

---

## Summary: the most important codable rules

1. **Risk 3% of equity per trade (max), with total open risk ≤ 3%.** A second trade is allowed only from leftover budget, or once the first trade is risk-free with its SL at entry (#50, #56, #60, #144). Size = equity × risk / stop distance; leverage follows from that (#50, #68).
2. **Minimum RR 2 to the first target in crypto, 3 in forex.** Skip a trade otherwise (#37, #70, #117, #151, #152).
3. **At +2R: close about 30% (30–40%) and move SL to entry.** Trail the rest behind new swing lows/highs. Close runners at 20–30R (#70, #117, #203, #132, #152).
4. **Trigger 1, indecision candle at S/R:** never enter on the candle itself. After it closes, place a stop order beyond its wick. SL at the other wick. TP = next opposing zone (#82–#85, #87).
5. **Trigger 2, break → pullback → strong high-volume confirmation candle:** enter, with SL under the pullback candle's wick (#87, #143). Nothing outside the two triggers is traded (#87).
6. **Three-timeframe structure** (1D/4H/1H, 4H/1H/30m or 1H/30m/15m; spot M/W/D). Never look below the entry TF. Expectations scale with the TF (#127, #85, #142).
7. **Circuit breaker:** after 3 stop-losses, no trading for ≥ 24 h, and no revenge trades (#65). Optionally a one-week pause after an outsized win or loss (#64).
8. **No anticipation:** patterns and breaks must be confirmed by a closed candle, plus a pullback in ranges, which are prone to fake-outs (#103, #147).

Everything about Dow theory, market phase and chart patterns is taught **only in videos** that are not in the archive, so it cannot be extracted from this source.
