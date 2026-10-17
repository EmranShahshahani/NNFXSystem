#!/usr/bin/env python3
"""Extract trade calls / setups from Trade City Pro (@tradecity_pro), 2018-2021.

Input : data/cache/telegram/main_signals_A_2018_2021.jsonl  (pre-filtered subset)
        data/cache/telegram/main_all.jsonl                  (full archive, for follow-ups)
Output: signals_2018_2021.csv            (one row per call leg)
        signals_2018_2021_review.txt     (auto-parse vs. text + follow-up candidates, for manual review)
        signals_2018_2021_stats.json     (aggregates used in signals_2018_2021.md)
        signals_2018_2021_archive_supplement.csv  (call-like archive posts NOT in the input; auto-parsed only)

Pipeline
  1. normalise text (Persian/Arabic digits, Arabic letters, thousands separators)
  2. de-duplicate reposts / truncated forwards / "pinned «...»" copies -> canonical post
  3. classify each canonical post (call / result / follow-up / commentary / market-data / promo / image-only)
  4. auto-extract fields from the text with regexes
  5. apply MANUAL review overrides (keyed by post id) -> final legs
  6. search the full archive for follow-ups (same asset, outcome words, within FOLLOWUP_DAYS)
     -> candidates written to the review file; verified outcomes are in MANUAL_OUTCOME
  7. write CSV + stats

Rules: no value is invented. If a field is not in the text it stays blank. Values read off a chart
image are never filled in (the image is not in the archive). Manual overrides only transcribe what
the text says, or split a multi-scenario post into legs.

Run:  python3 extract_signals_2018_2021.py
"""
from __future__ import annotations

import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # /home/user/NNFXSystem
SRC = ROOT / "data/cache/telegram/main_signals_A_2018_2021.jsonl"
ARCHIVE = ROOT / "data/cache/telegram/main_all.jsonl"
OUT_CSV = HERE / "signals_2018_2021.csv"
OUT_REVIEW = HERE / "signals_2018_2021_review.txt"
OUT_STATS = HERE / "signals_2018_2021_stats.json"
OUT_SUPP = HERE / "signals_2018_2021_archive_supplement.csv"
URL = "https://t.me/tradecity_pro/{}"
FOLLOWUP_DAYS = 30

COLUMNS = [
    "post_id", "date_utc", "symbol", "timeframe", "side", "setup_type", "entry", "entry_type",
    "stop", "targets", "stated_rr", "conditions", "outcome_reported", "confidence",
    # extra columns (not requested, but useful and documented in the .md)
    "leg", "url", "risk_pct", "stop_pct", "rr_tp1_calc", "n_targets", "completeness", "entry_mode",
    "call_origin", "repost_ids", "has_photo",
]

# --------------------------------------------------------------------------------------------
# 1. normalisation
# --------------------------------------------------------------------------------------------
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_LETTERS = str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی", "ة": "ه", "٫": ".", "٬": ",", "،": "،",
                          "‌": " ", "‏": "", "‎": ""})


def norm(text: str) -> str:
    t = (text or "").translate(_DIGITS).translate(_LETTERS)
    # thousands separators: 3,138,144 / 10,000,000 -> no comma (only when groups of exactly 3 digits
    # follow and nothing numeric is glued on; "8120 ,8145" lists have a space and are untouched)
    t = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", t)
    return t


def squash(text: str) -> str:
    """Key for duplicate detection."""
    t = norm(text)
    t = re.sub(r"^Trade City Pro ™️ pinned «", "", t)
    t = t.rstrip("»").rstrip()
    t = t.rstrip("…").rstrip(".").rstrip()
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


# --------------------------------------------------------------------------------------------
# 2. load + de-duplicate
# --------------------------------------------------------------------------------------------
def load(path: Path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def dedup(rows):
    """Return canonical posts (first occurrence) with a list of repost ids.

    A post is a repost if its squashed text equals, or is a prefix (>= 40 chars) of, the squashed
    text of an earlier canonical post, or vice versa (an earlier truncated copy, a later full copy).
    """
    canon = []  # list of dict(row, key, reposts)
    for r in sorted(rows, key=lambda x: x["id"]):
        k = squash(r["text"])
        hit = None
        for c in canon:
            ck = c["key"]
            if k == ck or (len(k) >= 40 and ck.startswith(k)) or (len(ck) >= 40 and k.startswith(ck)):
                hit = c
                break
        if hit is None:
            canon.append({"row": r, "key": k, "reposts": [], "photo_any": r["has_photo"]})
        else:
            hit["reposts"].append(r["id"])
            hit["photo_any"] = hit["photo_any"] or r["has_photo"]
            if len(k) > len(hit["key"]):  # keep the fullest text, but the earliest id/date
                hit["full_text"] = r["text"]
                hit["key"] = k
    for c in canon:
        c.setdefault("full_text", c["row"]["text"])
    return canon


# --------------------------------------------------------------------------------------------
# 3. classification
# --------------------------------------------------------------------------------------------
RE_MARKET = re.compile(r"(?i)(liquidated|longs paying shorts|shorts paying longs|longs vs shorts|"
                       r"^long short|liquidations in the last day|bitfinex longs)")
RE_RESULT = re.compile(r"(?i)(^#results?\b|^#result|^#log\b|^pnl\s*:|برایند عملکرد|#results\b|"
                       r"سود تحلیل|سیگنال داده شده که)")
RE_LONG = re.compile(r"(?i)(لانگ|\blong\b|\bbuy\b|خرید|بخرید|buy zone|long zone|\bbuy stop|stop buy|استاپ بای|"
                     r"افزایش حجم|#long)")
RE_SHORT = re.compile(r"(?i)(شورت|شرت|\bshort\b|\bsell\b|sell zone|stop sell|استاپ سل|#short)")
RE_LEVEL = re.compile(r"\d")


def classify(text: str, has_photo: bool) -> str:
    t = norm(text).strip()
    tl = t.lower()
    if len(re.sub(r"\s|#\w+", "", t)) < 15 and has_photo:
        return "image_only"
    if RE_MARKET.search(t):
        return "market_data"
    if RE_RESULT.search(tl):
        return "result"
    if RE_LONG.search(t) or RE_SHORT.search(t):
        return "call_candidate"
    return "commentary"


# --------------------------------------------------------------------------------------------
# 4. automatic field extraction
# --------------------------------------------------------------------------------------------
NUM = r"\d+(?:\.\d+)?"

SYMBOL_ALIASES = {
    # generic names -> normalised symbol. Era-specific mapping is done in norm_symbol().
    "بیتکوین": "BTC", "بیت کوین": "BTC", "بیت": "BTC", "btc": "BTC", "xbt": "XBTUSD",
    "اتریوم": "ETH", "ریپل": "XRP",
}


def norm_symbol(raw: str, date: str) -> str:
    s = raw.strip().lstrip("#").upper().replace("-", "").replace("_UPDATE", "")
    if s in ("XBT", "XBTUSD"):
        return "XBTUSD"
    if s in ("BTC", "بیتکوین", "بیت"):
        return "BTCUSDT" if date >= "2021" else "BTCUSD"
    return s


RE_HASHSYM = re.compile(r"#(\d?[A-Za-z]{2,10}(?:[A-Z]\d{2}|usdt|usd|btc|busd)?)\b", re.I)
SKIP_TAGS = {"SL", "SPOT", "FOREX", "BINANCE", "TIP", "LONG", "SHORT", "WATCH", "DAILY", "WEEKLY", "RISKY", "VIEW", "RESULT", "RESULTS", "VIP",
             "MONTHLY", "BITMEX", "LOG", "TIP", "4H", "1H", "15M", "4HOURS", "RISKYSHORT", "SHORT", "BUY"}


def find_symbol(t: str, date: str) -> str:
    for m in RE_HASHSYM.finditer(t):
        tag = m.group(1).upper()
        if tag in SKIP_TAGS or tag.startswith("RISKY"):
            continue
        return norm_symbol(tag, date)
    m = re.search(r"(?i)\b(?:buy|long|sell|short)\s+(btc|xrp|ada|eos|eth|trx|bch|ltc)\b", t)
    if m:
        return norm_symbol(m.group(1), date)
    if re.search(r"بیت ?کوین|بیتکوین", t):
        return norm_symbol("BTC", date)
    if "اتریوم" in t:
        return "ETH"
    return ""


def find_timeframe(t: str) -> str:
    tl = t.lower()
    pats = [
        (r"15 ?(?:min|مین|دقیقه)|#15m\b|۱۵ مین", "15m"),
        (r"30 ?(?:min|مین)", "30m"),
        (r"\b1 ?(?:ساعته|ساعت)\b|یک ساعته|#1h\b|کندل 1 ساعت|1 ساعته", "1h"),
        (r"4 ?(?:ساعته|ساعت)|#4h(?:ours)?\b|4ساعته", "4h"),
        (r"#daily|روزانه|tf ?: ?1d|کندل دیلی|دیلی", "1D"),
        (r"#weekly|هفتگی", "1W"),
    ]
    for p, tf in pats:
        if re.search(p, tl):
            return tf
    return ""


def grab(pattern: str, t: str):
    m = re.search(pattern, t, re.I)
    return m.group(1).strip() if m else ""


def parse_targets(t: str) -> list[str]:
    out: list[str] = []
    # numbered: target1:3902(1%) / TP1: 9590 / tp scalp: 3.541 / تارگت 1 11255
    # an index ("1", "scalp") is only consumed when a separator or another number follows it
    for m in re.finditer(r"(?i)(?:target|tp|تارگت)\s*(?:(?:\d|scalp)\s*[:：]\s*|(?:\d|scalp)\s+(?=\d)|[:：]\s*|\s*)("
                         + NUM + r"(?:\s*-\s*" + NUM + r")?)", t):
        v = m.group(1)
        if re.fullmatch(r"[1-5]", v):  # "target 2 <zone on chart>": the index, not a price
            continue
        out.append(v.replace(" ", ""))
    # list after "Targets:" (space, comma, dash separated)
    m = re.search(r"(?i)(?:targets?|taregt|تارگت ها)\s*[:：]?\s*((?:" + NUM + r"[\s,\-/]*){2,})", t)
    if m:
        vals = re.findall(NUM, m.group(1))
        if len(vals) >= 2:
            out = vals
    # de-dup preserve order
    seen, res = set(), []
    for v in out:
        if v not in seen:
            seen.add(v)
            res.append(v)
    return res


def auto_extract(text: str, date: str) -> dict:
    t = norm(text)
    one = re.sub(r"\s+", " ", t)
    d: dict = {}
    d["symbol"] = find_symbol(one, date)
    d["timeframe"] = find_timeframe(one)
    has_l, has_s = bool(RE_LONG.search(one)), bool(RE_SHORT.search(one))
    d["side"] = "long" if has_l and not has_s else "short" if has_s and not has_l else ("both" if has_l else "")
    d["entry"] = (grab(r"(?:entry(?: price)?|enrty|entery zone|buy zone|sell zone|long zone|buy|long|sell|short)"
                       r"(?:\s+(?!sl\b|tp\b|stop\b|now\b)[a-z]{2,6})?\s*[:：@]?\s*(" + NUM
                       + r"(?:\s*[-_]\s*" + NUM + r")?)", one))
    d["stop"] = grab(r"(?:\bsl(?=[\s:：\d])|stop loss|stoploss|stoop loss|\bstop\b|حد ضرر|استاپ لاس|استاپ)\s*(?:under|above|زیر|بالای)?\s*[:：]?\s*(" + NUM + r"%?)", one)
    d["targets"] = ";".join(parse_targets(one))
    d["risk_pct"] = grab(r"(?:risk|ریسک)\s*[:;]?\s*(" + NUM + r"(?:\s*-\s*" + NUM + r")?)\s*%", one)
    d["stated_rr"] = grab(r"(?:rr|r/r|ریسک به ریوارد|ریوارد ?به ?ریسک)\s*[:]?\s*(" + NUM + r")", one)
    el = one.lower()
    if re.search(r"stop (?:buy|sell|market|limit)|buy stop|استاپ (?:بای|سل)|stop limit", el):
        d["entry_type"] = "stop"
    elif re.search(r"entry\s*:?\s*market|همین الان|همینجا|همین نقطه|در قیمت فعلی", el):
        d["entry_type"] = "market"
    elif re.search(r"لیمیت|limit|اوردر خرید", el):
        d["entry_type"] = "limit"
    elif re.search(r"zone|محدوده \d+ (?:الا|الی|تا)", el):
        d["entry_type"] = "zone"
    else:
        d["entry_type"] = ""
    return d


# --------------------------------------------------------------------------------------------
# 5. MANUAL REVIEW
# --------------------------------------------------------------------------------------------
# Every canonical post in the input was read. Posts that are trade calls get an entry in MANUAL
# with one dict per leg (a leg = one side/entry scenario). Fields given here replace the auto-parse.
# Keys: sym tf side setup entry et stop tg rr cond risk conf origin
#   origin: "signal" = terse numeric signal; "analysis" = prose setup/analysis with an actionable scenario;
#           "example" = didactic example ("not for trading"); "position_note" = author's own position
#           management (signal+analysis are the "public" calls used for statistics);
#   conf: parse confidence (high = all stated numbers unambiguous, medium = some interpretation /
#         prose, low = levels only on chart image or heavily conditional)
# Non-call posts are listed in NONCALL with their category.

def L(**kw):
    """One call leg. Keys: sym tf side setup entry et stop tg rr cond risk conf origin."""
    return kw


S, A, P, X = "signal", "analysis", "position_note", "example"

MANUAL: dict[int, list[dict]] = {
    # ---------------------------------------------------------------- 2019 (BitMEX era, author "Navid")
    1561: [L(sym="XRPM19", side="short", setup="range_breakout", entry="4500", et="stop", tg="4175",
             cond="short after break of 4500, target 4175", conf="medium", origin=A),
           L(sym="XRPM19", side="long", setup="support_resistance", entry="4175", et="limit", tg="",
             cond="then long from 4175 'to the top of the monitor' (joke, no numeric target)", conf="low", origin=A)],
    1607: [L(sym="BTCUSD", side="long", setup="support_resistance", entry="10200-10400", et="zone", stop="10100",
             tg="", cond="buy zone 10400-10200, stop 10100", conf="high", origin=A)],
    1617: [L(sym="BTCUSD", tf="1h", side="short", setup="support_resistance", entry="", et="market", stop="11860",
             tg="11255", cond="short now; stop = 1h close above resistance 11860; TP2 = zone marked on chart (image)",
             conf="medium", origin=A)],
    1634: [L(sym="XRPU19", side="long", setup="range_breakout", entry="", et="market", stop="3800",
             cond="zone broken with full-body candle; author entered long, SL 3800", conf="medium", origin=A)],
    1642: [L(sym="XBTUSD", tf="1D", side="long", setup="pullback", entry="11400", et="", stop="11700", tg="11900",
             cond="Ichimoku: strong breakout from kumo + pullback + strong candle; author's own trade, entry 11400, "
                  "half closed at 11900, stop raised to 11700 (BitMEX price)", conf="medium", origin=P)],
    1659: [L(sym="BTCUSD", side="long", setup="other", entry="11661", et="market", stop="11541", tg="12000",
             cond="'immediate signal': long now at 11661, SL 11541, targets stated only as 'above 12000'",
             conf="medium", origin=A)],
    1660: [L(sym="BTCUSD", tf="1h", side="long", setup="range_breakout", entry="", et="stop", stop="",
             cond="long signal promised after price crosses daily pivot (green line, chart only); scenario void if "
                  "1h closes below prior low (chart)", conf="low", origin=A)],
    1703: [L(sym="BTCUSD", side="long", setup="trendline_break", entry="11100", et="stop", stop="",
             cond="short-term downtrend broke and pulled back; author will not long until a candle closes above 11100",
             conf="medium", origin=A)],
    1734: [L(sym="BTCUSD", side="long", setup="support_resistance", entry="", et="zone", stop="",
             cond="blue zone (chart) OK for spot BTC buy; for leveraged long wait for down-trendline break; "
                  "if zone lost -> 8500 (text truncated)", conf="low", origin=A)],
    1768: [L(sym="XBTUSD", side="short", setup="support_resistance", entry="", et="limit", stop="",
             cond="look for shorts; if 10748 breaks, wait to short at channel top (chart)", conf="low", origin=A)],
    1811: [L(sym="ETHUSD", tf="15m", side="long", setup="range_breakout", entry="", et="stop", stop="",
             cond="long only above the price marked on the 15m chart (image), 'not now'", conf="low", origin=A)],
    2064: [L(sym="XRPU19", side="long", setup="other", entry="2639", et="market", stop="3%", tg="+6%",
             cond="#example 'this post is not for trading': long now, stop 3%, target 6% to illustrate leverage risk",
             conf="high", origin=X)],
    2309: [L(sym="XBTUSD", side="short", setup="trendline_break", entry="", et="stop", stop="9800",
             cond="long not suitable; short if the trend line breaks down, stop 9800", conf="medium", origin=A)],
    2467: [L(sym="ADAU19", side="long", setup="range_breakout", entry="494", et="stop", stop="3%",
             cond="long if candle closes above 494, stop 3%", conf="high", origin=A)],
    2478: [L(sym="XBTUSD", tf="4h", side="long", setup="trendline_break", entry="", et="stop", stop="",
             cond="4-month downtrend broke 17d ago; waiting for 4h reaction (pullback); long/spot buy if black "
                  "trend line breaks, 'reasonable stop'", conf="low", origin=A)],
    2487: [L(sym="EOSZ19", side="short", setup="momentum_rsi", entry="3940-3948", et="zone", stop="4042",
             tg="3902;3883;3853;3830", risk="1.5",
             cond="half in 3940-3948, half below 3920; low-volume green candles, SMA7/25 pressure, RSI fails to "
                  "cross Bollinger mid-line -> small rise then drop", conf="high", origin=A)],
    2498: [L(sym="EOSZ19", side="long", setup="pullback", entry="", et="market", stop="2.5-3%", risk="1.5",
             cond="pullback to broken resistance + SMA99, touching uptrend line; long now, stop 2.5-3%",
             conf="medium", origin=A)],
    2520: [L(sym="TRX", side="long", setup="unstated", entry="196-198", et="zone", stop="193", tg="199;200;202;204",
             cond="bare signal, no rationale (price in sats, BitMEX contract)", conf="high", origin=S)],
    2527: [L(sym="XRPZ19", side="long", setup="indecision_trigger", entry="2953-2957", et="zone", stop="2916",
             tg="2968;2986;3029-3044", risk="2",
             cond="strong support, indecision candle forming, RSI reacted at lower Bollinger band; entry above the "
                  "indecision is risky, conservative entry above trend line", conf="high", origin=A)],
    2540: [L(sym="XBTUSD", tf="4h", side="short", setup="indecision_trigger", entry="7300-7310", et="zone", stop="7500",
             tg="7240;7110;7000", risk="1.5",
             cond="BTC weak; indecision candle under SMA99 on previous 4h candle; failed to break down-trendline",
             conf="high", origin=A)],
    2573: [L(sym="LTCZ19", side="short", setup="unstated", entry="6075", et="", stop="6100",
             tg="6065;6055;6045;6035;6025;6015", cond="bare signal", conf="high", origin=S)],
    2578: [L(sym="TRXZ19", side="long", setup="unstated", entry="194", et="", stop="190",
             tg="196;198;200;202;204;205;207;209;210;211;213", cond="bare signal", conf="high", origin=S)],
    2580: [L(sym="TRXZ19", tf="4h", side="long", setup="ma_signal", entry="192-194", et="zone", stop="187", risk="3",
             cond="'risky entry'; daily triangle support, 4h SMA7 crossing SMA25 up", conf="high", origin=A),
           L(sym="TRXZ19", tf="1h", side="long", setup="range_breakout", entry="196", et="stop", stop="187", risk="3",
             cond="'safe entry after 196' = above 1h SMA99 resistance capping at 195", conf="high", origin=A)],
    2586: [L(sym="XBTUSD", tf="1D", side="short", setup="indecision_trigger", entry="7375", et="stop", stop="",
             cond="BTC in big triangle; daily indecision candle -> risk-takers short when tomorrow's daily candle is "
                  "below 7375", conf="medium", origin=A),
           L(sym="XBTUSD", tf="1h", side="short", setup="pullback", entry="7450-7500", et="limit", stop="3%", risk="1.5",
             cond="1h SMA99 broken, pulling back to it; risk-takers place short orders 7450-7500", conf="high", origin=A)],
    2593: [L(sym="XRPZ19", side="long", setup="unstated", entry="3005", et="zone", stop="2957",
             tg="3020;3040;3050;3070;3090;3110;3130;3150;3170;3190;3210;3220;3240;3260;3280;3300",
             cond="bare signal ('ENTERY ZONE 3005')", conf="high", origin=S)],
    2601: [L(sym="XRPZ19", side="long", setup="range_breakout", entry="3060", et="stop", stop="2981",
             tg="3093;3147;3200", risk="2",
             cond="resistance overhead, good long if passed; RSI pulling back to Bollinger mid; team placed buy order "
                  "at 3060 (order type not stated; above resistance -> treated as stop)", conf="medium", origin=A)],
    2606: [L(sym="ADAZ19", side="long", setup="unstated", entry="509", et="", stop="500",
             tg="512;515;520;525;530;535;540", cond="bare signal", conf="high", origin=S)],
    2630: [L(sym="TRXZ19", side="long", setup="pullback", entry="194-196", et="zone", stop="188",
             cond="#WATCH: long OK on pullback to trend line, poor RR now; if entered 194-196 use stop 188",
             conf="medium", origin=A)],
    2643: [L(sym="XRPZ19", tf="1D", side="long", setup="ma_signal", entry="3071", et="stop", stop="2954",
             cond="daily SMA7 crossed SMA25 up + support candle 2 days ago (team took risky long earlier); "
                  "'safe entry after 3071'", conf="high", origin=A)],
    2737: [L(sym="XBTUSD", side="long", setup="range_breakout", entry="7640", et="stop", stop="7450", risk="2",
             cond="stop-limit buy after 7640, SL under 7450", conf="high", origin=A)],
    2752: [L(sym="XBTUSD", tf="1h", side="short", setup="ma_signal", entry="", et="stop", stop="",
             cond="risky short below 1h SMA99; spot holders stop ~7050 below 4h SMA99", conf="low", origin=A)],
    2792: [L(sym="XRP", side="long", setup="unstated", entry="2620", et="", stop="2450", tg="2640;2655;2675;2690",
             cond="bare signal (photo attached)", conf="high", origin=S)],
    2810: [L(sym="XBTUSD", tf="1D", side="long", setup="pattern", entry="7276-7286", et="zone", stop="6980",
             tg="7450-7550", risk="1",
             cond="inside falling wedge / accumulation; team waits for valid break; for those who want: enter "
                  "7276-7286 (per yesterday's candle), risk <=1%, exit 7450-7550 max", conf="high", origin=A)],
    2818: [L(sym="BTCUSD", side="long", setup="unstated", entry="7230", et="", stop="7000",
             tg="7260;7290;7320;7350;7375;7400;7425;7450;7475;7500;7555", cond="bare signal (photo)", conf="high", origin=S)],
    2819: [L(sym="XRP", side="long", setup="unstated", entry="2640", et="", stop="2450",
             tg="2655;2675;2690;2710;2725;2750;2775;2800", cond="bare signal (photo)", conf="high", origin=S)],
    2834: [L(sym="", side="long", setup="trendline_break", entry="", et="stop", stop="463",
             cond="symbol not in text (chart link only); long on trend break, stop below 463", conf="low", origin=A),
           L(sym="", side="long", setup="support_resistance", entry="463", et="limit", stop="",
             cond="if trend does not break, wait for the 463 zone", conf="low", origin=A)],
    2862: [L(sym="XBTUSD", side="short", setup="unstated", entry="7280-7290", et="zone", stop="7541",
             tg="7215;7145;7085", risk="2", cond="no rationale given", conf="high", origin=S)],
    2867: [L(sym="ADA", side="long", setup="unstated", entry="466", et="", stop="450", tg="470;475;480;485;490",
             cond="'signal-only' post (team does not trade these, <=1% risk, per post 2869)", conf="high", origin=S)],
    2868: [L(sym="EOS", side="long", setup="unstated", entry="3585", et="", stop="3400",
             tg="3600;3620;3640;3660;3680;3700", cond="'signal-only' post (see 2869)", conf="high", origin=S)],
    2878: [L(sym="ADAH20", side="long", setup="unstated", entry="460-461", et="zone", stop="452", risk="2",
             cond="'long at 460-461 suitable again'", conf="high", origin=S)],
    2956: [L(sym="", tf="15m", side="long", setup="trendline_break", entry="", et="market", stop="1.6%", risk="1.5",
             cond="symbol not stated; trend line broken on 15m, long here; targets 'will update'", conf="medium", origin=A),
           L(sym="", tf="15m", side="long", setup="trendline_break", entry="", et="market", stop="3%", risk="1.5",
             cond="second (risky) position with 3% stop", conf="medium", origin=A)],
    2960: [L(sym="XBTUSD", side="long", setup="unstated", entry="8080-8090", et="zone", stop="2%", tg="8213;8344",
             risk="1.5", cond="bare signal", conf="high", origin=S)],
    2985: [L(sym="XBTUSD", tf="4h", side="long", setup="range_breakout", entry="8240", et="stop", stop="3%",
             tg="8410;8525;8808", risk="1.5",
             cond="important resistance 8240; 4h RSI crossed Bollinger mid-line; long if candle closes/holds above 8240",
             conf="high", origin=A)],
    2988: [L(sym="XBTUSD", side="long", setup="unstated", entry="8070-8090", et="zone", stop="8000",
             tg="8120;8145;8190;8225;8250;8275", cond="bare signal + exchange referral link", conf="high", origin=S)],
    3124: [L(sym="XBTUSD", tf="1D", side="long", setup="range_breakout", entry="9450-9470", et="stop", stop="2%",
             tg="9590;9700;9800", rr="1.82", risk="1.5-2",
             cond="if supported on trend line and valid break of 9450, RR 1.82 to 9800", conf="high", origin=A)],
    3135: [L(sym="ETHUSD", tf="1h", side="long", setup="indecision_trigger", entry="178.65", et="", stop="173.1",
             tg="179.1;179.2;180.6", risk="1", cond="indecision candle on trend line, 1h", conf="high", origin=A)],
    3143: [L(sym="XBTUSD", tf="1W", side="long", setup="other", entry="8960", et="market", stop="8.6%", risk="3",
             cond="weekly long, 'a bit risky', leverage 3; lower-risk entry after break of 9200", conf="high", origin=A),
           L(sym="XBTUSD", tf="1W", side="long", setup="range_breakout", entry="9200", et="stop", stop="",
             cond="'less risky place is after the break of 9200'", conf="medium", origin=A)],
    3172: [L(sym="XBTUSD", side="long", setup="pullback", entry="9730-9750", et="zone", stop="2%",
             tg="9830;9900;10000", risk="1-1.5",
             cond="price left long-term range (blue box), TP1 9700 of earlier view hit; now reacting/supported on "
                  "rising trend line", conf="high", origin=A)],
    3173: [L(sym="XBTUSD", side="long", setup="unstated", entry="9805", et="", stop="9650",
             tg="9830;9850;9875;9900;9925;9950;9975;10000", cond="bare signal + referral link", conf="high", origin=S)],
    3174: [L(sym="LTCH20", side="long", setup="unstated", entry="7600", et="", stop="7480",
             tg="7615;7630;7645;7660;7675;7690", cond="bare signal", conf="high", origin=S)],
    3175: [L(sym="XRPH20", side="long", setup="unstated", entry="2898", et="", stop="2800",
             tg="2910;2930;2950;2970;2990;3110;3130;3150;3170",
             cond="bare signal; target list as written (3110 after 2990 probably a typo for 3010)", conf="high", origin=S)],
    3188: [L(sym="ADABTC", side="long", setup="pullback", entry="669", et="limit", stop="648", risk="1.5-2",
             cond="#WATCH at resistance top; chart is Binance ADABTC, converted to BitMEX ~669 'after pullback', stop "
                  "'about 648'", conf="medium", origin=A)],
    3190: [L(sym="XBTUSD", tf="1h", side="long", setup="range_breakout", entry="", et="market", stop="9650", tg="10000",
             risk="1", cond="1h body closed outside the rectangle -> add to position", conf="medium", origin=A)],
    3194: [L(sym="XRPH20", side="long", setup="unstated", entry="2795", et="stop", stop="2727",
             cond="stop-market buy after 2795; targets 'will update'", conf="high", origin=S)],
    3201: [L(sym="XBTUSD", side="long", setup="support_resistance", entry="9900", et="limit", stop="9590",
             tg="10400-10500", risk="1.5-2",
             cond="failed at 10500, back to channel bottom ~9900 -> long, ~3% stop at 9590, TP1 = previous top",
             conf="high", origin=A)],
    3209: [L(sym="XBTUSD", side="long", setup="pullback", entry="8760", et="market", stop="8400", tg="9000;9100",
             risk="1.5", cond="downtrend broken and pulled back; long at current 8760, leverage 5", conf="high", origin=A),
           L(sym="XBTUSD", side="long", setup="range_breakout", entry="8840", et="stop", stop="8600", tg="9000;9100",
             cond="second entry after 8840 ('more certain position')", conf="high", origin=A)],
    3214: [L(sym="ETHUSD", side="short", setup="unstated", entry="229.80", et="", stop="234.50",
             tg="226.90;223.95;220.50",
             cond="#risky; input post has only the targets - entry/SL from archive post 3213 posted the same minute",
             conf="high", origin=S)],
    3225: [L(sym="ETHUSD", side="long", setup="trendline_break", entry="", et="stop", stop="2%",
             cond="#WATCH: long with 2% stop on break of down trend line", conf="medium", origin=A)],
    3230: [L(sym="LTCH20", side="", setup="unstated", entry="7030", et="", stop="2%", risk="1",
             cond="'7030 can be a good entry, 2% stop' - direction not stated in text (chart link only)",
             conf="low", origin=A)],
    3231: [L(sym="XBTUSD", tf="15m", side="long", setup="trendline_break", entry="8810", et="stop", stop="8700", risk="1",
             cond="if 15m trend line breaks, re-enter long or add; stop-buy above 8810", conf="high", origin=A)],
    3251: [L(sym="XBTUSD", side="long", setup="range_breakout", entry="9240", et="stop", stop="8985",
             tg="9300;9400;9480", risk="1.5",
             cond="price at channel top, not heading to bottom; stop-buy at 9240 to join a channel breakout",
             conf="high", origin=A)],
    3289: [L(sym="ETHUSD", side="long", setup="pattern", entry="202.5-202.6", et="zone", stop="196.7",
             tg="208.5;209.6;212.6", risk="1.5",
             cond="inverse head & shoulders at channel bottom, neckline broken and pulled back; stop at previous low",
             conf="high", origin=A)],
    3320: [L(sym="XBTUSD", tf="4h", side="long", setup="pattern", entry="5660", et="stop", stop="4985", tg="5950;6700",
             risk="0.5-1",
             cond="(inverse) head & shoulders on 4h; if neckline breaks with good volume -> 5950 then 6700; leverage 3; "
                  "side from targets above entry", conf="medium", origin=A)],
    3338: [L(sym="XBTUSD", side="short", setup="other", entry="6550", et="", stop="7020", tg="6140;5900;5650",
             risk="0.5",
             cond="#risky-short: author took a 0.5%-risk starter short; will add if channel and SMA99 break",
             conf="high", origin=A)],
    3354: [L(sym="XBTUSD", side="long", setup="support_resistance", entry="6150", et="limit", stop="6000",
             tg="6550;6670;6800", risk="0.5", cond="limit buy at 6150 zone; leverage 3 or 5", conf="high", origin=A),
           L(sym="XBTUSD", side="long", setup="range_breakout", entry="6420", et="stop", stop="6130",
             tg="6550;6670;6800", risk="0.5-1", cond="buy-stop at 6420", conf="high", origin=A)],
    3411: [L(sym="XBTUSD", side="long", setup="trendline_break", entry="", et="stop", stop="",
             cond="#WATCH: long if this trend line breaks", conf="low", origin=A),
           L(sym="XBTUSD", side="short", setup="other", entry="", et="", stop="",
             cond="short if it fails to break and prints a reversal pattern", conf="low", origin=A)],
    3426: [L(sym="XBTUSD", side="short", setup="trendline_break", entry="", et="stop", stop="7500",
             cond="price between two trend lines; if lower rising trend breaks -> short, stop 7500", conf="medium", origin=A),
           L(sym="XBTUSD", tf="4h", side="long", setup="trendline_break", entry="", et="stop", stop="",
             cond="if upper falling trend breaks, wait for (at least 4h) consolidation to find a stop, then long",
             conf="low", origin=A)],
    3456: [L(sym="LTCM20", side="long", setup="support_resistance", entry="", et="zone", stop="",
             cond="'good support zone for long' (levels on chart)", conf="low", origin=A)],
    3472: [L(sym="ETHUSD", tf="1h", side="short", setup="ma_signal", entry="", et="stop", stop="216", tg="203.15",
             risk="2",
             cond="short if 1h closes below SMA99, or wait for pullback; 4h SMA7/SMA25 bearish cross, or wait for 4h "
                  "close below SMA25", conf="medium", origin=A)],
    3509: [L(sym="ETHUSD", side="short", setup="pattern", entry="", et="stop", stop="215", tg="200;185",
             cond="triangle compressed under resistance; short after break + lower high", conf="medium", origin=A),
           L(sym="ETHUSD", side="long", setup="pattern", entry="", et="stop", stop="",
             cond="long after break of triangle and support zone + higher low", conf="low", origin=A)],
    3514: [L(sym="XBTUSD", side="short", setup="range_breakout", entry="", et="stop", stop="",
             cond="in rectangle, RSI falling, BTC dominance down; short at downside break (stop above rectangle) or on "
                  "pullback (stop above pullback, better RR); break also takes out SMA99", conf="low", origin=A)],
    3571: [L(sym="XBTUSD", side="long", setup="range_breakout", entry="", et="stop", stop="",
             cond="back inside rectangle; no long because of downtrend overhead; long probably after break of this zone",
             conf="low", origin=A)],
    3595: [L(sym="FETBTC", side="long", setup="range_breakout", entry="250", et="stop", stop="", rr="1",
             cond="accumulation after drop; low-risk entry after break of pink line, earlier entry after yellow line; "
                  "stop for 'entry after 250' on chart; RR 1 to pink line, ~30% after it", conf="low", origin=A)],
    3596: [L(sym="DUSKBTC", tf="4h", side="long", setup="trendline_break", entry="", et="stop", stop="273",
             tg="318;350;400;430",
             cond="daily downtrend broken, corrected to 50% fib; buy on break of pink 4h trend line; targets by fib "
                  "extension", conf="medium", origin=A)],
    3661: [L(sym="ALGOBTC", side="long", setup="fib_retracement", entry="2280", et="limit", stop="2210",
             tg="2430;2520;2700;3000", risk="1",
             cond="long-term downtrend broken, correcting; buy order at 61.8% retracement + price support, 3% stop",
             conf="high", origin=A)],
    3665: [L(sym="XBTUSD", tf="1W", side="long", setup="range_breakout", entry="10200", et="stop", stop="",
             cond="weekly close looks bearish (volume/price divergence); holders stop below 9200; long only after "
                  "10200; downside targets 8350, 7800, 6800", conf="medium", origin=A)],
    3682: [L(sym="ARDRBTC", tf="1D", side="long", setup="ma_signal", entry="", et="", stop="", risk="1",
             cond="held above daily SMA99; stop and target on chart only; side implied (bullish, spot BTC pair)",
             conf="low", origin=A)],
    3690: [L(sym="ONTUSDT", side="long", setup="unstated", entry="0.5746", et="", stop="0.5615",
             tg="0.5905;0.6127;0.63", cond="SL 'under 0.5615'", conf="high", origin=S)],
    3706: [L(sym="ETHUSDT", side="short", setup="unstated", entry="246-247", et="zone", stop="250", risk="3",
             cond="SL 'above 250'; target pending whether 234 floor breaks", conf="high", origin=S)],
    3707: [L(sym="BATUSDT", side="long", setup="support_resistance", entry="0.2472", et="", stop="0.2440",
             tg="0.2528;0.2583", risk="1", cond="#risky: on new support zone, risk <=1%", conf="high", origin=S)],
    3709: [L(sym="QTUMUSDT", side="long", setup="unstated", entry="1.816", et="", stop="1.795", tg="1.850",
             cond="#risky; SL 'under 1.795'", conf="high", origin=S),
           L(sym="QTUMUSDT", side="long", setup="range_breakout", entry="1.835", et="stop", stop="1.795", tg="1.850",
             cond="'better entry after 1.835'; if passed TP1 = 1.850", conf="high", origin=S)],
    3711: [L(sym="LINKUSDT", side="short", setup="unstated", entry="4.455", et="", stop="4.487", tg="",
             cond="#risky; SL 'above 4.487'; target text truncated ('Target a')", conf="high", origin=S)],
    3719: [L(sym="QSPBTC", side="long", setup="unstated", entry="162", et="", stop="154",
             cond="re-entry after earlier call 'went 10% higher'; SL 'below 154'; targets later", conf="high", origin=S)],
    3727: [L(sym="IOTAUSDT", side="short", setup="unstated", entry="2304", et="stop", stop="2352",
             cond="stop-sell 2304 / SL 2352 (prices written without decimal point)", conf="high", origin=S)],
    3765: [L(sym="ETHUSDT", side="short", setup="unstated", entry="235.60", et="stop", stop="240.15", tg="229",
             risk="3", cond="stop-sell; do not close full size at target; companion post: 'if this trend is lost "
                         "ETH will drop sharply' (archive 3767)", conf="high", origin=S)],
    3786: [L(sym="PPTBTC", side="long", setup="unstated", entry="3925", et="stop", stop="3791", tg="4200", risk="2",
             cond="stop-buy", conf="high", origin=S)],
    3789: [L(sym="BTCUSDT", side="short", setup="unstated", entry="9487", et="", stop="9600", tg="9369;9240",
             risk="2", cond="SL 'above 9600'; don't close all at targets; if stopped, trend likely turned up",
             conf="high", origin=S)],
    3800: [L(sym="LINKUSDT", side="long", setup="unstated", entry="4.1030-4.1160", et="zone", stop="4.0492",
             tg="4.2202", risk="1", cond="bare signal", conf="high", origin=S)],
    3809: [L(sym="BATUSDT", side="short", setup="unstated", entry="2324-2334", et="zone", stop="2%", tg="2301;2260",
             risk="1", cond="prices written without decimal point (0.2324...)", conf="high", origin=S)],
    3812: [L(sym="XLMUSDT", side="long", setup="unstated", entry="0.06921", et="", stop="2%", tg="0.07060", risk="1",
             cond="entry written '6921' (decimal point dropped; =0.06921); target 0.07060 given in follow-up post 3813 the same minute, "
                  "'don't close all'", conf="high", origin=S)],
    3821: [L(sym="XTZUSDT", side="long", setup="unstated", entry="2.670", et="", stop="1.5%", risk="1",
             cond="targets 'will update'; watching whether a resistance zone is passed", conf="high", origin=S)],
    3882: [L(sym="TRXBTC", side="", setup="unstated", entry="", et="", stop="",
             cond="'stop and target marked on chart' only - nothing parseable", conf="low", origin=A)],
    3883: [L(sym="COSBTC", side="", setup="unstated", entry="", et="", stop="",
             cond="'stop and target marked on chart' only", conf="low", origin=A)],
    3884: [L(sym="KMDBTC", side="", setup="unstated", entry="", et="", stop="",
             cond="'stop and target marked on chart' only", conf="low", origin=A)],
    3885: [L(sym="WTCBTC", side="", setup="unstated", entry="", et="", stop="",
             cond="'stop and target marked on chart' only", conf="low", origin=A)],
    # ---------------------------------------------------------------- 2021 (Binance USDT-M era, Arshia / Kian / Naseri)
    3905: [L(sym="", tf="15m", side="short", setup="unstated", entry="", et="", stop="",
             cond="setup on 15m chart image only; 'stop very close, use small size'", conf="low", origin=A)],
    3914: [L(sym="BTCUSDT", tf="4h", side="long", setup="candle_trigger", entry="35600", et="stop", stop="",
             cond="not a good time to long (weekly bearish); risky buy if this 4h candle closes above 35600 or next "
                  "candle engulfs it; author only scalps longs until close above 41000", conf="medium", origin=A)],
    3915: [L(sym="BTCUSDT", tf="15m", side="short", setup="unstated", entry="", et="market", stop="0.5%", tg="34920",
             cond="15m short, stop 0.5%; TP1 34920 in follow-up 3916, TP2 withheld (would rather trail)",
             conf="high", origin=S)],
    3924: [L(sym="QTUMUSDT", side="short", setup="unstated", entry="", et="market", stop="7.120", tg="6.98",
             cond="short 'at this point', stop above 7.120; scalp signals, close stops", conf="high", origin=S)],
    3927: [L(sym="", side="long", setup="candle_trigger", entry="", et="market", stop="",
             cond="symbol not stated (follows BTC/QTUM posts): 'if you accept the risk, long with stop below the shadow'",
             conf="low", origin=A)],
    3938: [L(sym="MATICUSDT", side="short", setup="range_breakout", entry="1.2868", et="stop", stop="",
             cond="if 1.2868 support is lost, sharp drop; use stop-sell ...", conf="medium", origin=A),
           L(sym="MATICUSDT", side="short", setup="pullback", entry="", et="limit", stop="",
             cond="... or wait for break + pullback, then short", conf="low", origin=A)],
    3947: [L(sym="LTCUSDT", tf="1D", side="short", setup="pullback", entry="", et="", stop="",
             cond="daily bearish; holders' stop below 125; futures short on lower TF at pullback after break",
             conf="low", origin=A)],
    3964: [L(sym="BTCUSDT", tf="4h", side="short", setup="range_breakout", entry="", et="stop", stop="",
             cond="strong 4h divergence is no reason to long; don't trade last 1/3 of a triangle; stop-sell below "
                  "support possible but stop-hunt risk", conf="low", origin=A),
           L(sym="BTCUSDT", tf="4h", side="long", setup="trendline_break", entry="", et="stop", stop="",
             cond="for upside: on trend break; 36200 important", conf="low", origin=A)],
    3991: [L(sym="", side="", setup="unstated", entry="", et="market", stop="", tg="34800", rr="2",
             cond="symbol/side not in text: 'entry here could be good; TP1 at RR 2, TP2 34800, TP3 hold & make "
                  "risk-free'", conf="low", origin=S)],
    3995: [L(sym="DOTUSDT", tf="15m", side="long", setup="candle_trigger", entry="", et="stop", stop="",
             cond="long if 15m closes green; stop on chart; exit when a lower high forms", conf="medium", origin=S)],
    4014: [L(sym="ZILUSDT", tf="15m", side="long", setup="candle_trigger", entry="", et="market", stop="",
             cond="#risky: long right here, stop below the 15m candle", conf="medium", origin=S)],
    4025: [L(sym="BTCUSDT", side="short", setup="range_breakout", entry="30170", et="stop", stop="30777",
             cond="risky short: stop-sell below 30170, SL above 30777 once filled; leverage <=10; target later",
             conf="high", origin=S),
           L(sym="BTCUSDT", side="short", setup="support_resistance", entry="", et="", stop="",
             cond="author prefers to short after rejection from the blue box (chart)", conf="low", origin=A)],
    4029: [L(sym="ETHUSDT", side="short", setup="unstated", entry="", et="market", stop="1740",
             cond="risky short with stop 1740; respect size/leverage", conf="medium", origin=S)],
    4042: [L(sym="BTCUSDT", side="short", setup="unstated", entry="", et="", stop="3%", rr="2",
             cond="stop ~3%, leverage 5; RR-2 target marked on chart (image)", conf="medium", origin=S)],
    4053: [L(sym="BTCUSDT", side="long", setup="pullback", entry="", et="market", stop="", tg="33200", rr="2",
             cond="stop on chart; entry is risky - in pullback but needs support; safer after a higher low; TP1 at "
                  "RR 2 = 33200, TP2 hold (side from 'higher low' wording + TP above)", conf="medium", origin=S)],
    4096: [L(sym="BTCUSDT", side="short", setup="unstated", entry="", et="market", stop="34700", tg="34150;34030",
             cond="split post: input has only 'Target 3: keep open and lower the stop'; #short / SL above 34700 / "
                  "TP1 34150 / TP2 34030 come from archive posts 4092-4095 (same minute)", conf="medium", origin=S)],
    4111: [L(sym="BTCUSDT", side="long", setup="unstated", entry="", et="market", stop="2%",
             cond="spot buy with 2% stop; author buys BTC with 30% of his USDT", conf="medium", origin=A)],
    4138: [L(sym="BTCUSDT", tf="4h", side="long", setup="range_breakout", entry="35000", et="stop", stop="",
             tg="36500;40000-42000",
             cond="(Kian) 4h fighting 35000; if 4h closes above, broken; wait for 4h close before entering",
             conf="medium", origin=A)],
    4145: [L(sym="DOGEUSDT", side="long", setup="unstated", entry="0.26033", et="", stop="0.25808",
             tg="0.26749;0.27700", cond="entry written 'Entry:026033' (decimal point missing)", conf="medium", origin=S)],
    4168: [L(sym="XLMUSDT", side="long", setup="pullback", entry="", et="", stop="",
             tg="0.27894;0.29390;0.30333",
             cond="broke falling trend line, pulling back; entry if it holds with a strong candle", conf="medium", origin=A)],
    4170: [L(sym="ADAUSDT", side="long", setup="pullback", entry="", et="", stop="", tg="1.4228;1.4683",
             cond="pulling back to its falling trend line; entry if it holds with a strong candle", conf="medium", origin=A)],
    4173: [L(sym="ICXUSDT", side="long", setup="unstated", entry="0.8012", et="", stop="0.7854", tg="0.8336",
             cond="bare signal", conf="high", origin=S)],
    4220: [L(sym="COMPUSDT", tf="1h", side="long", setup="range_breakout", entry="", et="stop", stop="",
             tg="383.26;414.45", cond="zone broken; long if a 1h candle closes above the zone (chart)",
             conf="medium", origin=A)],
    4229: [L(sym="BTCUSDT", tf="4h", side="long", setup="range_breakout", entry="", et="stop", stop="",
             tg="36500;38000",
             cond="(Kian) end of 4h compression; if it breaks up targets 36500/38000; beware fakeouts after "
                  "compression, wait for consolidation before entry; alt scenario range 34000-35500",
             conf="low", origin=A)],
    4252: [L(sym="ZECUSDT", side="long", setup="unstated", entry="116.50", et="", stop="115.60", tg="118.60;120.20",
             cond="#risky: given only because stop is very close", conf="high", origin=S)],
    4336: [L(sym="BTCUSDT", tf="15m", side="long", setup="range_breakout", entry="33990", et="stop", stop="",
             tg="35000", cond="no longs until a 15m or 1h candle closes above 33990; then towards 35000",
             conf="medium", origin=A),
           L(sym="BTCUSDT", side="short", setup="range_breakout", entry="33550", et="stop", stop="",
             cond="'stop or safe entry for a short is 33550' (ambiguous wording)", conf="low", origin=A)],
    4341: [L(sym="SKYBTC", tf="1D", side="long", setup="unstated", entry="", et="market", stop="15%", risk="3",
             cond="spot buy, 15% stop, targets on chart; lose at most 3% of capital", conf="medium", origin=A)],
    4342: [L(sym="VIABTC", tf="1D", side="long", setup="unstated", entry="", et="market", stop="16%",
             cond="spot buy, daily uptrend started, 16% stop; targets on chart", conf="medium", origin=A)],
    4394: [L(sym="ETCUSDT", tf="1D", side="long", setup="pattern", entry="", et="stop", stop="", tg="60",
             cond="daily converging pattern (support 47 + rising and falling trend lines); upside break -> 60",
             conf="low", origin=A),
           L(sym="ETCUSDT", tf="1D", side="short", setup="pattern", entry="", et="stop", stop="", tg="30",
             cond="downside break -> 30; direction depends on BTC", conf="low", origin=A)],
    4398: [L(sym="ETHUSDT", tf="4h", side="short", setup="pattern", entry="", et="", stop="",
             cond="head & shoulders formed; likely activates if it closes below; better entry on pullback; target on chart",
             conf="low", origin=A)],
    4412: [L(sym="BCHUSDT", tf="1D", side="long", setup="trendline_break", entry="", et="stop", stop="490", tg="610",
             cond="on break of yellow trend line, stop 490, target 610", conf="medium", origin=A)],
    4427: [L(sym="ADAUSDT", tf="1D", side="short", setup="support_resistance", entry="", et="", stop="1.362",
             cond="strong resistance trend + 1.4 zone that it 'cannot break'; 1.362 can be the stop of your short "
                  "(text truncated)", conf="low", origin=A)],
    4658: [L(sym="ENJUSDT", tf="1h", side="long", setup="range_breakout", entry="1.4322", et="stop", stop="",
             tg="1.5446;1.7183;1.9928", cond="if 1.4322 breaks", conf="medium", origin=A),
           L(sym="ENJUSDT", tf="1h", side="long", setup="support_resistance", entry="1.2572-1.2794", et="zone", stop="",
             tg="1.3762", cond="or if supported in zone 1.2572-1.2794 with a good candle", conf="medium", origin=A)],
    4720: [L(sym="BTCUSDT", side="long", setup="range_breakout", entry="35000", et="stop", stop="29000", risk="3",
             cond="#overview: most coins printed strong weekly candles; author buys BTC after 35000, stop 29000, "
                  "risk 3%", conf="high", origin=A)],
    4776: [L(sym="UNIUSDT", tf="1D", side="long", setup="range_breakout", entry="19", et="stop", stop="17",
             tg="23;27", cond="if daily closes above 19 -> TP1 23, TP2 27; buy on break of 19 with stop 17",
             conf="high", origin=A)],
    4777: [L(sym="DOTUSDT", tf="1W", side="long", setup="range_breakout", entry="15.5", et="stop", stop="",
             tg="19.5;27", cond="strong resistance 15.5; on break TP1 19.5, TP2 27", conf="medium", origin=A)],
    4782: [L(sym="XRPUSDT", tf="1D", side="long", setup="range_breakout", entry="0.7140", et="stop", stop="0.6383",
             tg="1.0327", cond="broke daily falling channel without pullback; buy on break of 0.7140 resistance",
             conf="high", origin=A)],
    4827: [L(sym="BTCUSDT", tf="1D", side="long", setup="range_breakout", entry="", et="stop", stop="",
             tg="36200;40000",
             cond="supported at drawn box, reached channel top; on break of this zone TP1 36200 then 40000 "
                  "(text truncated)", conf="medium", origin=A)],
    4848: [L(sym="BTCUSDT", side="long", setup="range_breakout", entry="41000", et="stop", stop="",
             cond="no shorts while above 39400; long suitable after 41000", conf="medium", origin=A)],
    5044: [L(sym="BTCUSDT", tf="1D", side="long", setup="unstated", entry="", et="market", stop="37500", risk="3",
             cond="if you hold no BTC you can buy now with stop 37500 (author holds since 35000)", conf="medium", origin=A),
           L(sym="BTCUSDT", tf="1D", side="long", setup="range_breakout", entry="41600", et="stop", stop="", tg="45000",
             cond="author waits for break of 41600 (current RR not suitable); 45000 if broken", conf="medium", origin=A)],
    5065: [L(sym="BTCUSDT", tf="4h", side="long", setup="trendline_break", entry="", et="", stop="39650", tg="45000",
             cond="position management: holding; new stop = daily close below 39650; trend-line break also a buy; "
                  "pivot 43600", conf="medium", origin=P)],
    5492: [L(sym="BTCUSDT", tf="1W", side="long", setup="range_breakout", entry="49600", et="stop", stop="",
             cond="weekly buy trigger after 49600", conf="medium", origin=A)],
    5493: [L(sym="BTCUSDT", tf="15m", side="long", setup="range_breakout", entry="49400", et="stop",
             stop="daily close < 48000", tg="51000;53000",
             cond="uptrend starts if it holds above 49400; main stop = daily close below 48000", conf="medium", origin=A)],
    5600: [L(sym="XRPUSDT", tf="1D", side="long", setup="candle_trigger", entry="", et="market", stop="1.03",
             cond="if daily closes like this -> bullish; risky buy now with stop below 1.03", conf="medium", origin=A),
           L(sym="XRPUSDT", tf="1D", side="long", setup="range_breakout", entry="1.3", et="stop", stop="", tg="1.6",
             cond="author waits for break of 1.3; target 1.6", conf="medium", origin=A)],
    5607: [L(sym="ETHUSDT", tf="1D", side="long", setup="candle_trigger", entry="", et="market", stop="3050", tg="3700",
             cond="very good daily candle closing; buy with stop 3050 for target 3700", conf="high", origin=A)],
    5702: [L(sym="BTCUSDT", tf="15m", side="long", setup="candle_trigger", entry="48800;49100", et="zone", stop="",
             cond="(Kian) expect 2-4h rest; no long now; after rest, a good 15/30m candle with volume at 48800 or "
                  "49100 is a long", conf="medium", origin=A)],
    5828: [L(sym="BTCUSDT", tf="1D", side="long", setup="range_breakout", entry="50600", et="stop",
             stop="daily close < 49000", tg="53400", cond="if daily closes above 50600", conf="high", origin=A)],
    6008: [L(sym="DOGEUSDT", tf="1D", side="long", setup="trendline_break", entry="", et="stop", stop="",
             cond="wait for break of yellow trend line; 0.25 strong resistance after; 0.16 main support; author "
                  "cannot give a stop (market too emotional)", conf="low", origin=A)],
    6067: [L(sym="USDJPY", tf="4h", side="long", setup="pullback", entry="", et="", stop="",
             cond="moved without correction; wait for a correction to long with a smaller stop; no limit orders",
             conf="low", origin=A)],
    6182: [L(sym="BNBUSDT", tf="4h", side="long", setup="pullback", entry="371", et="zone", stop="", tg="385;396;416",
             cond="broke downtrend and 371, pulling back; long on a supportive candle on lower TF in this zone",
             conf="medium", origin=A)],
    6261: [L(sym="COMPUSDT", tf="4h", side="long", setup="trendline_break", entry="", et="stop", stop="",
             cond="trend line broken; long if it holds above", conf="low", origin=A),
           L(sym="COMPUSDT", tf="4h", side="long", setup="range_breakout", entry="358", et="stop", stop="",
             cond="safer entry: hold above 358", conf="medium", origin=A)],
    6353: [L(sym="BAKEUSDT", tf="4h", side="long", setup="pullback", entry="1.75", et="zone", stop="", tg="1.85;1.93",
             cond="broke downtrend, pulled back, held above 1.75; long on a good candle here", conf="medium", origin=A)],
    6406: [L(sym="XRPUSDT", tf="4h", side="long", setup="range_breakout", entry="", et="market", stop="", tg="1.1264",
             cond="resistance zone broken -> long to 1.1264", conf="medium", origin=A)],
    6449: [L(sym="BTCUSDT", side="long", setup="range_breakout", entry="55400", et="stop",
             stop="daily close < 53500", tg="57000",
             cond="#market_status: above 55400 likely move to 57000; author's own stop = daily close below 53500",
             conf="medium", origin=A)],
    6499: [L(sym="ALGOUSDT", tf="4h", side="long", setup="support_resistance", entry="", et="", stop="",
             tg="1.786;1.927", cond="near support; long on a good candle; if 1.598 not held, next support 1.420",
             conf="medium", origin=A)],
    6517: [L(sym="ADAUSDT", tf="1D", side="long", setup="trendline_break", entry="", et="stop", stop="",
             cond="buy on break of overhead trend line; holders' stop below 2.060", conf="low", origin=A),
           L(sym="ADAUSDT", tf="1D", side="long", setup="range_breakout", entry="2.3", et="stop", stop="",
             cond="author enters only after break of 2.3 (safe entry)", conf="medium", origin=A)],
    6984: [L(sym="BNBUSDT", tf="1D", side="long", setup="range_breakout", entry="700", et="stop", stop="",
             tg="850;1250", cond="at ATH; above 700 OK to buy but stop is far", conf="medium", origin=A)],
    6994: [L(sym="XRPUSDT", tf="1D", side="long", setup="candle_trigger", entry="1.28", et="stop",
             stop="below candle (risky) / below purple box (chart)",
             cond="buying now is risky; if today's daily closes above 1.28, buy with stop below the candle (risky) - "
                  "correct stop below purple box", conf="medium", origin=A)],
    # ---- Nov 2021 two-sided "if above X long / if below Y short" template (Naseri, 4h)
    7031: [L(sym="ETHUSDT", tf="4h", side="short", setup="trendline_break", entry="", et="stop", stop="",
             cond="supported on rising trend line; short after trend-line break", conf="low", origin=A),
           L(sym="ETHUSDT", tf="4h", side="long", setup="range_breakout", entry="", et="stop", stop="",
             cond="long after a new high + consolidation", conf="low", origin=A)],
    7033: [L(sym="ALGOUSDT", tf="4h", side="long", setup="range_breakout", entry="2.048", et="stop", stop="",
             cond="break and hold above 2.048", conf="medium", origin=A),
           L(sym="ALGOUSDT", tf="4h", side="short", setup="range_breakout", entry="1.923", et="stop", stop="",
             cond="hold below 1.923", conf="medium", origin=A)],
    7034: [L(sym="BTTUSDT", tf="4h", side="long", setup="range_breakout", entry="", et="stop", stop="",
             cond="break above this zone (chart); don't trade last 1/3 of a triangle", conf="low", origin=A),
           L(sym="BTTUSDT", tf="4h", side="short", setup="range_breakout", entry="", et="stop", stop="",
             cond="break below this zone (chart)", conf="low", origin=A)],
    7035: [L(sym="CHZUSDT", tf="4h", side="long", setup="range_breakout", entry="", et="stop", stop="",
             cond="rising channel, reacted at mid-channel -> not a long now; long after break of previous high",
             conf="low", origin=A),
           L(sym="CHZUSDT", tf="4h", side="short", setup="range_breakout", entry="", et="stop", stop="",
             cond="short only after break of previous low (shorting inside rising channel not logical)",
             conf="low", origin=A)],
    7060: [L(sym="ALPHAUSDT", tf="4h", side="short", setup="range_breakout", entry="", et="stop", stop="",
             cond="range box: break and hold below previous low", conf="low", origin=A),
           L(sym="ALPHAUSDT", tf="4h", side="long", setup="support_resistance", entry="", et="", stop="",
             cond="good candle at box bottom", conf="low", origin=A)],
    7061: [L(sym="ENJUSDT", tf="4h", side="long", setup="range_breakout", entry="", et="stop", stop="",
             cond="on weekly zone: candle closes above and holds", conf="low", origin=A),
           L(sym="ENJUSDT", tf="4h", side="short", setup="support_resistance", entry="2.64", et="", stop="",
             cond="if it cannot pass the zone, 2.64 suitable for short", conf="medium", origin=A)],
    7089: [L(sym="XLMUSDT", tf="4h", side="long", setup="support_resistance", entry="", et="", stop="",
             cond="near rising trend line; long if supported with a good candle", conf="low", origin=A),
           L(sym="XLMUSDT", tf="4h", side="short", setup="range_breakout", entry="0.3637", et="stop", stop="",
             cond="if 0.3637 lost; next support 0.3630", conf="medium", origin=A)],
    7090: [L(sym="QTUMUSDT", tf="4h", side="short", setup="range_breakout", entry="15.45", et="stop", stop="",
             cond="in box, reacted at mid; short after losing 15.45", conf="medium", origin=A),
           L(sym="QTUMUSDT", tf="4h", side="long", setup="range_breakout", entry="", et="stop", stop="",
             cond="long if candle closes above box mid -> to box top", conf="low", origin=A)],
    7091: [L(sym="VETUSDT", tf="4h", side="short", setup="range_breakout", entry="0.1506", et="stop", stop="",
             cond="channel bottom lost and hold below 0.1506", conf="medium", origin=A),
           L(sym="VETUSDT", tf="4h", side="long", setup="support_resistance", entry="0.1603", et="", stop="",
             cond="strong candle on static support 0.1603", conf="medium", origin=A)],
    7121: [L(sym="ZILUSDT", tf="4h", side="long", setup="range_breakout", entry="", et="stop", stop="",
             cond="at static resistance; break and hold -> higher targets", conf="low", origin=A),
           L(sym="ZILUSDT", tf="4h", side="short", setup="support_resistance", entry="0.09756", et="stop", stop="",
             cond="if rejected, below 0.09756 short", conf="medium", origin=A)],
    7139: [L(sym="ENJUSDT", tf="4h", side="long", setup="trendline_break", entry="", et="stop", stop="",
             cond="break and hold above falling trend line", conf="low", origin=A),
           L(sym="ENJUSDT", tf="4h", side="short", setup="trendline_break", entry="2.82", et="stop", stop="",
             cond="breaks rising trend and candle closes below 2.82", conf="medium", origin=A)],
    7140: [L(sym="XLMUSDT", tf="4h", side="long", setup="range_breakout", entry="0.3913", et="stop", stop="",
             cond="hold above 0.3913", conf="medium", origin=A),
           L(sym="XLMUSDT", tf="4h", side="short", setup="range_breakout", entry="0.367", et="stop", stop="",
             cond="not a short now; short if candle closes below 0.367", conf="medium", origin=A)],
    7141: [L(sym="ATOMUSDT", tf="4h", side="long", setup="range_breakout", entry="32.22", et="stop", stop="",
             cond="risky long on hold above 32.22", conf="medium", origin=A),
           L(sym="ATOMUSDT", tf="4h", side="long", setup="range_breakout", entry="33.78", et="stop", stop="",
             cond="safer long on hold above 33.78", conf="medium", origin=A),
           L(sym="ATOMUSDT", tf="4h", side="short", setup="range_breakout", entry="31.42", et="stop", stop="",
             cond="candle closes below 31.42", conf="medium", origin=A)],
    7142: [L(sym="FLMUSDT", tf="4h", side="long", setup="range_breakout", entry="0.6919", et="stop", stop="",
             cond="hold above 0.6919", conf="medium", origin=A),
           L(sym="FLMUSDT", tf="4h", side="short", setup="range_breakout", entry="0.6650", et="stop", stop="",
             cond="hold below 0.6650", conf="medium", origin=A)],
    # ---- Nov-Dec 2021 "entry market / sl % price / tp scalp / tp1 / tp2 hold" template
    7390: [L(sym="ENJUSDT", side="long", setup="market_scalp", entry="", et="market", stop="3.409", tg="3.541;3.66",
             risk="1", cond="SL 2.60% = 3.409; TP-scalp 3.541, TP1 3.66; author keeps all open to next morning",
             conf="high", origin=S)],
    7402: [L(sym="ZECUSDT", side="long", setup="market_scalp", entry="", et="market", stop="203.9", tg="206;208",
             risk="0.5", cond="SL 0.7% = 203.9; TP-scalp 206, TP1 208, TP2 hold", conf="high", origin=S)],
    7431: [L(sym="TLMUSDT", side="long", setup="market_scalp", entry="0.3826", et="market", stop="0.3799",
             tg="0.3850;0.3894;0.3950", risk="0.5", cond="SL 0.7%; TP-scalp, TP1, TP2", conf="high", origin=S)],
    7624: [L(sym="ETHUSDT", side="long", setup="market_scalp", entry="", et="market", stop="4274", tg="4383;4495",
             cond="SL 1.7% = 4274; TP-scalp 4383, TP1 4495, TP2 hold", conf="high", origin=S)],
    7674: [L(sym="ETHUSDT", tf="1D", side="long", setup="pattern", entry="", et="market", stop="3850",
             cond="(Kian) ETH/BTC broke its flag, daily pullback to 0.077; risky buy here with stop 3850 (~15%); "
                  "safer after a good daily candle", conf="medium", origin=A)],
    7760: [L(sym="IOSTUSDT", side="long", setup="market_scalp", entry="", et="market", stop="3182", tg="3278",
             cond="SL 1% = 3182 (prices without decimal point)", conf="high", origin=S)],
    7761: [L(sym="BTCUSDT", side="long", setup="market_scalp", entry="", et="market", stop="48490", tg="49170;49579",
             cond="SL 0.8% = 48490; TP-scalp 49170; TP1 49579 (written 'TO1')", conf="high", origin=S)],
    7853: [L(sym="ATOMUSDT", tf="4h", side="long", setup="range_breakout", entry="", et="stop", stop="",
             cond="pushing into resistance; break + confirmation -> long", conf="low", origin=A),
           L(sym="ATOMUSDT", tf="4h", side="short", setup="support_resistance", entry="", et="", stop="",
             cond="rejected with a good candle -> short", conf="low", origin=A)],
    8076: [L(sym="IOSTUSDT", side="long", setup="market_scalp", entry="", et="market", stop="0.03462",
             tg="0.03552;0.03655;0.03777", cond="SL 1.85% = 0.03462", conf="high", origin=S)],
    8085: [L(sym="IOSTUSDT", side="long", setup="market_scalp", entry="", et="market", stop="0.035045",
             tg="0.03629;0.038070", cond="SL 2.8% = 0.035045", conf="high", origin=S)],
    8087: [L(sym="MATICUSDT", side="long", setup="market_scalp", entry="", et="market", stop="2.721", tg="2.8;2.89",
             cond="SL 2% = 2.721; TP-scalp 2.8, TP1 2.89, TP2 hold", conf="high", origin=S)],
}

# Stated stop distance (%) for market entries where the text gives both % and price.
STATED_STOP_PCT = {7390: 2.60, 7402: 0.7, 7431: 0.7, 7624: 1.7, 7760: 1.0, 7761: 0.8, 8076: 1.85, 8085: 2.8, 8087: 2.0}

# Outcomes reported in later posts (each follow-up was read). Key = post_id (all legs) or (post_id, leg).
# "probable" = follow-up does not name the symbol or is an aggregate log mapped by symbol.
# Percentages are the channel's own figures (usually on margin with leverage 10, not price move).
MANUAL_OUTCOME: dict = {
    1642: "same post: 50% closed at 11900; stop on remainder raised to 11700",
    2487: "probable: post 2500 lists '#Eosz19 29% (full target)' for the pre-shutdown period",
    (2586, 1): "post 2674: price fell from 7375 'as analysed'; keep stop above black trend line",
    3135: "post 3136 (3 min later): +13% with lev 10 so far, hold; more upside above 187",
    3214: "post 3215 (same minute): TP2 hit, ~23% with lev 10; author closed half",
    3682: "post 3723: TP2 hit, ~7% profit",
    3690: "post 3691 (same minute as call): TP1 hit, ~25% with lev 10",
    3707: "post 3708 (same minute as call): target hit ~20%; post 3773: target hit, ~60% with lev 10",
    3709: "post 3710 (same minute, tagged #qtumbtc): target hit ~20%",
    3711: "probable: post 3712 (same minute, no symbol): TP1 hit ~14%",
    3727: "probable: post 3728 (same minute, no symbol): ~24% profit so far",
    3765: "post 3768: short still open; post 3770: 'the sharp drop happened' (quoted % is for a VIP entry)",
    3789: "post 3790: TP1 hit, ~15% with lev 10; hold or move SL to entry",
    3800: "probable: post 3810 (no symbol): stop hit, -1% of capital",
    3812: "posts 3814/3825: TP 0.07060 hit (~20%), next TP 7170 reached ('37' with lev 10); SL to entry",
    3821: "post 3822 (same minute): +25% with lev 10, partial profit taken, SL moved to 2.695",
    3915: "post 3918: TP1 hit, author holds; weekly log 4036: btcusdt short 65%",
    3924: "weekly log 4036: qtumusdt short 77%",
    (3938, 1): "weekly log 4036: maticusdt short 20%",
    3995: "weekly log 4036: dotusdt long 37%",
    4014: "weekly log 4036: zilusdt long STOP LOSS",
    4053: "post 4082: TP1 33200 hit 'if not stopped', ~17% with lev 10; author holds",
    4173: "probable: log 4317: icxusdt 30% (18% on balance)",
    4220: "probable: log 4317: compusdt sl (-3% on balance)",
    4720: "post 4870: BTC/alts +12-15% since the buy call; move SL to entry",
    4776: "post 5556: ~27% from entry to target (RR ~5); author closed at 23",
    4777: "post 5566: TP1 hit, ~31% from entry",
    4827: "post 4870: both targets 36200 and 40000 hit",
    (5044, 2): "post 5126: BTC reached 45000; author saved profit",
    6449: "post 6580: 57000 box reached after 19 days",
    7390: "post 7400: RR 5 so far, +4% on capital; probable post 7404: 30% closed at TP1, 30% more, RR 6",
}

# Canonical posts that are NOT calls, with category (anything not listed falls back to the auto class).
# Categories: result (performance summary/claim), followup (update on an earlier call), market_data,
# commentary (view/education/warning/promo), image_only.
NONCALL: dict[int, str] = {
    **{i: "followup" for i in (1921, 2674, 3760, 3770, 3790, 3813, 3814, 3916, 3918, 3925, 3930, 4005,
                               4082, 4151, 4870, 5556, 5566, 6068)},
    **{i: "result" for i in (3530, 3541, 3573, 3063, 6341, 7744, 7872)},
    **{i: "commentary" for i in (1574, 1665, 1932, 2226, 2576, 2869, 3291, 3454, 3835, 3913, 4011, 4271,
                                 4285, 4281, 4287, 4315, 4519, 4674, 5780, 5778, 5781, 5782, 4805, 4828, 4833, 4902, 5090, 5151,
                                 5155, 5241, 5251, 5277, 5279, 5291, 5325, 5411, 5491, 5535, 5608, 5645,
                                 5669, 5855, 6016, 6187, 6414, 6489, 6492, 6590, 6665, 6666, 6983, 6996,
                                 7266, 7746, 7811, 3217, 3284, 2945, 4934)},
}

SETUP_TYPES = ["range_breakout", "trendline_break", "pullback", "indecision_trigger", "candle_trigger",
               "fakeout", "momentum_rsi", "ma_signal", "pattern", "support_resistance", "fib_retracement",
               "market_scalp", "unstated", "other"]


# --------------------------------------------------------------------------------------------
# 6. follow-up search in the full archive
# --------------------------------------------------------------------------------------------
ASSET_WORDS = {
    "BTC": [r"\bbtc", r"\bxbt", "بیت ?کوین", "بیتکوین", r"\bبیت\b"],
    "ETH": [r"\beth", "اتریوم"], "XRP": [r"\bxrp", "ریپل"], "ADA": [r"\bada"], "EOS": [r"\beos"],
    "LTC": [r"\bltc", "لایت"], "TRX": [r"\btrx"], "LINK": [r"\blink"], "XLM": [r"\bxlm"],
    "DOGE": [r"\bdoge"], "DOT": [r"\bdot"], "UNI": [r"\buni"], "QTUM": [r"\bqtum"], "MATIC": [r"\bmatic"],
}
RE_OUTCOME = re.compile(r"(?i)(تارگت ?\d? ?(?:اول|دوم|سوم)? ?(?:رو )?(?:زد|خورد)|tp ?\d? ?(?:touch|✅)|✅|"
                        r"حد ?ضرر (?:خورد|خوردیم|فعال)|استاپ (?:خورد|خوردیم|شدیم)|stop(?:ped)?\b|hit sl|"
                        r"ریسک ?فری|risk ?free|سود داد|% ?سود|سود \d|full target|فول تارگت|نقطه ورود|"
                        r"سیو سود|\bresult)")


def base_asset(sym: str) -> str:
    s = sym.upper()
    if s.startswith("XBT") or s.startswith("BTC"):
        return "BTC"
    for a in ASSET_WORDS:
        if s.startswith(a):
            return a
    return re.sub(r"(USDT|USD|BTC|[A-Z]\d\d)$", "", s)


def followups(call_id: int, date: str, sym: str, archive):
    a = base_asset(sym)
    pats = ASSET_WORDS.get(a, [r"\b" + a.lower()])
    rx = re.compile("|".join(pats), re.I)
    t0 = datetime.fromisoformat(date)
    out = []
    for r in archive:
        if r["id"] <= call_id:
            continue
        t = datetime.fromisoformat(r["date"])
        if t - t0 > timedelta(days=FOLLOWUP_DAYS):
            break
        txt = norm(r["text"])
        if rx.search(txt) and RE_OUTCOME.search(txt) and not RE_MARKET.search(txt):
            out.append((r["id"], r["date"][:16], re.sub(r"\s+", " ", txt)[:300]))
    return out


# --------------------------------------------------------------------------------------------
# helpers for derived columns
# --------------------------------------------------------------------------------------------
def first_num(s: str):
    m = re.search(NUM, s or "")
    return float(m.group(0)) if m else None


def mid(s: str):
    vals = [float(x) for x in re.findall(NUM, s or "")]
    if not vals:
        return None
    return sum(vals[:2]) / len(vals[:2])


def stop_pct(entry: str, stop: str):
    if stop and stop.strip().endswith("%"):
        return first_num(stop)
    e, s = mid(entry), first_num(stop)
    if e and s and e > 0:
        return round(abs(e - s) / e * 100, 2)
    return None


def rr_tp1(entry: str, stop: str, targets: str, side: str):
    """Reward/risk to the first target, from the stated numbers only (entry mid-point of a zone)."""
    e, s = mid(entry), first_num(stop)
    tp = first_num(targets.split(";")[0]) if targets else None
    if not (e and s and tp) or targets.startswith("+"):
        return None
    risk = e * s / 100 if stop.strip().endswith("%") else abs(e - s)
    if risk == 0:
        return None
    rew = (tp - e) if side == "long" else (e - tp)
    return round(rew / risk, 2)


def entry_mode(leg: dict) -> str:
    """immediate = market now; resting = limit/zone/unspecified order at a stated price;
    conditional = stop/trigger entry or an entry that depends on a future event without a price."""
    if leg["entry_type"] == "market":
        return "immediate"
    if leg["entry_type"] == "stop":
        return "conditional"
    if leg["entry"]:
        return "resting"
    return "conditional"


def completeness(leg: dict) -> str:
    has_e = bool(leg["entry"]) or leg["entry_type"] == "market"
    has_s, has_t = bool(leg["stop"]), bool(leg["targets"])
    if has_e and has_s and has_t:
        return "complete"
    if has_e and has_s:
        return "entry+stop"
    if has_e and has_t:
        return "entry+target"
    if has_s and has_t:
        return "stop+target"
    if has_e or has_s or has_t:
        return "partial"
    return "direction_only"


# --------------------------------------------------------------------------------------------
# archive supplement: call-like posts of 2019-2021 that are NOT in the pre-filtered input
# --------------------------------------------------------------------------------------------
RE_STRUCT = re.compile(r"(?i)(\b(?:sl|tp\d?|entry|enrty|target ?\d?)\b\s*[:：]?\s*(?:above|under)?\s*\d|"
                       r"حد ?ضرر\s*(?:زیر|بالای)?\s*\d|استاپ\s*(?:لاس)?\s*\d|stop (?:buy|sell|loss)\s*\d|"
                       r"#(?:long|short)\b|\b(?:long|short|buy|sell)\s+\d)")


def archive_supplement(archive, input_rows, input_canon):
    in_ids = {r["id"] for r in input_rows}
    in_keys = [c["key"] for c in input_canon]
    pool = [r for r in archive if "2019" <= r["date"][:4] <= "2021" and r["id"] not in in_ids]
    out = []
    for c in dedup(pool):
        r, k = c["row"], c["key"]
        if any(k == ik or (len(k) >= 40 and ik.startswith(k)) or (len(ik) >= 40 and k.startswith(ik)) for ik in in_keys):
            continue  # repost of an input post
        t = norm(c["full_text"])
        if RE_MARKET.search(t) or RE_RESULT.search(t.lower()) or not RE_STRUCT.search(t):
            continue
        a = auto_extract(c["full_text"], r["date"][:10])
        if not (a["entry"] or a["stop"] or a["targets"]):
            continue
        if re.search(r"(?i)#(?:آموزش|vip|مدیریت_سرمایه)", t) or (not a["side"] and len(t) > 60):
            continue  # education / VIP marketing / prose without a direction
        out.append({"post_id": r["id"], "date_utc": r["date"].replace("+00:00", "Z"), "symbol": a["symbol"],
                    "timeframe": a["timeframe"], "side": a["side"], "entry": a["entry"],
                    "entry_type": a["entry_type"], "stop": a["stop"], "targets": a["targets"],
                    "risk_pct": a["risk_pct"], "stated_rr": a["stated_rr"], "confidence": "auto_unreviewed",
                    "url": URL.format(r["id"]), "repost_ids": ";".join(map(str, c["reposts"])),
                    "has_photo": int(c["photo_any"]),
                    "kind": "fragment" if len(t) < 40 else "structured",
                    "text": re.sub(r"\s+", " ", t)[:300]})
    return out


# --------------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------------
def main():
    rows = load(SRC)
    archive = sorted(load(ARCHIVE), key=lambda r: r["id"])
    canon = dedup(rows)

    review = []
    legs_out = []
    cat_counter = Counter()
    seen_manual = set()
    for c in canon:
        r = c["row"]
        pid, date = r["id"], r["date"]
        text = c["full_text"]
        auto_cat = classify(text, r["has_photo"])
        auto = auto_extract(text, date[:10])
        if pid in MANUAL:
            cat = "call"
        else:
            cat = NONCALL.get(pid, auto_cat)
        cat_counter[cat] += 1
        review.append(f"\n=== {pid} {date[:16]} cat={cat} (auto={auto_cat}) reposts={c['reposts']} photo={c['photo_any']}")
        review.append("TEXT: " + re.sub(r"\s+", " ", norm(text))[:900])
        review.append("AUTO: " + json.dumps(auto, ensure_ascii=False))
        if pid not in MANUAL:
            continue
        seen_manual.add(pid)
        for i, m in enumerate(MANUAL[pid], 1):
            leg = {
                "post_id": pid, "date_utc": date.replace("+00:00", "Z"),
                "symbol": m.get("sym", auto["symbol"]), "timeframe": m.get("tf", auto["timeframe"]),
                "side": m.get("side", auto["side"]), "setup_type": m.get("setup", "other"),
                "entry": m.get("entry", auto["entry"]), "entry_type": m.get("et", auto["entry_type"]),
                "stop": m.get("stop", auto["stop"]), "targets": m.get("tg", auto["targets"]),
                "stated_rr": m.get("rr", auto["stated_rr"]), "conditions": m.get("cond", ""),
                "outcome_reported": MANUAL_OUTCOME.get((pid, i), MANUAL_OUTCOME.get(pid, "")),
                "confidence": m.get("conf", "medium"), "leg": i, "url": URL.format(pid),
                "risk_pct": m.get("risk", auto["risk_pct"]),
                "call_origin": m.get("origin", "public"),
                "repost_ids": ";".join(map(str, c["reposts"])), "has_photo": int(c["photo_any"]),
            }
            assert leg["setup_type"] in SETUP_TYPES, (pid, leg["setup_type"])
            assert leg["side"] in ("long", "short", ""), (pid, leg["side"])
            sp = STATED_STOP_PCT.get(pid) or stop_pct(leg["entry"], leg["stop"])
            leg["stop_pct"] = "" if sp is None else sp
            rr = rr_tp1(leg["entry"], leg["stop"], leg["targets"], leg["side"])
            if rr is None and not leg["entry"] and pid in STATED_STOP_PCT and leg["stop"] and leg["targets"]:
                # market entry: implied fill price from the stated stop price and stop % (derived, not stated)
                sp_, st_ = STATED_STOP_PCT[pid], first_num(leg["stop"])
                implied = st_ / (1 - sp_ / 100) if leg["side"] == "long" else st_ / (1 + sp_ / 100)
                rr = rr_tp1(f"{implied:.6g}", leg["stop"], leg["targets"], leg["side"])
            leg["rr_tp1_calc"] = "" if rr is None else rr
            leg["n_targets"] = len([x for x in leg["targets"].split(";") if x]) if leg["targets"] else 0
            leg["completeness"] = completeness(leg)
            leg["entry_mode"] = entry_mode(leg)
            legs_out.append(leg)
            fu = followups(pid, date, leg["symbol"], archive)
            review.append(f"LEG{i}: " + json.dumps({k: leg[k] for k in COLUMNS[:14]}, ensure_ascii=False))
            for f in fu[:12]:
                review.append(f"   FU {f[0]} {f[1]}: {f[2]}")
    missing = set(MANUAL) - seen_manual
    assert not missing, f"MANUAL ids not canonical posts: {missing}"

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for leg in legs_out:
            w.writerow({k: leg.get(k, "") for k in COLUMNS})
    OUT_REVIEW.write_text("\n".join(review), encoding="utf-8")
    supp = archive_supplement(archive, rows, canon)
    with open(OUT_SUPP, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(supp[0].keys()) if supp else ["post_id"])
        w.writeheader()
        w.writerows(supp)

    # ------------------------------------------------------------------ stats
    pub = [l for l in legs_out if l["call_origin"] in ("signal", "analysis")]
    def cnt(key, data=pub):
        return dict(Counter(l[key] or "(blank)" for l in data).most_common())
    sps = [float(l["stop_pct"]) for l in pub if l["stop_pct"] != ""]
    rrs = [float(l["rr_tp1_calc"]) for l in pub if l["rr_tp1_calc"] != ""]
    srr = [float(l["stated_rr"]) for l in pub if l["stated_rr"]]
    ntg = [l["n_targets"] for l in pub if l["n_targets"]]
    def q(v):
        if not v:
            return {}
        v = sorted(v)
        return {"n": len(v), "min": v[0], "p25": v[len(v) // 4], "median": statistics.median(v),
                "p75": v[(3 * len(v)) // 4], "max": v[-1], "mean": round(statistics.mean(v), 2)}
    by_sym_base = Counter(base_asset(l["symbol"]) for l in pub)
    stats = {
        "input_posts": len(rows), "canonical_posts": len(canon),
        "duplicate_posts": len(rows) - len(canon),
        "canonical_by_category": dict(cat_counter),
        "image_only_in_input": sum(1 for r in rows if r["has_photo"] and len(re.sub(r"\s|#\w+", "", r["text"])) < 15),
        "call_posts": len(seen_manual), "legs_total": len(legs_out), "legs_public": len(pub),
        "legs_by_origin": cnt("call_origin", legs_out),
        "by_setup": cnt("setup_type"), "by_symbol": cnt("symbol"), "by_asset": dict(by_sym_base.most_common()),
        "by_timeframe": cnt("timeframe"), "by_side": cnt("side"), "by_entry_type": cnt("entry_type"),
        "by_year": dict(Counter(l["date_utc"][:4] for l in pub)),
        "by_year_month": dict(sorted(Counter(l["date_utc"][:7] for l in pub).items())),
        "by_completeness": cnt("completeness"), "by_confidence": cnt("confidence"),
        "by_entry_mode": cnt("entry_mode"),
        "completeness_x_mode": dict(Counter(f"{l['completeness']}|{l['entry_mode']}" for l in pub)),
        "by_origin_x_completeness": dict(Counter(f"{l['call_origin']}|{l['completeness']}" for l in pub)),
        "setup_x_side": dict(Counter(f"{l['setup_type']}|{l['side']}" for l in pub)),
        "tf_by_year": {y: dict(Counter(l["timeframe"] or "(blank)" for l in pub if l["date_utc"].startswith(y)))
                       for y in ("2019", "2020", "2021")},
        "side_by_year": {y: dict(Counter(l["side"] or "(blank)" for l in pub if l["date_utc"].startswith(y)))
                         for y in ("2019", "2020", "2021")},
        "stop_pct_by_year": {y: q([float(l["stop_pct"]) for l in pub if l["stop_pct"] != "" and l["date_utc"].startswith(y)])
                             for y in ("2019", "2020", "2021")},
        "stop_pct_by_origin": {o: q([float(l["stop_pct"]) for l in pub if l["stop_pct"] != "" and l["call_origin"] == o])
                               for o in ("signal", "analysis")},
        "risk_pct_dist": dict(Counter(l["risk_pct"] for l in pub if l["risk_pct"])),
        "outcome_posts": sorted({l["post_id"] for l in pub if l["outcome_reported"]}),
        "call_posts_public": len({l["post_id"] for l in pub}),
        "archive_supplement_posts": len(supp),
        "archive_supplement_by_year": dict(Counter(x["date_utc"][:4] for x in supp)),
        "archive_2018_2021_posts": sum(1 for r in archive if "2018" <= r["date"][:4] <= "2021"),
        "archive_2018_posts_nonservice": sum(1 for r in archive if r["date"][:4] == "2018" and "pinned Deleted message" not in r["text"]),
        "archive_photo_short_2018_2021": sum(1 for r in archive if "2018" <= r["date"][:4] <= "2021" and r["has_photo"]
                                             and len(re.sub(r"\s|#\w+", "", r["text"])) < 15),
        "stop_pct": q(sps), "rr_tp1_calc": q(rrs), "stated_rr": q(srr), "n_targets": q(ntg),
        "n_targets_dist": dict(Counter(l["n_targets"] for l in pub)),
        "with_outcome": sum(1 for l in pub if l["outcome_reported"]),
        "setup_by_year": {y: dict(Counter(l["setup_type"] for l in pub if l["date_utc"].startswith(y)))
                          for y in ("2019", "2020", "2021")},
        "completeness_by_year": {y: dict(Counter(l["completeness"] for l in pub if l["date_utc"].startswith(y)))
                                 for y in ("2019", "2020", "2021")},
    }
    OUT_STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: stats[k] for k in ("input_posts", "canonical_posts", "call_posts", "legs_total",
                                             "legs_public", "with_outcome")}, ensure_ascii=False))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(HERE))
    main()
