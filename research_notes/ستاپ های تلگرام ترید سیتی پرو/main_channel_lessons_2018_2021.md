# Trade City Pro main channel (@tradecity_pro): educational posts 2018–2021, rules for a mechanical backtest

Source: `data/cache/telegram/main_edu_A_2018_2021.jsonl` (421 posts, ~252k chars). Each post is at `https://t.me/tradecity_pro/<id>`.
Some posts were truncated in the scrape (they end in "…"). For those I used the full text from `education.jsonl` (separate education channel, marked `EDU#n`) or from a later full repost in the same file. I note where I did this.

Coverage notes
- The file has **no 2018 posts**. The first post is 2019-07-20 (#1747).
- There are two eras.
  - **Era 1 (2019-07 → 2020-07, BitMEX era)**: very few posts, almost all on money management and psychology. Arshia Azizpour writes them.
  - **Gap 2020-07 → 2021-06**: the channel was inactive. #5779 says the author left social media during COVID.
  - **Era 2 (2021-06 → 2021-12, Binance futures era)**: dense teaching. Authors are Arshia Azizpour (AA), Kian Zandi (KZ) and Yasi Naseri (YN). Most entry-rule content is in Era 2.
- Many posts are verbatim reposts. For example #3275/#3350/#3613/#4193 are the same text. I cite the first occurrence.
- Some content exists **only on video**: Dow theory parts 1–7, market phase, multi-timeframe, chart patterns (V, H&S, double top/bottom, triangles, flags), stop-loss placement, save-profit, psychology. These posts contain no codable text. I list them in §10 and don't guess what is in them.

Tag legend: **[M]** mechanical as stated · **[O]** operationalisable (proposed definition + parameter grid) · **[D]** discretionary / not codable.

Agreement with the education-channel notes (`education_channel_rules.md`) is marked **=EDU**. Contradiction is marked **≠EDU**.

---

## 1. Capital management (مدیریت سرمایه)

### 1.1 Risk per trade
| Post | Date | Quote | Gloss | Tag |
|---|---|---|---|---|
| #1750 | 2019-07-20 | «هر پوزیشن که میزارید باید بین ۲ الا ۴ % سرمایه باشه.» | "Each position should be 2–4% of capital." It is ambiguous whether this is margin or risk. Read with point 3 of the same post, it is most likely **margin per order**. | [O] |
| #2228 | 2019-08-24 | «در هر پوزیشن ریسک 3% رو رعایت کنید.» | Respect 3% risk per position. | [M] =EDU |
| #2493 | 2019-12-01 | «بر اساس استراتژی تیم ترید سیتی پرو در بد ترین حالت 3% از سرمایه شما وارد ضرر می شود.» | Worst case, a trade loses 3% of equity. | [M] =EDU |
| #3877 | 2020-07-09 | «تو هر ترید ماکسیمم ۱٪ روی کل سرمایه ضرر کنید» | (VIP advert) max **1%** loss per trade. | [M] ≠EDU (lower) |
| #4297 / EDU#50 | 2021-07-07 | «چون اجازه نداریم بیشتر از ۳٪ ریسک کنیم پس اگر حد ضرر می خوردیم ۳٪ سرمایه ضرر میکردیم» | "We are not allowed more than 3% risk." | [M] =EDU |
| #4443 | 2021-07-14 | «در مدیریت سرمایه من اجازه ندارم بیشتر از ۳٪ سرمایه در هر ترید ضرر کنم» | Same rule. Leverage 10 with a 0.7% stop gives 7% if all capital is used, so he used 50% margin to land near 3%. | [M] |
| #5560 | 2021-08-26 | «با ریسک 3% ترید می کنم» | Trades with 3% risk. | [M] |
| #6537 | 2021-10-13 | «اگر می ترسین ۳٪ سرمایه ضرر کنید ۱٪ درگیر کنید اگر ۱٪ هم می ترسین ۰.۵٪ درگیر کنید» | If 3% scares you, use 1%, or 0.5%, and scale up slowly. | [O] grid: risk ∈ {0.5, 1, 2, 3}% |

**Realised risk in the VIP logs.** #4317 (2021-07-09), #5064 (2021-08-06) and #6107 (2021-09-26) show losses of **−1%, −1.5% or −3%** on balance. Risk was 3% at most, and often less. In #4579 (2021-07-20), three stop-outs cost 3% in total, so about 1% each that day. **Codable:** fixed fractional risk with `risk_pct ∈ {1, 1.5, 3}`, 3% as the ceiling.

**Contradiction.** In #4300 (2021-07-08) the stop was about 0.2%, the whole capital was used at leverage 20, and the post says «اگر حد ضرر خوردیم ۴٪ کل سرمایه ضرر میکردیم» ("we would have lost 4%"). That breaks the 3% cap. It is the only such case.

### 1.2 Position sizing formula (implied by the worked examples)
In this channel, "capital engaged" (سرمایه درگیر) means **margin**. The worked examples are #4196, #4297, #4443, #4583/EDU#68, #5165 and #6194.
- `notional = equity × risk_pct / stop_pct`, then `margin = notional / leverage`.
- Examples that check out:
  - stop 1.3%, lev 10 → 30% margin → 3.9% (#4297, "~3%")
  - stop 1% → 30% margin @ lev 10 (#6194)
  - stop 0.3% → 100% margin @ lev 10 → 3% (#5165)
  - stop 1.8% → 20% margin @ 3% risk (#4196, approximate)
- **[M]** Size from risk and stop distance. Leverage only sets margin usage, so treat it as a constraint (`margin ≤ equity`) and not as a risk input.

### 1.3 Leverage, margin mode, spot vs futures (evolution)
| Post | Date | Quote | Gloss | Tag |
|---|---|---|---|---|
| #1750 | 2019-07-20 | «هیچ وقت لورج بالا استفاده نکنید. ماکسیمم ۱۰،من خودم ۷ استفاده میکنم.» | Never use high leverage. Max 10; he uses 7. | [M] |
| #3365 | 2020-04-03 | «لطفا تقاضا دارم ازتون که با کراس ترید نکنید» | Don't trade with **cross** margin. His example used isolated leverage 5 with 30% of capital, a 12% move, +15% on the account. | [M] use isolated margin |
| #3365 | 2020-04-03 | «حد ضرر ها زیر 2% نیست تو این تحلیل ها» | Used to argue that cross-margin 1.2%-target trades have bad R:R. In context it means real stops are rarely under 2%. | [D] |
| #4300, #4583, #5165, #6337 | 2021 | lev 10–20 | In 2021, leverage of 10 or 20 is normal, because 15-minute stops are tiny (<1%). | evolution |
| #2803 | 2019-12-29 | «برای اسکالپ ، ترید روزانه ، ترید هفتگی به هیچ وجه در بایننس ترید نمیکنم» | No spot (one-directional market) for scalp, daily or weekly trading. Spot only for 3-month baskets. | [O] |
| #3950 | 2021-06-21 | «برای پوزیشن در فیوچرز تایم فریم های پائینتر نیاز داریم واسه ورود» | Futures entries need lower timeframes. Spot entry = daily close above trendline resistance. | [O] |
| #5564 | 2021-08-26 (KZ) | «با حد ضرر ١٠ درصد اسپاتي يعني بدون لوريج» | Spot example uses a 10% stop and no leverage. | [O] |
| #6099 | 2021-09-26 | «آلت کوین ها رو هم در اسپات... اکثرشون نزدیک ۱۰٪ حد ضرر نیاز دارند» | Alt spot buys usually need about a 10% stop. | [O] spot stop 8–12% |
| #6295 | 2021-10-03 | «حد ضرر ها ي همشون زير خود كندل و يا شدو اين كندل هفتگي... از ١٠٪؜ تا ٢٠٪؜» | Spot picks: stop under the weekly candle body or shadow, 10–20%. | [O] |

### 1.4 Number of positions / total open risk
| Post | Date | Quote | Gloss | Tag |
|---|---|---|---|---|
| #1750 | 2019-07-20 | «تو یک حرکت ماکسیمم ۱۰% الا 15% سرمایه استفاده میشود اونم تو یه رنج ۷%» | In one move, use at most 10–15% of capital, spread over a 7% price range with 3–4 orders. Worst case (BTC +50%) is −10% of the account. | [O] **total risk per idea ≤10%** (old BitMEX rule) |
| #1750 | 2019-07-20 | «۳ الا ۴ اوردر بزارید،چه برای باز کردن پوزیشن چه برای بستن پوزیشن» | Use 3–4 orders to enter and 3–4 to exit, i.e. scale in and out. | [O] grid: n_orders ∈ {1, 3, 4} |
| #3877 | 2020-07-09 | «در اسپات بیشتر از ۲ تا کوین همزمان نمی گیریم» | Spot: never more than 2 coins at once. | [M] |
| #3950 | 2021-06-21 | «ترجیحا بر روی یک کوین پوزیشن باز کنید بین ۱۰ کوین اول تقریبا از نظر سود دهی هیچ تفاوتی با هم ندارند» | Prefer a position on one coin; the top-10 coins perform about the same. | [O] |
| #4588 | 2021-07-21 (team) | «توي بازار ارز ديجيتال نهايتا بيشتر از ٢ پوزيشن توي اين ماركت باز نكنن» | Max **2 open positions** in crypto, because everything is correlated with BTC. | [M] max_positions=2 |
| #4583 / EDU#68 | 2021-07-20 | «حد ضرر گزاشتیم روی نقطه ورود (که بتونیم اگر سیگنال دیگری بود باز پوزیشن باز کنیم)» | Stop was moved to entry so that a new signal could be taken. A risk-free position frees the risk budget. | [O] total-risk counter excludes positions with stop ≥ entry |
| #5864 | 2021-09-07 | «اگر بیشتر از ۳٪ سرمایه امروز وارد ضرر شدین حتما ویدیو مدیریت سرمایه... نگاه کنید» | Losing more than 3% in a day means you broke the rules. | [O] **daily loss limit 3%** =EDU (3% total) |

**Contradiction.** The VIP channel ran many concurrent signals (#4317, #5064 and #6107 list dozens in 2–7 weeks) and hedged: 2 alt longs plus a BTC short (#4227). That conflicts with the max-2-positions rule in #4588. A reasonable backtest default is `max_positions=2` and total open risk ≤3%. Test {1, 2, 3} positions and {3, 6, 10}% total risk as sensitivity.

### 1.5 Hedging (پوشش ریسک)
- #4227 (2021-07-03): «ما یک مفهومی داریم در بازار مالی به نام پوشش ریسک». Two alt longs (R:R 3 and 2) were opened together with a BTC short. One side's targets pay for the other side's stops. **[O]** BTC-hedged alt longs.
- #4295 (2021-07-07): no hedge when BTC is ranging, «بیت در حال رنج زدن بود و هیچ روند خاصی نداشت که من بتونم حد ضرر درست براش تعیین کنم». **[O]** filter: hedge only if BTC is trending. Low priority.

### 1.6 Account-level targets and profit allocation
- #3275 (2020-03-08): «هر ماه نسبت به ماه قبل 5% فقط 5% سود کرده باشید... این روتین رو برای 6 ماه حفظ کنید». Aim for a steady +5% a month for 6 months before chasing more. **[O]** benchmark only.
- #3275: «دلیل نمیشه که ریسک ترید.هارو بالاتر ببرید تا ضررتون رو یک شب جبران شه». Never raise risk to recover losses. **[M]** risk does not increase after a drawdown.
- #4821 (KZ): «نه غير از اون مثلا بگين بازار خوبه ديگه اينجا اهرم مون رو بالا ببريم». Don't raise leverage because the market "looks good". **[M]** fixed parameters.
- #5560 (2021-08-26): each month, of profits, 10% is saved, 10% spent, 10% buys a reward, 10% goes to long-term alt holds, and about 60% is compounded. **[O]** equity-withdrawal model (≈40% of monthly profit withdrawn).
- #5815 (2021-09-05): «هرجایی بیشتر از ماهی ۳٪ سود میدادن فرار کنید ازش». About scams; not a trading rule. [D]

---

## 2. Risk-to-reward (ریسک به ریوارد)

| Post | Date | Quote | Gloss | Tag |
|---|---|---|---|---|
| #2228 | 2019-08-24 | «نسبت زیر 2 اصلا مناسب ترید نیست» / «فقط... نسبت ریسک به ریوارد شما بالای 2 باشد» | R:R under 2 is not tradable; take only R:R above 2. | [M] =EDU |
| #2296 | 2019-08-31 | «من خودم اول حد ضرر میزارم بعد اوردر خرید» | Place the stop first, then the buy order. | [M] every order has a stop |
| #3276 | 2020-03-08 | «اگر نسبت ریسک به ریواد شما 2 باشد فقط نیاز که 33% مواقع تحلیل هاتون درست باشه» | Break-even win rate at 2R is 33%. | [M] arithmetic |
| #4043 | 2021-06-26 | «اولین جایی که اجازه دارین پوزیشن ببندین در زمانی هست که ۲۰ دلار سود کرده باشید» | The first price where you may close any part is +2R. No discretionary exit before 2R (stop-out excepted). | [M] =EDU |
| #4254 | 2021-07-05 | «ماکسیمم کاری که می تونید بکنید این هستش که حد ضرر بزارین روی نقطه ورود و منتظر تارگت خودتون با ریسک به ریوارد ۲ باشید» | Before 2R, the only allowed action is moving the stop to entry. | [O] see §4 |
| #4443 | 2021-07-14 | «اگر ریسک به ریوارد سیگنال یا تحلیلی زیر ۲ بود اصلا ترید نکنید» | Same min-2 filter. | [M] |
| #5024 | 2021-08-04 | «تارگت ۱ حد اقل ریسک به ریوارد ۲ داره» | TP1 is at least 2R. | [M] |
| #6337 | 2021-10-04 | «همیشه تارگت ۱ ریسک به ریوارد ۲ هستش» / «تارگت ۲ ( که عموما ریسک به ریوارد ۵ هست...)» | TP1 is always 2R; TP2 is usually about 5R. | [M] TP1=2R, TP2≈5R |
| #5852 | 2021-09-06 | «ریسکتون ۱ ریواردتون ۲... این مینیمم ریسک به ریواردی هست که من برای ترید های خودم قائلم» | 1:2 is his personal minimum. He closes below 2R about once in 100 trades, and then immediately reverses. | [M] |
| #5852 | 2021-09-06 | R:R 1:1 «واسه افراد مبتدی بازار نیست... مگر در بازار رنج» | 1:1 only for pros, or in ranges with a range-specific strategy. | [D] |
| #5853 | 2021-09-06 | «در فارکس مینیمم ریسک به ریوارد من ۳ هستش» | Forex minimum is 3R. In crypto, if 3R is available, 5R usually is too. | [M] =EDU (2 crypto / 3 FX) |
| #5853 | 2021-09-06 | «من خودم بعد از سید سود رو ریسک به ریوارد ۲ و ریسک فری کردن با دنبال کردن بازار و جابه جا کردن حد ضرر ریسک به ریوارد های ۱۰ ۲۰ ۳۰ میگیرم... اکثرا در ریسک به ریوارد ۵ بسته میشن» | After the 2R partial and moving the stop to entry, he trails the stop to catch 10–30R (2–3 times a month). Most trades end near 5R. He closes at 20–30R "without thinking". | [O] trailing runner with a hard cap at 20–30R |

The VIP logs confirm the minimum of 2R. #5064 reports R:R from 2 to 35 and a 63% win rate. #6107 reports 111 signals, 37 stops, a 66.6% win rate and TP1 = 2R. Note that "risk free" (stopped at entry) is counted as a non-loss in these logs.

---

## 3. Stop-loss (حد ضرر / استاپ لاس)

| Post | Date | Quote | Gloss | Tag |
|---|---|---|---|---|
| #2228, #2296, #2665 | 2019 | «هر سیگنال یا تحلیلی که بدون حد ضرر بود اصلا نگیرید» | Never take a trade without a stop. | [M] |
| #4448 | 2021-07-14 | «منطقی باشد (حد ضرر 30% کاملا اشتباه هست و همینطور حد ضرر 0.6%)» | The stop must be reasonable: 30% is wrong and so is 0.6%. | [O] stop-distance bounds |
| #4448 | 2021-07-14 | «حد ضرر جایی باید گذاشته شود که فروشنده ها یا خریدار ها به راحتی حد ضرر شما رو فعال نکنند» | Put the stop where it is expensive for the other side to hit. | [O] beyond swing/zone + buffer |
| #4448 | 2021-07-14 | «حد ضرر شما باید در نزدیکی نقطه عطف باشه... اگر فعال شد قیمت مسیر حرکتش عوض شود» | The stop sits at the invalidation / turning point: if hit, the structure has flipped. | [O] stop = beyond the last swing low (long) |
| #5238 | 2021-08-12 (KZ) | «استاپ رو بايد بالاي شدو در يك ناحيه خوب حمايتي و يا مقاومتي گذاشته بشه» | Stop goes beyond the **shadow**, inside or behind a good S/R zone. When trailing, move it behind the shadows of newly formed zones. | [O] |
| #5572 | 2021-08-26 (KZ) | «استاپ مطمئن ميشه زير كف هايي كه ساخته شده (... زير شدو ها باشه يا كندل ها)» | Stop goes under valid swing lows, at the shadow or the body depending on the chart. | [O] grid: wick vs body |
| #5797 | 2021-09-04 | «سیگنال های تایم فریم ۱۵ دقیقه( اصولا حد ضرر شون زیر ۱٪ هست...)» | 15m VIP signals have stops under 1%. | [O] |
| #4300 / #4583 / #5165 | 2021-07/08 | stops of 0.2%, 0.4% and 0.3% | Very tight stops on 15m. | evolution |
| #6099, #6491, #6580 | 2021-09/10 | «حد ضرر کلوز کندل دیلی زیر ۴۰۵۰۰» | For BTC swing trades the stop is a **daily close** below a level, not an intraday touch. | [O] close-based stop for swing (1D) trades |

**Contradiction / evolution.** In #4448 (2021-07) a 0.6% stop is "wrong". A week earlier (#4300) and later (#4583, #5165, #5797) the VIP trades used 0.2–0.4% and "<1%" stops on 15m. The likely reconciliation is that a stop must fit its timeframe's structure, so test a minimum stop in ATR units rather than in percent. Era 1 (#3365) implies real stops are usually ≥2%.

**Proposed definition [O].**
- Long stop = `min(low of signal/pullback candle, last swing low) − k·ATR(14)`, with `k ∈ {0, 0.1, 0.25}`.
- Reject the trade if the stop distance is `< 0.5·ATR` or `> 3·ATR` on the entry timeframe.
- Swing variant on 1D: exit on a daily close beyond the level.

---

## 4. Position management (ریسک فری, سیو سود, پله‌ای, trailing)

| Post | Date | Quote | Gloss | Tag |
|---|---|---|---|---|
| #4317 | 2021-07-09 | «سیگنال هایی که ریسک فری نوشته شده جلوشون یعنی روی نقطه ورود حد ضرر خوردیم» | "Risk free" = the trade was stopped at entry after the stop was moved to break-even. | definition |
| #4583 / EDU#68 | 2021-07-20 | «۳۰٪ پوزیشن را در ریسک به ریوارد ۵ بستیم و حد ضرر گزاشتیم روی نقطه ورود» | Closed 30% at 5R and moved the stop to entry; the rest was closed at 35R. | [O] |
| #5024 | 2021-08-04 | «روی ریسک به ریوارد ۲ خودم اعلام کردم ۳۰٪ پوزیشن ببندن و حد ضرر بزارند نقطه ورود» | At 2R, close 30% and move the stop to entry, even though TP1 was at about 4R. | [M] =EDU |
| #5797 | 2021-09-04 | «تارگت ۱ نزدیک ۳۳٪ ببندین و حد ضرر بزارین نقطه ورود ، تارگت ۲ نبندین اصلا ، تارگت ۳ کلا ۳۰٪ باز نگه دارین» / «روی ریسک به ریوارد ۲ نزدیک ۳۰ الی ۴۰٪ پوزیشن بسته میشه» | TP1: close about 33% and move the stop to entry. TP2: close nothing. TP3: keep 30% open. At 2R close 30–40% and keep the rest for higher R. | [M] |
| #6194 | 2021-09-30 | «اعلام کردیم ۵۰٪ پوزیشن را روی تارگت ۱ ببندن و نزدیکی های تارگت ۲ اعلام کردیم کل پوزیشن را ببندن» | Variant: 50% at TP1 (3R), the rest near TP2 (8R). | [O] |
| #6337 | 2021-10-04 | «بر روی تارگت ۱... هیچی نبندین... روی تارگت ۲... کلا ۵۰٪ ببندین و حد ضرر به نقطه x جابه جا کنید» | Variant: nothing at TP1 (2R) when a strong move is expected; 50% at TP2 (≈5R) and move the stop. | [O] |
| #5200 | 2021-08-11 (KZ) | «فقط سيو سود كنين و استاپ رو روي نقطه ورود بگذارين و رهاش كنين» | In a trending bull or bear market, take a partial, put the stop at entry and let the rest run. | [O] |
| #5189 | 2021-08-11 (KZ) | «تيپي هم يا كف اول يا سقف اول... ٣٠ ٪ خارج ميشم و استاپ نقطه ورود» | TP1 = first prior swing high (long) or swing low (short): close 30% and move the stop to entry. TP2 depends on conditions. | [O] |
| #5572 | 2021-08-26 (KZ) | «توى سقف بالاترى كه زديم يه مقدار سيو سود ميكنيم... تو اون كف پايينى باز يه مقدار به پوزيشن اضافه ميكنيم» / «ميتونيد مثلا تو ريسك به ريوارد ٢ يه مقدار از پوزيشن رو سيو سود كنيد» / partial before a resistance whose break is uncertain | Save profit at each higher high, re-add at the next higher low. Alternatively take a partial at 2R, or a partial into resistance. | [O] |
| #5564 | 2021-08-26 (KZ) | «بعد از هر اصلاح يه خريد در كف جديد مي كنيم... استاپ هم كه همراه خريد پله مياريم بالا» / exit: «تو سقف اول يه پله و سقف دوم... كل سرمايه رو خارج ميكنيم» | Spot pyramiding in an uptrend only: buy a tranche at each new higher low and trail the stop up. Exit one tranche at the first lower high and everything at the second lower high. | [O] |
| #5853 | 2021-09-06 | trailing after 2R + risk-free to 10/20/30R, close at 20–30R | see §2 | [O] |
| #6580 | 2021-10-15 | «ولی نگفتم سیو سود کنید و روی نقطه ورود حد ضرر خوردیم» | Admits a BTC trade that reached +17% was stopped at entry because no partial was taken. The lesson favours taking partials. | [D] |

**Proposed exit model [O]** (default = the 2021 consensus, =EDU):
1. Initial stop as in §3.
2. At +2R, close `p1 ∈ {0.3, 0.33, 0.5}` and move the stop to entry.
3. Manage the remainder with one of:
   - (a) a fixed TP2 at `{4, 5, 8}R`, closing `{50%, 100%}`;
   - (b) a swing trail (stop under the last confirmed swing low on the entry TF, fractal `n ∈ {2, 3, 5}`);
   - (c) a hard cap at `{20, 30}R`.
4. Variant (#6337): skip step 2 and take 50% at 5R. Use it for an ablation only.

---

## 5. Entry triggers / setups

### 5.1 The two official triggers (=EDU)
- #4447 (2021-07-14): «از استراتژی ما تا الان فقط 2 تریگر برای سیستم معاملاتی داریم». The two triggers are:
  1. «خرید با کمک کندل ایندیسیژن بر روی حمایت / فروش با کمک کندل ایندیسیژن زیر مقاومت» (buy with an indecision candle on support / sell with one under resistance).
  2. «فروش در صورت شکسته شدن حمایت(برای پوزیشن بهتر در پولبک) / خرید در صورت شکسته شدن مقاومت(برای پوزیشن بهتر در پولبک)» (sell on a support break, buy on a resistance break, better entry on the pullback).
- «به جز این حالت ها ما هیچ پوزیشن باز نمی کنیم... حتی شده برای 1 ماه ترید نمیکنیم» (no other entries, even if that means a month without trading). **[M]** whitelist of setups.

### 5.2 Indecision / reversal candle (=EDU)
- #4325 (2021-07-10): the anatomy is a long lower shadow on support, closing green. «قوانین کندل ها فقط در نقاط مهم صدق می کند مثل: روی حمایت ، روی مقاومت ،روی روند». Candle rules apply only at S/R or a trendline. **[O]**
- #4328/#4329 (full text in EDU#83/84) and #4327 (EDU#82):
  - «ما هرگز... روی خود کندل ایندیسیژن ترید نمی کنیم» (we never trade the indecision candle itself).
  - Long: buy-stop **above the indecision shadow (high)** once it has closed, triggered when the next candle trades above it.
  - Short: sell-stop below the low.
  - «به طور معمول تا اولین مقاومت» (typical target is the next S/R).
  - **[M]**
- #3935 (2021-06-20): «برای پوزیشن شورت نقطه ورود شما پایین شدن کندل میشه و حد ضرر بالای شدو کندل». For a candle at resistance: short entry below the candle's low, stop above its upper shadow. **[M]** The stop is the candle's opposite extreme.
- #2256 (2019-08-27): «یک تریدر منتظر دیدن کندل بازگشتی میشه رو حمایت و تایید میگیره». Wait for a reversal candle at support as confirmation. This is the earliest version of the same idea. **[O]**
- #4330 (2021-07-10): «فقط فقط حمایت و مقاومت را بلد بودم و همین یدونه کندل... ماهی ۱۰ تا پوزیشن میداد... نزدیک ۳۰٪ سود رو کل سرمایه». Six years ago, S/R plus this one candle gave about 10 trades and about 30% a month. A rough expectation benchmark; [D].

**Proposed definition [O].** An indecision candle is one where:
- the rejection shadow is ≥ `w × range`, with `w ∈ {0.5, 0.6}`;
- the body is ≤ `b × range`, with `b ∈ {0.3, 0.4}`;
- the shadow pierces a zone (pivot S/R or trendline) within `z × ATR`, with `z ∈ {0.25, 0.5}`.

Entry is a stop order at the high + tick (long) or low − tick (short), valid for `{1, 2, 3}` bars. The stop is the candle's other extreme (± buffer).

### 5.3 Break → pullback → strong candle (تثبیت) (=EDU)
- #5518 (2021-08-23, KZ): «شكست يك مقاومت يا يك حمايت استاتيك و يا دايناميك وقتي اتفاق ميفته منتظر باشيم پول بك به اون سطح داشته باشيم و بعد يه كندل خوب پر جون با حجم خوب به اون سمت ديده بشه... با استاپ زير شدو ي او كندل قبلي كه پولبك بوده». After a break of a static or dynamic level, wait for a pullback to it. Then wait for a strong body + good volume candle in the break direction, enter, and put the stop under the shadow of the pullback candle. **[O]**
- #5327 (2021-08-16): «هيچ ناحيه ي حمايتي و مقاومتي معتبر نيستند تا كندل خوبي در اون ناحيه ديده نشده» (no zone is valid until a good candle with good body and volume appears there). **[O]**
- #4295 (2021-07-07), exception: entered long **above resistance without waiting for the pullback**. The 15m price had been compressed under the level for a long time («فشردگی قیمت... فنر» — compression, like a spring). **[O]** "compression breakout": skip the pullback if ≥N bars sat within X·ATR under the level. N ∈ {20, 40}, X ∈ {0.5, 1}.
- #5126 (2021-08-08): «برای ورود جدید بعد از ۴۵۳۷۰ اقدام به خرید کنید با حد ضرر ۴۳۲۰۰». A buy-stop above a level, used as a breakout entry. «در صورتی که کندل امروز بالای ۴۵۰۰۰ بسته بشه میشه به شکست مقاومت خوش بین بود» (a break counts on a daily close beyond the level). **[O]** break = close beyond level.
- #3950 (2021-06-21): spot buy «هروقت کندل روزانه بالای روند مقاومتی بسته شد» (whenever a daily candle closes above the resistance trendline). **[O]**

**Proposed definition [O].**
- Break = a close beyond the level by ≥ `{0, 0.1, 0.25}·ATR`.
- Pullback = a low within `{0.25, 0.5}·ATR` of the level within `{3, 5, 10}` bars, with no close back beyond it by more than 0.25 ATR.
- Strong candle = `body ≥ {0.6, 0.7}·range`, `body ≥ {1.0, 1.5}×` the median body of 20 bars, and `volume ≥ {1.2, 1.5}× SMA20(volume)`.
- Enter at the close of the strong candle, or a stop above its high.
- Stop = the pullback candle's shadow ± buffer.

### 5.4 Kian Zandi's price-action strategy (#5189, 2021-08-11) (=EDU §4.4)
- «خطوط حمايت و مقاومت رسم ميكنم و اون ها رو طبق برخورد هايي كه داشتند اعتبار سنجي ميكنم» — validate S/R by the number of touches. **[O]** zone strength = touches ≥ `{2, 3}`.
- «خطوط ترند... كه بشكنه... و از اون ناحيه مهم ام... هم بزنه بيرون با يه كندل فول بادي يه خوب و حجم خوب، پوزيشنم رو... باز ميكنم» — enter when a trendline break **and** a zone breakout happen with a full-body, good-volume candle.
- Stop under that strong candle. TP1 = first swing high/low: close 30% and move the stop to entry. TP2 depends on conditions. «بدون استفاده از هيچ انديكاتور» (no indicators). **[O]**

### 5.5 Patterns
- #4845 (2021-07-29): «لطفا لطفا پیشواز پترن نرید... منتظر باشید پترن اتفاق بیفته تایید بده بهتون... خط گردن شیکست حالا قراره بریزه». Don't anticipate patterns; enter only after confirmation (e.g. neckline break). **[O]** pattern trades need a close beyond the neckline or boundary.
- #5797: VIP example «مثلث شکسته شد خریداری کنید» (triangle broke → buy). **[O]**
- Pattern videos: V (#6751), H&S (#6867), double top/bottom (#6949), triangles (#7194, #7330), flags (#7578), diamond (#5577 «اگر می خواین شرایط بازار بدونید پترن دیاموند رو بخونید»), dead cat bounce (#7377). Video only; [D].

### 5.6 Other entry filters
- #4610 (KZ): «اگر كويني مثبت چند درصد رشد كرد بعد رشدش تازه نريم بخريمش». Don't buy a coin after it has already rallied several percent. **[O]** skip a long if the 24h return is > `{5, 8, 10}%`, or the entry is more than `{2, 3}·ATR` from the trigger level.
- #6580 (2021-10-15): «من تو استراتژی خودم تا روند صعودی نشه خرید نمی زنم» (twice). Don't buy at support until the trend has turned up. **[O]** long only if the trend state is up (Dow HH/HL on the setup TF, or price > SMA). This is a key filter for the spot/BTC swing trades.
- #6099 (2021-09-26): wait for a «کندل حمایتی خوب» (good support candle) in a key zone (BTC 40–41k), preferably at the daily close. A risky early entry is allowed with a stop on a daily close below 40.5k. **[O]**
- #5126: «در روزانه واگرایی منفی داریم ولی دلیل محکمی برای ریزش نیست». Bearish daily divergence alone is not a sell reason. **[M]** divergence is not a standalone trigger.
- #5014 (team, citing Excavo): «يك سيگنال خريد لغو شده ميتوان يك سيگنال فروش و بالعكس». A failed buy setup can become a sell, but not on one red candle. **[O]** failed-breakout reversal (fake) setup. Low priority.
- #4569: «اگر بازار خلاف پيش بيني شما حركت كرد،پوزيشنتون رو ببنديد... هي به پوزيشنتون اضافه كنيد!» (if the market moves against you, close; don't keep adding). **[M]** no averaging down. See the contradiction with #1750 scaling-in in §11.

---

## 6. Support/resistance, timeframes, multi-timeframe

| Post | Date | Quote | Gloss | Tag |
|---|---|---|---|---|
| #5515 | 2021-08-23 | «ناحيه هاي حمايتي و مقاومتي كه مشخص ميكنين رو سعي كنين از تايم فريم هاي بالا به پايين بياين» / «مقاومت ها و حمايت ها تو تايم فريم هاي بالا تر بسيار معتبر تر هستند» / «از ماهانه تا ١٥ دقيقه» | Draw zones top-down from monthly to 15m. Higher-TF zones are stronger; expect less from 1m/5m levels. | [O] zone weight ∝ TF |
| #6778 | 2021-10-24 (YN) | «هرچي تايم فريم كوچيك تر بشه،ريسك بيشترى داره،چون شكست هاي فيك توش بيشتر هست» | Lower TF means more fake breakouts. | [O] |
| #5797 | 2021-09-04 | 15m signals; 1h/4h/daily analyses | VIP stack: 15m entries, 1h/4h/1D context. | [O] TF grid |
| #3950 | 2021-06-21 | daily for spot, lower TF for futures entries | see §1.3 | [O] |
| #5330 | 2021-08-16 | «اگر مولتی تایم فریم نداشتیم من هیچ وقت نمی تونیم ترید کنم» | Multi-timeframe is essential; details only in video. | [D] =EDU (3-TF) |
| #6580 | 2021-10-15 | «برای تصمیم گیری درست نیاز دارم کندل هفتگی ببنده» | Decisions at a key box wait for the weekly close. | [O] |
| #3971 | 2021-06-22 | «تو هر تایم فریمی این ۲ تا کندل دیدین دیگه تا یه مدت تو اون تایم فریم ترید نکنید» | If you see "these 2 candles" (photo only) on a TF, stop trading that TF for a while. The candle types are unknown. | [D] (probably very large wide-range candles → cooldown; not verifiable) |
| #6247 | 2021-10-02 | mentions Alfonso's triple-timeframe (RTM), fakeouts, QM, diamond, can-can | Context only. | [D] |

**Proposed MTF [O]** (=EDU 3-TF):
- HTF (1D or 4H) sets the trend filter and the zones.
- Setup TF (1H or 4H) holds the zone and the trigger candle.
- Optional LTF (15m) refines the entry. Grid: (1D, 4H, 1H) and (4H, 1H, 15m).

---

## 7. Market filters (BTC dominance, altseason, news, sessions)

- #4523 (2021-07-18, team):
  - Check BTC.D and TOTAL2 every day before the watchlist.
  - «اگر روزي داميننس بيت نزولي بود و الت ها... صعودي هستند. يعني اون روز روي بيت كوين تريد نكنيم... روز تريد روي الت كوين ها هست... اگر داميننس بيت كوين صعودي بود... روي بيت كوين تريد كنيم». BTC.D falling + alt dominance rising → trade alts, not BTC. BTC.D rising → trade BTC.
  - «ريزشي بودن داميننس الت ها به معني ريزشي بودن خود الت ها هستش ولي ريزشي بودن داميننس بيت كوين دليل بر ريزشي بودن بيت كوين نيست». Falling alt dominance means alts are falling. Falling BTC.D does not mean BTC is falling.
  - **[O]** universe switch: `slope(BTC.D, n) < 0 and slope(TOTAL2, n) > 0` → alts; `slope(BTC.D, n) > 0` → BTC only. Use n ∈ {5, 10, 20} daily bars, or the sign of EMA20 vs EMA50.
- #6198 (2021-09-30): three dominances: BTC.D, TOTAL2, USDT.D; they identify the start of altseason (details on video). **[O]** extra filter: USDT.D rising → risk-off, so no longs.
- #5080 (team): «بيت كوين صعود خودش رو ميكنه... بعد صعود ميره تو اصلاح و رنج... الت پارتي شروع ميشه». After a BTC rally, when BTC corrects or ranges, lagging alts rally. **[O]** alt-rotation filter: BTC 1D range (ADX < 20 or a narrow N-day range) after a +X% leg.
- #6491 (2021-10-11): «اگر بیت به اون محدوده برسه و چند روزی رنج بزنه آلت ها هم حرکت صعودی خواهند داشت». Same idea.
- News: #4522 «سعي كنين كه با اخبار تو اين بازار تريد نكنين»; #4610 «به اخبار اصلا گوش نكنين»; #7004 video on not trading the news. **[M]** no news-driven entries. A backtest can't model news except as an event blackout.
- Token burns (#4522): in spot you may buy on the announcement and sell after the pump; not suitable for futures. [D]
- #4888 (2021-07-31): «همیشه یک تریدر در ۲ بازار مالی باید فعال باشد که در صورت رنج بودن یک بازار یا نداشتن ریسک به ریوارد مناسب در بازار بعدی به ترید بپردازد». A trader should be active in 2 markets and switch when one is ranging or offers no R:R. **[O]** portfolio of crypto + FX.
- Coin selection (#4746, KZ): top-100 CoinMarketCap only, check volume and the order book, reputable exchanges only. Shitcoins at most 1/1000 of capital. **[O]** universe = top-100 by market cap with a liquidity filter.
- Sessions: **no session rule appears in this file.**

---

## 8. Indicators
- **RSI** (#7354, 2021-11-22): «Rsi بندازین رو چارتتون ببینید بره زیر ۳۰ چه اتفاقی میفته واسه قیمت / تایم فریم ۱۵ دقیقه / Rsi رو کلوز کندل مهمه». Look at what happens when RSI goes below 30 on 15m; RSI matters on the candle close.
- **RSI** (#7770, 2021-12-07): the textbook 70/30 is «غلط نیست ولی کاملا ناقص» (not wrong but incomplete).
  - «ورود rsi به زیر 30 نشون دهنده ریزش زیاد و شارپ» — entry below 30 often marks a sharp drop (momentum, not a buy signal).
  - «ورود به بالای 70 نشانه رشد زیاد و شارپ» — above 70 often marks a sharp rise.
  - «بین 30 تا 70... حرف زیادی برای گفتن نداره» — 30–70 says little.
  - Use it only on closed candles. The length is never stated; assume 14.
  - **[O]** momentum use: RSI(14) closing > 70 means don't short, or confirms a breakout; closing < 30 means don't long. The opposite "mean reversion" reading is **not** endorsed. Grid: length {14}, thresholds {30/70, 25/75}, TF {15m, 1H}.
- **Volume**: "good volume" is required on the trigger candle (#5189, #5327, #5518). Never quantified. **[O]** `vol ≥ {1.2, 1.5, 2.0}× SMA20(vol)`.
- **Moving averages, momentum, Ichimoku, Fibonacci, Elliott**: listed only as future topics (#5371: «مووینگ اورج... ایچیموکو(خودم دوسش ندارم)... Rsi»). Ichimoku videos by "Kris" appear in #2623/#2624. **No MA lengths are given anywhere in 2019–2021.** Kian's strategy is explicitly indicator-free (#5189).
- **Order types** (#4897): prefer limit orders over market orders (lower fees). Stop-limit and stop-market are defined. **[M]** for cost modelling, assume maker fills for limit entries and taker fills for stop entries and stop-losses.

---

## 9. Range / fake / stop hunting
- #5238 (2021-08-12, KZ):
  - Stop hunting comes in two forms: near stops and far stops. Far-stop hunts happen more in trending markets.
  - «وقتي بازار يه جا گير ميكنه تو يه باكس... هم بالاي اون ناحيه كلي استاپ هست... و هم پايينش... اين قدر ادامه پيدا ميكنه تا قدرت يكي بيشتر بشه كه اون وقت حركت شارپي خواهد بود». In a box/range there are stops above and below. Price alternately sweeps both sides until one side wins; then comes a sharp move.
  - **[O]** range filter: inside an N-bar box (N ∈ {20, 50}, height ≤ k·ATR), don't place stops just beyond the box edge. Either stand aside or wait for a close outside **plus** the pullback trigger (§5.3).
- #6778: more fakes on lower TFs (see §6).
- #2392 (2019-09-14): «چند روزی هست که تریگری نمیده بازار... امکان خوردن حد ضرر زیاد هست پس منتظر تریگر ترید میمونیم». No trigger, no trade. **[M]**
- #5573: video on range markets and stop hunting. [D]

---

## 10. Dow theory / market phase / trend analysis / save-profit (video only)
- Dow theory, 7 parts: #4904, #4930, #5025, #5063, #5088, #5164, #5293. The text claims «داو تئوری شما رو ازین مشکلات نجات میده» (#5027): it solves early exits, stop placement and closing too fast. «بعد از این ویدیو خودتون باید بتونید... پوزیشن باز کنید تارگت در بیارین حد ضرر در بیارین» (#5293): after it you should be able to set entries, targets and stops. **No codable text.** **[O] proxy:** Dow trend state from swing HH/HL (fractal n ∈ {2, 3, 5}), used as the trend filter in §5.6 and the trailing stop in §4.
- Market phase: #5986 «امشب قسمت اول market phase»; #5989 «داو تئوری صرفا ۱ بخش از ۹ بخش مارکت فیز بود»; #6069; #6122. [D]
- Multi-timeframe video #5330; stop-loss video #5981 («هر استراتژی و هر تریدر باید حد ضرر مخصوص خودش را پیدا کنه»); save-profit video #6832; position-management psychology video #5390. [D]

---

## 11. Psychology rules that can be hard constraints

| Post | Date | Quote | Gloss | Tag / constraint |
|---|---|---|---|---|
| #4579 | 2021-07-20 | «بعد از ۳ تا حد ضرر باید حداقل ۲۴ ساعت از بازار فاصله بگیرم» | After 3 stop-losses, stay out for at least 24h. | [M] =EDU. Consecutive or daily? Here they were 3 VIP losses in a row. Grid: {3 consecutive, 3 within 24h}. |
| #4579 | 2021-07-20 | «revenge trade... بزرگترین اشتباه... پس من ترید نمیکنم حتی اگر بازار تمام نکات استراتژی من را داشته باشه» | No revenge trades after a stop, even on a valid setup. | [M] covered by the cooldown |
| #4563 | 2021-07-20 (team) | «بعد از ضرر و سود زياد يك هفته كار نكنين» | After a large loss **or a large profit**, don't trade for a week. | [O] if a single trade ≥ +X R or the day's PnL ≤ −Y%, pause 7 days. X ∈ {10, 20}R; Y ∈ {3, 5}%. ≠EDU (adds a 1-week, profit-triggered pause) |
| #6602 | 2021-10-16 (KZ) | «اگه حال روحي تون خراب باشه... فقط با ضرر همراه ميشه» / right after waking or before sleep | Don't trade in a bad mood. | [D] (a time-of-day blackout could proxy it) |
| #6602 | 2021-10-16 (KZ) | «اگه موقعيت تريد از دست رفت ولش كنيد» | If you missed the trade, let it go. | [M] no late entries: cancel a pending trigger after N bars |
| #1748 | 2019-07-20 | «من برای باز کرد و بستن پوزیشن ها روزانه ۱۵ دقیقه وقت می زارم» | 15 minutes a day for opening and closing positions. | [O] supports HTF, order-based entries |
| #3759 / #4278 | 2020-06-14 / 2021-07-06 | «شما قرار نیست هروز ترید کنید حتی قرار نیست هر هفته ترید کنید» | You won't trade every day, not even every week. | [M] no minimum trade frequency |
| #5878 | 2021-09-08 | «۹۰٪ کوین ها ورودی پوزیشن لانگ داشتند... ولی من خودم هم نگرفتم چون دلیلی نداره هروز ترید کنین» | 90% of coins gave 15m long entries but he took none. | [D] (discretionary skipping) |
| #2256 / #4213 | 2019 / 2021 | «یک تریدر استراتژی از قبل معلوم هست و بدون هیچ سوال و ابهامی و خالی از هرگونه احساس وارد ترید میشه» | The strategy is fixed in advance; no feelings. | supports mechanical rules |
| #4447 | 2021-07-14 | «همچیز از قبل در👈 دفترچه 👉 نوشته شده» | Everything is written in the strategy notebook beforehand. | — |
| #4499 / #5146 | 2021-07-17 / 08-09 | journal + money-management Excel; «هر ۱۰ روز چک میکنم» | Keep a journal and review it every 10 days. | [O] logging |
| #6537 | 2021-10-13 | «ناراحت نشین اگر با ریسک به ریوارد ۲ ۷ بار حد ضرر خوردین چون کافیه ۳ دفعه سود کنید» | Don't despair after 7 losses at 2R; 3 wins bring you back to flat. | Implies **no** rule that stops trading after N losses beyond the 24h cooldown. |
| #6631 | 2021-10-18 | «هر مقدار مطلبی که بلدین رو کامل... بلد باشید... نسبت ریسک به ریوارد و وین ریت روش داشته باشید» | Master a few setups and know each one's R:R and win rate. | supports per-setup stats |
| #4821 | 2021-07-28 (KZ) | «استراتاژي تون رو تو دمو امتحان كنين و بعد اگه سود ده بود فقط طبق اون عمل كنين» | Test in demo first; once profitable, follow only the strategy. | — |

---

## 12. Contradictions and evolution over time
1. **Risk per trade.**
   - 2019-07: "2–4% per position" (probably margin) and ≤10–15% per move.
   - 2019-08 → 2019-12: 3% risk.
   - 2020-07 advert: max 1%.
   - 2021: 3% cap, with logs showing 1–3% realised and one 4% case (#4300).
   - 2021-10: 0.5–1% for nervous traders.
   - The steady rule is ≤3% (=EDU).
2. **Leverage.** 2019: max 10 (uses 7). 2020: example at 5, with isolated margin required. 2021: 10–20 with tiny 15m stops. The constraint shifted from a leverage cap to risk-based sizing.
3. **Stop size.** Era 1 implies ≥2%. #4448 (2021-07) calls 0.6% "wrong". The 2021 VIP used 0.2–0.4% and "<1%" on 15m. The two are inconsistent; normalise by ATR.
4. **Scaling in vs no averaging down.** #1750 (2019) scales into a short over a 7% adverse range with 3–4 orders. #4569 (2021) says don't keep adding when the market goes against you. #5564/#5572 (2021) allow adding **only in profit**, at new higher lows. Use the 2021 rule.
5. **Number of positions.** 2 spot coins max (#3877); max 2 crypto positions (#4588); "prefer one coin" (#3950). Against these, many concurrent VIP signals and hedges (#4227).
6. **First partial.** At 2R close 30% + stop to entry (#5024, #5797, =EDU). Variants: 50% at TP1 (#6194); nothing at 2R, 50% at 5R (#6337); 30% at 5R (#4583). The 2R rule is the stated default; the others are per-signal discretion.
7. **Cooldowns.** 24h after 3 stops (#4579, =EDU) vs 1 week after a large loss *or profit* (#4563, team post). Both can be applied.
8. **Min R:R.** Constant at 2 from 2019-08 to 2021-12 (crypto); 3 for forex (#5853). No contradiction.
9. **Trend filter for BTC swing longs.** Explicit only in late 2021 (#6580: no buys until the trend turns up). Earlier the indecision-candle trigger was taken at support without a stated trend condition. Treat it as an optional filter and test both.

---

## 13. Proposed baseline backtest built only from these rules

- **Universe.** BTCUSDT + top-10/top-100 USDT perpetuals with a liquidity filter. Alts vs BTC is chosen by the BTC.D/TOTAL2 slope filter (§7).
- **Timeframes.** HTF trend and zones on 1D/4H; setups on 1H/4H; optional 15m entry.
- **Zones.** Pivot S/R from HTF swings (fractal n=3–5) with ≥2 touches, merged within 0.25–0.5 ATR, plus trendlines from the last two pivots.
- **Setups (whitelist).**
  - A = indecision candle at a zone, stop-order entry beyond its extreme, stop at the other extreme.
  - B = break (close beyond) → pullback → strong-body high-volume candle, stop under the pullback shadow.
  - Nothing else.
- **Filters.**
  - Planned TP1 (next opposing zone) must be ≥2R, or skip.
  - Optional HTF Dow trend alignment.
  - Skip longs after a ≥X% 24h rally.
  - No entries inside a tight range box except on a breakout + pullback.
  - Optional RSI(14) momentum veto.
- **Sizing.** `risk = 3%` (grid 1/2/3), `notional = equity·risk/stop%`, leverage ≤10–20 used only for the margin check.
- **Portfolio.** `max_positions = 2`. Total open risk ≤3%, where positions with stop ≥ entry count as 0 risk. Daily loss limit 3%.
- **Exits.** At 2R close 30% and move the stop to entry. Remainder: swing-trail on the entry TF, cap 20–30R, or fixed TP2 at 5R (grid).
- **Cooldowns.** 24h after 3 consecutive losses; optional 7-day pause after a ≥10R win or a ≥3% daily loss.

---

## Summary: the most important codable rules

1. **Stop required, set before entry** (#2228, #2296, #2665). Never trade without one. [M]
2. **Risk ≤3% of equity per trade** (#2228, #2493, #4297, #4443, #5560). Size from stop distance: `notional = equity × risk / stop%`. Realised risk was often 1–1.5%; test {1, 2, 3}%. =EDU. [M]
3. **Minimum 2R to the first target** in crypto, 3R in forex (#2228, #4443, #5024, #6337, #5852, #5853); TP1 is "always 2R". **No discretionary close before +2R** (#4043). =EDU. [M]
4. **At +2R close about 30% (30–40%) and move the stop to entry**, then let the rest run to about 5R or trail it to 10–30R (#5024, #5797, #5853, #5189). Variants: 50% at TP1 (#6194); 50% at 5R (#6337). =EDU. [M]/[O]
5. **Only two setups** (#4447): (A) an indecision/reversal candle at S/R or a trendline, entered with a stop order beyond its high/low after it closes, stop at its other extreme (#3935, #4327, EDU#83/84); (B) an S/R break → pullback → strong-body high-volume candle, stop under the pullback shadow (#5518, #5189). Candle signals count only at S/R or trendlines (#4325, #5327). =EDU. [M]/[O]
6. **Max 2 concurrent crypto positions** (#4588); spot max 2 coins (#3877). Freeing risk by moving the stop to entry lets a new trade open (#4583). Total and daily loss ≤3% (#5864). [M]/[O]
7. **Leverage only for margin**; historically max 10 (#1750), isolated margin and no cross (#3365). [M]
8. **Stop at structural invalidation**, beyond the shadow / swing / zone, "not easy to hit"; not absurdly wide or tight (#4448, #5238, #5572). Swing trades use a **close-based** stop: daily close beyond the level (#6099, #6580). [O]
9. **Cooldown: 24h after 3 stop-losses, no revenge trades** (#4579). =EDU. Optional 1-week pause after a very large win or loss (#4563). [M]/[O]
10. **Market filters.** BTC.D down + TOTAL2 up → trade alts; BTC.D up → trade BTC (#4523). After a BTC leg, BTC ranging → alt rotation (#5080, #6491). Don't chase a coin that already pumped (#4610). No news trading (#4522, #4610). Top-100 coins only (#4746). [O]
11. **Trend gate for longs.** "No buy until the trend turns up" (#6580). Confirm patterns before entering (#4845). Higher-timeframe zones outrank lower ones; lower TFs have more fakes (#5515, #6778). [O]
12. **RSI(14) on closed candles as momentum**: <30 means sharp selling, >70 means sharp buying; not a mean-reversion signal (#7354, #7770). Volume "good" ≈ ≥1.2–1.5× its 20-bar average (proposed). **No MA lengths are given anywhere in 2019–2021.** [O]
