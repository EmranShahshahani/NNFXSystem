#!/usr/bin/env python3
"""Extract trade calls / setups from the Trade City Pro Telegram channel (@tradecity_pro), 2022-2026.

Inputs (JSON lines with id, date, views, text, has_photo, has_video):
  data/cache/telegram/main_signals_B_2022_2026.jsonl   (pre-filtered signal posts)
  data/cache/telegram/main_all.jsonl                    (full archive; used to recover posts the
                                                         pre-filter missed and to find follow-ups)
Outputs (next to this script):
  signals_2022_2026.csv        one row per (post, side, trigger level); chart-only posts as
                               record_type=chart_only rows
  signals_2022_2026_stats.json summary numbers used in signals_2022_2026.md

Method
  1. Universe = every archive post dated 2022-01-01 .. 2026-12-31 (the B file is a subset; posts the
     B filter missed, e.g. most 2026 "Pair:" posts, are added and flagged in_B_file=0).
  2. Reposts / truncated copies (text ending in "…") are folded into the earliest original.
  3. Text is normalised (Persian/Arabic digits, ٫ decimal, Persian comma decimals, ZWNJ, ي/ك).
  4. Each post is split into clauses; each clause is scanned for a side word (لانگ/شورت/...), price
     numbers and their role (trigger / target / stop / validity level / box edge / RSI level).
  5. Rule-based labels: setup_type, entry_type, confirmations, trigger_role, conditional.
  6. Follow-up search: later posts (<=30 days) for the same symbol that quote the same trigger
     price (±0.15 %) or that are explicit "Update/نتیجه" posts are classified into
     triggered / faked / not-triggered / save-profit / risk-free / stop / RR-reached.
  7. MANUAL dict: hand corrections after reading every extracted row (see bottom of file).
Nothing is invented: a field is blank when the text does not state it.
"""
from __future__ import annotations

import csv
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TG = ROOT / "data" / "cache" / "telegram"
B_FILE = TG / "main_signals_B_2022_2026.jsonl"
ALL_FILE = TG / "main_all.jsonl"
OUT_CSV = HERE / "signals_2022_2026.csv"
OUT_STATS = HERE / "signals_2022_2026_stats.json"

# --------------------------------------------------------------------------- normalisation
P2E = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def norm(t: str) -> str:
    t = (t or "").translate(P2E)
    t = t.replace("ي", "ی").replace("ك", "ک").replace("‌", " ").replace("\xa0", " ")
    t = t.replace("٫", ".").replace("٬", ",")
    t = re.sub(r"(?<=\d)/(?=\d)(?![^\s]*[A-Za-z])", ".", t)  # ۰/۲۳۱۳ -> 0.2313 (not dates like 9/Aug)
    return t


NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)(\s*هزار)?(?![\d])")


def parse_num(s: str, k: str | None) -> float:
    s = s.replace(",", "")
    v = float(s)
    if k:
        v *= 1000
    return v


def fmt(v: float | None) -> str:
    if v is None:
        return ""
    if v == int(v) and v >= 100:
        return str(int(v))
    return ("%.10f" % v).rstrip("0").rstrip(".")


# --------------------------------------------------------------------------- symbols & timeframe
NAME2SYM = {
    "بیت کوین": "BTCUSDT", "بیتکوین": "BTCUSDT", "بیت": "BTCUSDT", "اتریوم": "ETHUSDT", "سولانا": "SOLUSDT",
    "طلا": "XAUUSD", "دوج": "DOGEUSDT", "کاردانو": "ADAUSDT", "لینک": "LINKUSDT", "ترون": "TRXUSDT",
    "هایپ": "HYPEUSDT", "کیک": "CAKEUSDT", "لایت کوین": "LTCUSDT", "آواکس": "AVAXUSDT", "اواکس": "AVAXUSDT",
    "شیبا": "SHIBUSDT", "متیک": "MATICUSDT", "ماتیک": "MATICUSDT", "مانا": "MANAUSDT", "لونا": "LUNAUSDT",
    "اتم": "ATOMUSDT", "فانتوم": "FTMUSDT", "یونی": "UNIUSDT", "سویی": "SUIUSDT", "پامپ": "PUMPUSDT",
    "پندل": "PENDLEUSDT", "ژوپیتر": "JUPUSDT", "گالا": "GALAUSDT", "بایننس کوین": "BNBUSDT",
}
NON_USDT = {"XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "EURGBP", "USDCHF", "NZDCHF", "EURAUD", "NZDUSD",
            "TOTAL2", "BTCD", "OTHERSD", "USDCAD", "AUDUSD", "DXY"}
HASH_STOP = {"TCP", "FUTURES", "VIP", "SHORT", "LONG", "RISKY", "LOG", "مهم", "A", "B", "NEWS", "NCP", "OI",
             "FUNDING_RATE", "BITCOIN", "TRADE", "CRYPTO", "آموزشی", "آزمون", "آموزش"}
TF_HASH = re.compile(r"^(\d+)\s*(m|min|h|d|w|M)$", re.I)


def norm_symbol(raw: str) -> str:
    s = raw.upper().replace(" ", "").replace("/", "")
    s = s.replace("IOSDTUSDT", "IOSTUSDT").replace("USTD", "USDT").replace("DHIBAUSTD", "DHIBAUSDT")
    if s in NON_USDT or s.endswith("USDT") or s.endswith("USD") and len(s) == 6:
        return s
    return s + "USDT"


def find_symbol(t: str) -> str:
    m = re.search(r"Pair\s*:\s*#?([A-Za-z0-9]+)", t)
    if m:
        return norm_symbol(m.group(1))
    m = re.search(r"جفت ارز\s*:?\s*([A-Z]{6})", t)
    if m:
        return m.group(1)
    for h in re.findall(r"#([A-Za-z][A-Za-z0-9_]*)", t):
        hu = h.upper()
        if hu in HASH_STOP or TF_HASH.match(h) or hu in {"DAILY", "WEEKLY", "1D", "4H", "1H"}:
            continue
        return norm_symbol(h)
    m = re.search(r"#(\S+)", t)
    m = re.search(r"\b([A-Za-z]{2,10})\s?usdt\b", t, re.I)
    if m:
        return norm_symbol(m.group(1))
    m = re.search(r"(?:ارز|کوین)\s+([A-Za-z]{2,10})\b", t)
    if m:
        return norm_symbol(m.group(1))
    for name, sym in NAME2SYM.items():
        if name in t[:200]:
            return sym
    return ""


TF_WORDS = [(r"15\s*(?:min|m\b|دقیقه)", "15m"), (r"30\s*(?:min|دقیقه)", "30m"), (r"5\s*دقیقه", "5m"),
            (r"\b1\s*h\b|1\s*ساعت|یک\s*ساعت|یکساعت|1H", "1h"), (r"\b4\s*h\b|4\s*ساعت|چهار ساعت|4H", "4h"),
            (r"\b1\s*d\b|روزانه|daily|1D", "1d"), (r"\b1\s*w\b|هفتگی|weekly|1W", "1w")]


def find_tf(t: str) -> str:
    m = re.search(r"Time\s*Frame\s*:\s*#?(\w+)(?:\s*,\s*#?(\w+))?", t, re.I)
    if m:
        tfs = [x for x in m.groups() if x]
        return "/".join(tf_norm(x) for x in tfs)
    m = re.search(r"TimeFrame\s*:\s*(\w+)", t, re.I)
    if m:
        return tf_norm(m.group(1))
    m = re.search(r"تایم فریم\s*:\s*(\w+)", t)
    if m:
        return tf_norm(m.group(1))
    for h in re.findall(r"#(\w+)", t):
        if TF_HASH.match(h) or h.lower() in {"daily", "weekly"}:
            return tf_norm(h)
    m = re.search(r"#\w+\s+(\d+\s*(?:m|min|h|d)\b)", t, re.I)
    if m:
        return tf_norm(m.group(1))
    m = re.search(r"(?:تایم فریم|تایم)\s*(\d+\s*(?:ساعت|دقیقه)|روزانه|هفتگی|یک ساعت|یکساعت)", t)
    if m:
        return tf_norm(m.group(1))
    return ""


def tf_norm(x: str) -> str:
    x = x.strip().lower().replace(" ", "")
    for pat, tf in TF_WORDS:
        if re.search(pat, x, re.I):
            return tf
    x = x.replace("min", "m")
    return x


# --------------------------------------------------------------------------- vocab
LONG_RE = r"لانگ|longe?\b|long\b|خرید اسپات|خرید ریسکی|برای خرید|استاپ بای|stop ?buy|موقعیت خرید|معاملات لانگ|خرید"
SHORT_RE = r"شورت|شروت|short\b|استاپ سل|پوزیشن سل|موقعیت فروش|معاملات فروش|پوزیشن فروش"
NOT_SIDE = r"حجم خرید|حجم فروش|فشار فروش|فشار خرید|خریدار|فروشنده|اردرهای فروش|اردر های فروش|قدرت خرید|شورت اسکوییز|short squeez|long squeez|شورت ویدیو|شورت ویدئو|youtube\.com/shorts|مومنتوم خرید"
NEG_RE = (r"(?:تریگر|پوزیشن|شورت|لانگ|نقطه ورود)[^/]{0,30}?(?:نیست|نمیده|نمیدن|نمی ?دهد|نمی ?دهند)"
          r"|نمی ?کنم|نمی ?گیرم|نمی ?زنم|نکنیم|نگیریم|نمی ?کنیم|نمیکنیم|معنا(?:ی)? نیست|معنی نداره|سناریو(?:یی)? (?:برای[^/]{0,20})?ندار"
          r"|تریگری? (?:مناسبی )?نداریم|نقطه ورود(?:ی)? (?:شورت|لانگ)?(?:ی)? ?نداره|برنامه ای نداریم|فکر نمی")
BREAK_RE = (r"شکست|بشکن|بشکون|شکسته|بریک ?اوت|break|بالای|بالا ی|زیر|پایین|از دست|تثبیت|trigger|تریگر|تريگر"
            r"|under|above|zire|بعد از|بعد|نقطه ورود|ورود|استاپ بای|استاپ سل|فعال")
TARGET_PRE = r"(?:به سمت|بسمت|تا(?! زمانی| وقتی| موقعی| اینجا| الان)|تارگت|tp\d?\s*:?|هدف|اهداف|نواحی مقاومتی بعدی|مقاومت بعدی|حمایت بعدی|سیو سود)"
STOP_PRE = r"(?:استاپ(?! بای| سل)|حد ضرر|sl\s*[:;]|stop(?! ?buy))"
VALID_PRE = r"(?:تا زمانی که|تا وقتی|تا موقعی که|تا زمانیکه)"


def side_hits(seg: str):
    s = re.sub(NOT_SIDE, " ", seg, flags=re.I)
    out = []
    for m in re.finditer(LONG_RE, s, re.I):
        out.append((m.start(), "long"))
    for m in re.finditer(SHORT_RE, s, re.I):
        out.append((m.start(), "short"))
    return sorted(out)


def split_clauses(t: str):
    # header lines are removed by caller; split on lines, ' / ', ؛ ; and sentence dots
    parts = re.split(r"\n+|\s/\s|؛|;|(?<=[^\d])\.(?=\s|$)|(?<=\s)\.(?=\d\D)|[🔥✅✔️⭐✨💡🔔📊📈📉⛏⚖️🎯🧮✍️🔭🪣🔍🚀💫💼🔽🏦🕯💎💵💨👀🥺🔺🌟⏱❓☹️🔘▫️🐳📌🔸🛑⚡🟠]+", t)
    out = []
    for p in parts:
        if not p or not p.strip():
            continue
        # split before a new side phrase "برای (پوزیشن) لانگ/شورت" / "واسه شورت"
        sub = re.split(r"(?=(?:\s(?:ولی|اما|و))?\s(?:برای|واسه|وسه)\s(?:پوزیشن\s|پوزیش\s)?(?:لانگ|شورت|long|short)(?!\s*(?:باز|ریسکی\s+باز)))", p)
        for s in sub:
            s = s.strip()
            if s:
                # still both sides? split at ' اما '/' ولی ' between them
                hs = side_hits(s)
                if {h[1] for h in hs} == {"long", "short"}:
                    pieces = re.split(r"\s(?=(?:اما|ولی|و اگر|همچنین)\s)", s)
                    out.extend(x.strip() for x in pieces if x.strip())
                else:
                    out.append(s)
    return out


def classify_numbers(seg: str, side_ctx: str | None):
    """Return list of dicts {v, raw, pos, role, tag} for price-like numbers in seg."""
    res = []
    has_rsi = re.search(r"rsi|آر ?اس ?آی", seg, re.I) is not None
    for m in NUM_RE.finditer(seg):
        raw, k = m.group(1), m.group(2)
        a, b = m.start(), m.end()
        pre = seg[max(0, a - 28):a]
        post = seg[b:b + 18]
        pre_l = pre.lower()
        # junk numbers
        if re.match(r"\s*(?:ساعت|دقیقه|روز|ماه|هفته|سال|درصد|%|٪|بار|تا (?:ارز|کوین|تحلیل|سیگنال|ترید|پوزیشن|تارگت)|برابر|x\b|کالری|گرم|کیلو|نفر|میلیون|میلیارد|تایی|تاش|th|st|nd|rd|ام\b|امین|m\b|min|h\b|d\b|w\b|H\b|D\b|W\b|ثانیه)", post):
            continue
        if re.search(r"(?:تایم فریم|تایم|time ?frame|ریسک به ریوارد|ریسک ریوارد|\brr|لوریج|لورج|ساعت|sma|ema|ma|فیبو|fib|قسمت|پارت|روز|#|قانون|شماره|lev(?:erage)?)\s*[:\-]?\s*$", pre_l):
            continue
        if re.search(r"(?:sma|ema)\s*\d*\s*(?:و|,)\s*$", pre_l):
            continue
        if re.match(r"\s*(?:فیبو|fib)", post):
            continue
        try:
            v = parse_num(raw, k)
        except ValueError:
            continue
        if v == 0 or (1900 <= v <= 2035 and "." not in raw and re.search(r"سال|20\d\d\s*$|میلادی", pre + post)):
            continue
        role = None
        if has_rsi and (re.search(r"rsi[^0-9]{0,22}$", pre_l) or re.match(r"\s*(?:در|تو|روی)\s*rsi", post, re.I)
                        or (v in (30, 50, 70) and re.search(r"rsi", seg[max(0, a - 60):b + 40], re.I))):
            role = "rsi"
        elif re.search(r"(?:بین|محدوده|باکس|رنج)[^/\d]{0,25}$", pre) and re.match(r"\s*(?:و|تا|الی|الا|-)\s*\d", post):
            role = "box_lo"
        elif re.search(r"(?:بین|باکس|رنج|محدوده)[^/]{0,40}\d[\d.,]*\s*(?:و|تا|الی|الا|-)\s*$", pre):
            role = "box_hi"
        elif re.search(VALID_PRE + r"[^/\d]{0,30}$", pre):
            role = "valid"
        elif re.search(STOP_PRE + r"[^/\d]{0,22}$", pre_l):
            role = "stop"
        elif re.search(TARGET_PRE + r"[^/\d]{0,18}$", pre_l):
            role = "target"
        else:
            role = "level"
        res.append({"v": v, "raw": raw + (k or ""), "pos": a, "end": b, "role": role})
    return res


def label_setup(seg: str, post: str) -> str:
    s = seg.lower()
    if re.search(r"فیک|fake", s) and re.search(r"(?:فیک (?:بریک ?اوت|بشه|شد|کنیم|کرد|بودن)|در صورت فیک|اگر[^/]{0,40}فیک|fake)", s):
        return "fakeout"
    if re.search(r"sma|ema|میانگین متحرک", s):
        return "ma_pullback"
    if re.search(r"ایندیسیژن|indecision|کندل ستاپ|کندل تایید|شدو", s) and re.search(r"(?:با|همراه)[^/]{0,15}(?:کندل ستاپ|ایندیسیژن|کندل تایید)|کندل ستاپ[^/]{0,30}(?:پوزیشن|ورود)|اگه کندل ستاپی|استاپ بای[^/]{0,20}shadow", s):
        return "indecision_trigger"
    if re.search(r"پولبک|pullback", s) and re.search(r"(?:با|روی|در صورت|بعد از)[^/]{0,20}پولبک|پولبک[^/]{0,30}(?:پوزیشن|ورود|تریگر)", s):
        return "pullback"
    if re.search(r"مثلث|وج|کنج|سر و شانه|سقف دوقلو|کف دوقلو|پرچم|وی پترن|v pattern|کانال|ترند(?! صعودی خودش هست)|خط روند|ترند لاین|trend", s) and not re.search(r"باکس|رنج", s):
        return "pattern"
    if re.search(r"rsi", s) and re.search(r"اوربای|اورسل|over|70|30|50|72|مومنتوم", s):
        return "momentum_trigger_rsi"
    if re.search(BREAK_RE, s, re.I):
        return "range_breakout_trigger"
    return "other"


def confirmations(seg: str, post: str) -> list[str]:
    s = seg.lower()
    c = []
    if re.search(r"حجم|volume|ولوم", s):
        c.append("volume")
    m = re.findall(r"(?:rsi[^/]{0,25}?(?:ناحیه|لول|محدوده)?\s*)(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:در|تو)\s*rsi", s)
    if re.search(r"rsi", s):
        tag = "RSI"
        if re.search(r"اوربای|overbuy|بالای 70|بالا 70", s):
            tag += " overbought(>70)"
        elif re.search(r"اورسل|oversell", s):
            tag += " oversold(<30)"
        lv = [x for pair in m for x in pair if x]
        if lv:
            tag += " level " + "/".join(dict.fromkeys(lv))
        c.append(tag)
    sm = re.findall(r"sma\s*(\d+)(?:\s*(?:و|,)\s*(\d+))?", s)
    if sm:
        c.append("SMA" + "/".join(x for p in sm for x in p if x))
    if re.search(r"کندل ستاپ", s):
        c.append("setup candle")
    if re.search(r"کندل تایید|کندل خوب|انگولف|اینگلف|کندل شکست", s):
        c.append("confirmation candle")
    if re.search(r"تثبیت|ببنده|بسته شدن|کلوز|close|بست", s):
        c.append("candle close beyond level")
    if re.search(r"دامیننس|dominance", s):
        c.append("BTC dominance")
    if re.search(r"سقف و کف بالاتر|کف و سقف بالاتر|کف بالاتر|سقف پایین ?تر|کف و سقف پایین", s):
        c.append("HH/HL or LH/LL structure")
    if re.search(r"برخورد(?:های)? (?:دوم|بعدی|مجدد)|چندبار|دو بار|دوبار|یبار بهش برخورد|برخورد دوم", s):
        c.append("multiple touches")
    if re.search(r"نیویورک|new york", s):
        c.append("New York session")
    if re.search(r"شنبه|آخر هفته|weekend", s):
        c.append("weekend caution")
    if re.search(r"اردر ?بوک|order ?book|اردرهای فروش|اردر های", s):
        c.append("order book")
    if re.search(r"بیت کوین|بیتکوین|btc", s) and not re.search(r"pair\s*btc|دامیننس", s):
        c.append("BTC context")
    return c


def entry_type(seg: str) -> str:
    s = seg.lower()
    if re.search(r"استاپ بای|استاپ سل|stop ?buy|stop ?sell|اوردر استاپ|استاپ اردر", s):
        return "stop"
    if re.search(r"entry market|مارکت باز|همینجا|همین جا|همین محدوده|الان .{0,20}(?:اقدام|لانگ|شورت)", s):
        return "market"
    if re.search(r"limit|لیمیت", s):
        return "limit"
    if re.search(r"محدوده \d[\d.,]* (?:الا|الی|تا) \d", s) and re.search(r"مناسب|ورود|لانگ|شورت", s):
        return "zone"
    if re.search(BREAK_RE, s, re.I):
        return "stop"
    return ""


def break_confirmation(seg: str) -> str:
    s = seg.lower()
    if re.search(r"تثبیت|ببنده|بسته شدن|بسته بشه|کلوز|بست |کندل .{0,15}بالای|کندل .{0,15}زیر", s):
        return "close"
    if re.search(r"استاپ بای|استاپ سل|stop ?buy|شکست|بریک|بشکن|break|بعد از|بعد|under|above|zire|تریگر", s):
        return "break"
    return ""


def trigger_role(seg: str, pos: int, end: int, idx: int, n: int) -> str:
    s = seg
    win = s[end:end + 45] + " " + s[max(0, pos - 30):pos]
    if re.search(r"به ترتیب", s) and n >= 2 and re.search(r"ریسکی", s) and re.search(r"اصلی|مطمئن", s):
        return "risky" if idx == 0 else "main"
    if re.search(r"ریسکی|زودهنگام|زود هنگام|اول(?:ین)? تریگر|اولین|risky", win):
        return "risky/early"
    if re.search(r"اصلی|مطمئن|مطمعن|سیف|safe|تایید", win):
        return "main"
    if re.search(r"ریسکی|risky", s) and n == 1:
        return "risky/early"
    if re.search(r"اصلی|مطمئن|مطمعن|سیف|safe", s) and n == 1:
        return "main"
    return ""


ACTION_RE = (r"پوزیشن|اقدام|وارد|ورود|باز کن|بگیر|بگیرین|بگیرید|تریگر|تريگر|میشه (?:لانگ|شورت)|لانگ (?:گرفت|باز|کن)|شورت (?:گرفت|باز|کن|بگیر)"
             r"|short\b|long\b|longe|zire|بخرید|خرید|استاپ بای|استاپ سل|سل\b|کرد\b|کرد$|بفرمایید|بنمایید|بکنید|بکنین|کنید|کنین")


# --------------------------------------------------------------------------- data
def load(path: Path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def text_key(t: str) -> str:
    t = norm(t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[\s/…]+", "", t)
    return t


def fold_reposts(posts):
    """Map repost/truncated-copy id -> original id (earliest post with same text prefix)."""
    keys = []
    orig_of = {}
    by_prefix = defaultdict(list)
    for p in posts:  # chronological
        t = p["text"] or ""
        if t.startswith("Trade City Pro") and "pinned" in t[:40]:
            orig_of[p["id"]] = -1  # pin notice
            continue
        k = text_key(t)
        if len(k) < 25:
            continue
        trunc = (t.rstrip().endswith("…"))
        pref = k[:40]
        found = None
        for (oid, ok) in by_prefix.get(pref, []):
            if ok == k or (trunc and ok.startswith(k[:-1][: max(30, len(k) - 5)])) or (ok.startswith(k[: len(k) - 5]) and trunc):
                found = oid
                break
            if len(k) > 60 and ok[:200] == k[:200]:
                found = oid
                break
        if found is not None:
            orig_of[p["id"]] = found
        else:
            by_prefix[pref].append((p["id"], k))
    return orig_of


HEADER_RE = re.compile(r"(?im)^.*(?:Pair\s*:|Time\s*Frame\s*:|TimeFrame\s*:).*$|🫥+|🔗\s*لینک چارت.?|لینک چارت.?|https?://\S+|@\w+|LMN Bot.*$|.*جهت دیدن تحلیل های بیشتر.*$|.*برای دیدن تحلیل های روزانه بیشتر.*$|.*روز رایگان.*$|Trading View \|.*$")


def body_text(t: str) -> str:
    t = HEADER_RE.sub("\n", t)
    t = re.sub(r"#(\w+)", lambda m: " " if (TF_HASH.match(m.group(1)) or m.group(1).lower() in {"daily", "weekly", "tcp", "futures"}) else " " + m.group(1) + " ", t)
    return t


# --------------------------------------------------------------------------- extraction
def extract_post(p) -> tuple[list[dict], str]:
    """Return (rows, status) where status in setup / chart_only / no_setup."""
    raw = p["text"] or ""
    t = norm(raw)
    sym = find_symbol(t)
    tf = find_tf(t)
    body = body_text(t)
    clauses = split_clauses(body)
    rows = []
    post_targets, post_stops = [], []
    rr = ""
    m = re.search(r"(?:ریسک به ریوارد|RR|rr)\s*(?:نزدیک|حدود|حدودا|مینیموم)?\s*\(?\s*(\d+(?:\.\d+)?)", t)
    if m:
        rr = m.group(1)
    # explicit English template: "Long Trigger : X / Short Trigger : Y"
    for side, mm in [("long", re.search(r"Long Trigger\s*:\s*([\d.]+)", t, re.I)), ("short", re.search(r"Short Trigger\s*:\s*([\d.]+)", t, re.I))]:
        if mm:
            rows.append(mkrow(p, sym, tf, side, float(mm.group(1)), "range_breakout_trigger", "stop", "break", [], [], None, "", "", rr, "Long/Short Trigger template", "high"))
    if rows:
        return rows, "setup"
    # VIP-style template: "#short Entry market Sl: x Ts: y Tp1: z"
    if re.search(r"(?:entry|sl\s*[:;]).*tp1", t, re.I | re.S):
        side = "short" if re.search(r"short", t, re.I) else ("long" if re.search(r"long", t, re.I) else "")
        sl = re.search(r"sl\s*[:;]\s*([\d.]+)\s*([\d.]+%)?", t, re.I)
        tps = re.findall(r"tp\d\s*:\s*([\d.]+)", t, re.I)
        ts = re.search(r"ts\s*:\s*([\d.]+)", t, re.I)
        r = mkrow(p, sym, tf, side, None, "other", "market" if re.search(r"entry market", t, re.I) else "", "", [float(x) for x in tps],
                  [], float(sl.group(1)) if sl else None, "", "", rr,
                  f"VIP template; SL distance stated {sl.group(2) if sl and sl.group(2) else ''}; trailing/TS {ts.group(1) if ts else ''}".strip(), "high")
        r["conditional"] = "no"
        return [r], "setup"
    # forex position template (2023): "... در موقعیت فروش/خرید قرار گرفته است" (levels only on image)
    mm = re.search(r"در موقعیت (فروش|خرید) قرار گرفته", t)
    if mm:
        st = re.search(r"نوع استراتژی\s*:\s*([^\n]+)", t)
        stype = "pattern" if st and re.search(r"الگو", st.group(1)) else "range_breakout_trigger"
        r = mkrow(p, sym, tf, "short" if mm.group(1) == "فروش" else "long", None, stype, "", "", [], [], None, "", "", rr,
                  f"forex position card; strategy={st.group(1).strip() if st else ''}; levels only on image", "low")
        return [r], "setup"

    for ci, seg in enumerate(clauses):
        hits = side_hits(seg)
        neg = re.search(NEG_RE, seg) is not None
        nums = classify_numbers(seg, None)
        levels = [n for n in nums if n["role"] == "level"]
        targets = [n for n in nums if n["role"] == "target"]
        stops = [n for n in nums if n["role"] == "stop"]
        valid = [n for n in nums if n["role"] == "valid"]
        box = [n for n in nums if n["role"] in ("box_lo", "box_hi")]
        has_break = re.search(BREAK_RE, seg, re.I) is not None
        has_action = re.search(ACTION_RE, seg, re.I) is not None
        sides = []
        if hits:
            sides = list(dict.fromkeys(h[1] for h in hits))
        elif levels and has_break and has_action and re.search(r"پوزیشن|اقدام|تریگر|ورود", seg):
            # infer side from direction words (lower confidence)
            if re.search(r"زیر|از دست|شکست حمایت|حمایت[^/]{0,15}بشکن|شکست کف|کف[^/]{0,10}شکسته", seg):
                sides = ["short?"]
            elif re.search(r"بالای|شکست مقاومت|شکست سقف|مقاومت[^/]{0,15}بشکن", seg):
                sides = ["long?"]
        if not sides:
            continue
        if neg:
            continue
        if re.search(r"صبر کنیم|منتظر (?:تغییر|بمون|باشید|بمانید|بمانیم)|نیاز به زمان", seg) and not levels:
            continue
        if re.search(r"سیو سود|ریسک فری|استاپتون|استاپ ?تون|خارج شید|ببندید|سیو کنید", seg) and not re.search(r"(?:پوزیشن جدید|میتونیم|میتونید|میتونین)[^/]{0,40}(?:باز|پوزیشن)", seg):
            # management sentence about an existing position, not a new call
            if not (levels and has_break and re.search(r"پوزیشن (?:لانگ|شورت) (?:باز|میده)|تریگر", seg)):
                continue
        # assign each level number to nearest side word
        lv_by_side = defaultdict(list)
        if len(sides) == 1:
            for n in levels:
                lv_by_side[sides[0]].append(n)
        else:
            for n in levels:
                best = min(hits, key=lambda h: abs(h[0] - n["pos"]))
                lv_by_side[best[1]].append(n)
        for side in sides:
            lv = lv_by_side.get(side, [])
            sd = side.rstrip("?")
            conf_side = "medium" if side.endswith("?") else "high"
            stype = label_setup(seg, t)
            et = entry_type(seg)
            bc = break_confirmation(seg)
            cf = confirmations(seg, t)
            tg = [n["v"] for n in targets]
            sp = [n["v"] for n in stops]
            vl = fmt(valid[0]["v"]) if valid else ""
            bx = ""
            if len(box) >= 2:
                lo, hi = sorted([box[0]["v"], box[1]["v"]])
                bx = f"{fmt(lo)}-{fmt(hi)}"
            if not lv:
                # positive statement of a breakout call with level only on chart (e.g. "شکست سقف باکس بهمون پوزیشن لانگ میده")
                if has_break and re.search(r"پوزیشن (?:لانگ|شورت)? ?(?:میده|میدهد|باز کنیم|باز میکنیم|بگیریم)|تریگر (?:لانگ|شورت)|میتونیم[^/]{0,30}پوزیشن|میتونین[^/]{0,30}اقدام|میتوانید[^/]{0,30}اقدام|اقدام (?:کنین|کنید|کنیم|بفرمایید|بنمایید)|میشه (?:لانگ|شورت)", seg):
                    rows.append(mkrow(p, sym, tf, sd, None, stype, et, bc, tg, cf, sp[0] if sp else None, vl, bx, rr, "level not stated in text (chart only)", "low", seg))
                continue
            n_l = len(lv)
            for i, n in enumerate(lv):
                role = trigger_role(seg, n["pos"], n["end"], i, n_l)
                conf = conf_side
                if not sym:
                    conf = "low"
                if raw.rstrip().endswith("…"):
                    conf = "low" if conf != "high" else "medium"
                r = mkrow(p, sym, tf, sd, n["v"], stype, et, bc, tg, cf, sp[0] if sp else None, vl, bx, rr, "", conf, seg)
                r["trigger_role"] = role
                rows.append(r)
    # sanity on targets/stops relative to trigger & side
    for r in rows:
        trig = r["_trig"]
        if trig is not None:
            if r["side"] == "long":
                r["_targets"] = [x for x in r["_targets"] if x > trig]
                if r["_stop"] is not None and r["_stop"] >= trig:
                    r["_stop"] = None
            elif r["side"] == "short":
                r["_targets"] = [x for x in r["_targets"] if x < trig]
                if r["_stop"] is not None and r["_stop"] <= trig:
                    r["_stop"] = None
    # de-duplicate identical (side, trigger) within a post
    seen, out = set(), []
    for r in rows:
        k = (r["side"], r["_trig"])
        if k in seen and r["_trig"] is not None:
            continue
        seen.add(k)
        out.append(r)
    if out:
        return out, "setup"
    clean = re.sub(r"[#\s\W_]+", "", body)
    clean = re.sub(r"(?i)usdt|\d+[hdmw]", "", clean)
    if sym and len(clean) < 25:
        return [], "chart_only"
    return [], "no_setup"


def mkrow(p, sym, tf, side, trig, stype, et, bc, targets, conf, stop, valid, box, rr, note, confidence, seg=""):
    return {
        "post_id": p["id"], "date_utc": p["date"][:19].replace("T", " "), "symbol": sym, "timeframe": tf, "side": side,
        "setup_type": stype, "_trig": trig, "entry_type": et, "break_confirmation": bc, "_stop": stop, "_targets": list(targets),
        "stated_rr": rr, "confirmations": "; ".join(dict.fromkeys(conf)), "validity_level": valid, "box": box,
        "trigger_role": "", "conditional": "yes", "notes": note, "confidence": confidence, "clause": seg.strip()[:300],
        "has_photo": int(bool(p.get("has_photo"))), "has_video": int(bool(p.get("has_video"))),
    }


# --------------------------------------------------------------------------- follow-ups
OUTCOME_PATTERNS = [
    ("faked", r"فیک (?:شد|شده|کرد|کرده)|فیک شدن|نتونست بالا|نتونست زیر|ریجکت شد"),
    ("not_triggered", r"فعال نشده|فعال نشد|نتونست فعال|فعال نکرد|هنوز فعال"),
    ("triggered", r"فعال شد|فعال شده|فعال کرد|فعال کرده|فعاله|پوزیشن(?:مون)? (?:باز|فعال) شد|activated|بعد از شکست(?:ش)?|با شکست[^/]{0,20}(?:حرکت|ریزش|رشد)"),
    ("stop_hit", r"استاپ (?:خورد|خوردیم|شد|میخوره|بخوره)|حد ضرر خورد"),
    ("risk_free", r"ریسک فری"),
    ("save_profit", r"سیو سود"),
    ("target_hit", r"تارگت[^/]{0,20}(?:خورد|زد|رسید)"),
]


def num_in_text(v: float, t: str) -> bool:
    for m in NUM_RE.finditer(t):
        try:
            x = parse_num(m.group(1), m.group(2))
        except ValueError:
            continue
        if x and abs(x - v) / v <= 0.0015:
            return True
    return False


def find_followups(rows, posts_by_id, posts_sorted, sym_index):
    for r in rows:
        if r.get("record_type") != "setup" or not r["symbol"]:
            continue
        d0 = datetime.fromisoformat(r["date_utc"])
        trig = r["_trig"]
        found = []
        for q in sym_index.get(r["symbol"], []):
            if q["id"] <= r["post_id"] or q["id"] in r["_reposts"]:
                continue
            dq = datetime.fromisoformat(q["date"][:19])
            if dq - d0 > timedelta(days=30):
                break
            if dq < d0:
                continue
            tq = norm(q["text"] or "")
            if trig is not None and num_in_text(trig, tq):
                # sentence(s) containing the number
                sents = [s for s in split_clauses(body_text(tq)) if num_in_text(trig, s)]
                tags = []
                for s in sents:
                    for name, pat in OUTCOME_PATTERNS:
                        if re.search(pat, s):
                            tags.append(name)
                            break
                tags = list(dict.fromkeys(tags))
                if tags:
                    found.append((q["id"], "+".join(tags), sents[0][:160] if sents else ""))
            elif trig is None or re.search(r"Update|نتیجه|آپدیت", q["text"] or ""):
                if re.search(r"Update|نتیجه|آپدیت|پوزیشن[^/]{0,30}فعال|ریسک به ریوارد \d", tq) and (dq - d0) <= timedelta(days=10):
                    tags = [name for name, pat in OUTCOME_PATTERNS if re.search(pat, tq)]
                    m = re.search(r"ریسک به ریوارد\s*(\d+(?:\.\d+)?)|(\d+)\s*درصد", tq)
                    if tags or m:
                        extra = ""
                        if m:
                            extra = (f"RR{m.group(1)}" if m.group(1) else f"{m.group(2)}%")
                        found.append((q["id"], "+".join(dict.fromkeys(tags)) + (("/" + extra) if extra else ""), "symbol-level update"))
        r["_followups"] = found


def summarise_outcome(f):
    if not f:
        return ""
    return "; ".join(f"{tag} ({pid})" for pid, tag, _ in f[:4])


# --------------------------------------------------------------------------- main
def main():
    B = load(B_FILE)
    A = load(ALL_FILE)
    b_ids = {p["id"] for p in B}
    A.sort(key=lambda p: (p["date"], p["id"]))
    universe = [p for p in A if "2022-01-01" <= p["date"][:10] <= "2026-12-31"]
    orig_of = fold_reposts(universe)
    reposts = defaultdict(list)
    for rid, oid in orig_of.items():
        if oid > 0:
            reposts[oid].append(rid)

    # symbol index over whole archive (for follow-ups)
    sym_index = defaultdict(list)
    for p in A:
        s = find_symbol(norm(p["text"] or ""))
        if s:
            sym_index[s].append(p)
        # posts mentioning a coin by name in text but with another header still count for that header only

    all_rows, status = [], Counter()
    chart_only, no_setup_ids = [], []
    per_post_status = {}
    for p in universe:
        if p["id"] in orig_of:
            per_post_status[p["id"]] = "repost" if orig_of[p["id"]] > 0 else "pin_notice"
            continue
        rows, st = extract_post(p)
        per_post_status[p["id"]] = st
        if st == "setup":
            for r in rows:
                r["record_type"] = "setup"
                r["_reposts"] = reposts.get(p["id"], [])
            all_rows.extend(rows)
        elif st == "chart_only":
            r = mkrow(p, find_symbol(norm(p["text"] or "")), find_tf(norm(p["text"] or "")), "", None, "", "", "", [], [], None, "", "", "",
                      "chart/image-only post: no setup text", "low")
            r["record_type"] = "chart_only"
            r["_reposts"] = reposts.get(p["id"], [])
            r["conditional"] = ""
            chart_only.append(r)

    # ---- manual corrections
    all_rows = apply_manual(all_rows, {p["id"]: p for p in universe})
    # restated triggers: same symbol+side+trigger within 14 days of an earlier row
    last = {}
    for r in sorted(all_rows, key=lambda r: (r["date_utc"], r["post_id"])):
        if r["_trig"] is None:
            r["restated_from"] = ""
            continue
        k = (r["symbol"], r["side"])
        prev = [x for x in last.get(k, []) if abs(x[1] - r["_trig"]) / r["_trig"] <= 0.0015
                and datetime.fromisoformat(r["date_utc"]) - datetime.fromisoformat(x[2]) <= timedelta(days=14)]
        r["restated_from"] = str(prev[0][0]) if prev else ""
        last.setdefault(k, []).append((r["post_id"], r["_trig"], r["date_utc"]))

    find_followups(all_rows, None, None, sym_index)
    for r in all_rows:
        r["outcome_reported"] = summarise_outcome(r.get("_followups", []))
        r["outcome_post_ids"] = ";".join(str(x[0]) for x in r.get("_followups", [])[:6])

    rows_out = sorted(all_rows + chart_only, key=lambda r: (r["date_utc"], r["post_id"], r["side"], r["_trig"] or 0))
    cols = ["post_id", "date_utc", "symbol", "timeframe", "side", "setup_type", "trigger_price", "entry_type", "stop", "targets",
            "stated_rr", "confirmations", "outcome_reported", "confidence",
            "record_type", "trigger_role", "break_confirmation", "conditional", "validity_level", "box", "restated_from",
            "outcome_post_ids", "repost_ids", "in_B_file", "has_photo", "url", "notes", "clause_fa"]
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows_out:
            w.writerow({
                **{c: r.get(c, "") for c in cols},
                "trigger_price": fmt(r["_trig"]), "stop": fmt(r["_stop"]), "targets": ";".join(fmt(x) for x in r["_targets"]),
                "repost_ids": ";".join(map(str, r.get("_reposts", []))), "in_B_file": int(r["post_id"] in b_ids),
                "url": f"https://t.me/tradecity_pro/{r['post_id']}", "clause_fa": r.get("clause", ""),
            })

    # ---- stats
    setups = [r for r in all_rows if r["record_type"] == "setup"]
    st = Counter(per_post_status.values())
    stats = {
        "universe_posts_2022_2026": len(universe),
        "B_file_posts": len(B),
        "post_status_counts": dict(st),
        "setup_posts": len({r["post_id"] for r in setups}),
        "setup_posts_not_in_B": len({r["post_id"] for r in setups if r["post_id"] not in b_ids}),
        "setup_rows": len(setups),
        "setup_rows_with_trigger_price": sum(r["_trig"] is not None for r in setups),
        "unique_rows_not_restated": sum(1 for r in setups if not r.get("restated_from")),
        "chart_only_posts": len(chart_only),
        "chart_only_by_year": dict(Counter(r["date_utc"][:4] for r in chart_only)),
        "B_posts_with_photo": sum(bool(p["has_photo"]) for p in B),
        "B_posts_image_only_like": sum(1 for p in B if len(re.sub(r"https?://\S+|#\S+|\s|\W", "", norm(p["text"] or ""))) < 25),
        "by_setup_type": dict(Counter(r["setup_type"] for r in setups).most_common()),
        "by_symbol_top30": dict(Counter(r["symbol"] for r in setups).most_common(30)),
        "n_symbols": len({r["symbol"] for r in setups}),
        "by_timeframe": dict(Counter(r["timeframe"] or "(blank)" for r in setups).most_common()),
        "by_side": dict(Counter(r["side"] for r in setups)),
        "by_year_rows": dict(sorted(Counter(r["date_utc"][:4] for r in setups).items())),
        "by_year_posts": dict(sorted(Counter(r["date_utc"][:4] for r in {r["post_id"]: r for r in setups}.values()).items())),
        "by_year_setup_type": {y: dict(Counter(r["setup_type"] for r in setups if r["date_utc"][:4] == y)) for y in sorted({r["date_utc"][:4] for r in setups})},
        "by_entry_type": dict(Counter(r["entry_type"] or "(blank)" for r in setups)),
        "by_break_confirmation": dict(Counter(r["break_confirmation"] or "(blank)" for r in setups)),
        "by_trigger_role": dict(Counter(r["trigger_role"] or "(blank)" for r in setups)),
        "by_confidence": dict(Counter(r["confidence"] for r in setups)),
        "conditional": dict(Counter(r["conditional"] for r in setups)),
        "rows_with_stop": sum(r["_stop"] is not None for r in setups),
        "rows_with_targets": sum(bool(r["_targets"]) for r in setups),
        "n_targets_dist": dict(Counter(len(r["_targets"]) for r in setups)),
        "rows_with_stated_rr": sum(bool(r["stated_rr"]) for r in setups),
        "stated_rr_values": dict(Counter(r["stated_rr"] for r in setups if r["stated_rr"])),
        "rows_with_validity_level": sum(bool(r["validity_level"]) for r in setups),
        "rows_with_box": sum(bool(r["box"]) for r in setups),
        "confirmation_counts": dict(Counter(c.split(" ")[0] if c.startswith("RSI") else c for r in setups for c in r["confirmations"].split("; ") if c).most_common()),
        "rows_with_outcome": sum(bool(r["outcome_reported"]) for r in setups),
        "rows_with_outcome_by_year": dict(Counter(r["date_utc"][:4] for r in setups if r["outcome_reported"])),
        "outcome_tags": dict(Counter(tag for r in setups for _, tg, _ in r.get("_followups", []) for tag in re.split(r"[+/]", tg) if tag)),
        "first_outcome_tag": dict(Counter(re.split(r"[+/]", r["_followups"][0][1])[0] for r in setups if r.get("_followups"))),
    }
    # stop distance % and relative to box; target distance and implied R
    sd, sd_box, tgt_pct, implied_r, val_pct = [], [], [], [], []
    for r in setups:
        t = r["_trig"]
        if t:
            if r["_stop"]:
                sd.append(abs(t - r["_stop"]) / t * 100)
                if r["box"]:
                    lo, hi = map(float, r["box"].split("-"))
                    if hi > lo:
                        sd_box.append(abs(t - r["_stop"]) / (hi - lo))
                if r["_targets"]:
                    implied_r.append(abs(r["_targets"][0] - t) / abs(t - r["_stop"]))
            if r["_targets"]:
                tgt_pct.append(abs(r["_targets"][0] - t) / t * 100)
            if r["validity_level"]:
                v = float(r["validity_level"])
                if (r["side"] == "long" and v < t) or (r["side"] == "short" and v > t):
                    val_pct.append(abs(t - v) / t * 100)
    # box size relative to trigger (range width %), and trigger distance from opposite box edge
    box_w = []
    for r in setups:
        if r["box"] and r["_trig"]:
            lo, hi = map(float, r["box"].split("-"))
            if hi > lo:
                box_w.append((hi - lo) / r["_trig"] * 100)

    def q(xs):
        if not xs:
            return {}
        xs = sorted(xs)
        return {"n": len(xs), "median": round(statistics.median(xs), 3), "p25": round(xs[len(xs) // 4], 3),
                "p75": round(xs[(3 * len(xs)) // 4], 3), "min": round(xs[0], 3), "max": round(xs[-1], 3)}
    stats.update({"stop_dist_pct": q(sd), "stop_dist_over_box": q(sd_box), "first_target_dist_pct": q(tgt_pct),
                  "implied_R_first_target": q(implied_r), "validity_level_dist_pct": q(val_pct), "box_width_pct_of_trigger": q(box_w)})
    with open(OUT_STATS, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: stats[k] for k in ["setup_posts", "setup_rows", "chart_only_posts", "rows_with_outcome", "by_year_posts"]}, ensure_ascii=False))


# --------------------------------------------------------------------------- manual review
# Built after reading every extracted row against its post.  Keys are post ids.
#   "drop": True                         -> remove all rows of the post (not a call: education, quiz, ad, management)
#   "drop_trig": [x, ...]                 -> remove rows with these trigger prices
#   "set": {field: value}                 -> override on every row of the post
#   "set_trig": {trigger: {field: value}} -> override on one row
#   "add": [ {side, trig, setup_type, ...} ]  -> rows the rules missed
MANUAL: dict[int, dict] = {}


def apply_manual(rows, posts):
    out = []
    by_post = defaultdict(list)
    for r in rows:
        by_post[r["post_id"]].append(r)
    for pid, m in MANUAL.items():
        if pid not in by_post and m.get("add") and pid in posts:
            by_post[pid] = []
    for pid, rs in by_post.items():
        m = MANUAL.get(pid, {})
        if m.get("drop"):
            continue
        keep = []
        for r in rs:
            if r["_trig"] is not None and any(abs(r["_trig"] - x) < 1e-12 for x in m.get("drop_trig", [])):
                continue
            if r["_trig"] is None and m.get("drop_blank"):
                continue
            for k, v in m.get("set", {}).items():
                set_field(r, k, v)
            for tv, fields in m.get("set_trig", {}).items():
                if r["_trig"] is not None and abs(r["_trig"] - tv) < 1e-12:
                    for k, v in fields.items():
                        set_field(r, k, v)
            keep.append(r)
        for a in m.get("add", []):
            p = posts[pid]
            t = norm(p["text"] or "")
            base = keep[0] if keep else None
            r = mkrow(p, a.get("symbol", base["symbol"] if base else find_symbol(t)), a.get("timeframe", base["timeframe"] if base else find_tf(t)),
                      a["side"], a.get("trig"), a.get("setup_type", "range_breakout_trigger"), a.get("entry_type", "stop"),
                      a.get("break_confirmation", "break"), a.get("targets", []), a.get("confirmations", []), a.get("stop"),
                      a.get("validity_level", ""), a.get("box", ""), a.get("stated_rr", ""), a.get("notes", "added in manual review"),
                      a.get("confidence", "medium"), a.get("clause", ""))
            r["trigger_role"] = a.get("trigger_role", "")
            r["record_type"] = "setup"
            r["_reposts"] = base["_reposts"] if base else []
            if "conditional" in a:
                r["conditional"] = a["conditional"]
            keep.append(r)
        out.extend(keep)
    return out


def set_field(r, k, v):
    if k == "trig":
        r["_trig"] = v
    elif k == "stop":
        r["_stop"] = v
    elif k == "targets":
        r["_targets"] = v
    else:
        r[k] = v


if __name__ == "__main__":
    main()
