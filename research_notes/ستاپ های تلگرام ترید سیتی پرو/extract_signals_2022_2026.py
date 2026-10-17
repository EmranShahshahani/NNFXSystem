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


NUM_RE = re.compile(r"(?<![A-Za-z0-9.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)(\s*هزار)?(?![\d])")


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
    lines = [x.strip() for x in t.strip().split("\n") if x.strip() and not x.strip().startswith("http")]
    first = lines[0] if lines else ""
    m = re.match(r"^#?([A-Za-z]{2,10})\s*(?:usdt)?\s*(?:\d+\s*(?:m|min|h|d)\b)?\s*$", first, re.I)
    if m and m.group(1).lower() not in {"entry", "sl", "tp"}:
        return norm_symbol(m.group(1))
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
LONG_RE = r"لانگ|longe?\b|long\b|خرید اسپات|خرید ریسکی|برای خرید|استاپ بای|stop ?buy|موقعیت خرید|معاملات لانگ|بخرید|kharid"
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
        sub = [p]
        for s in sub:
            s = s.strip()
            if s:
                # still both sides? split at ' اما '/' ولی ' between them
                hs = side_hits(s)
                if {h[1] for h in hs} == {"long", "short"}:
                    pieces = re.split(r"\s(?=(?:اما|ولی|و اگر|همچنین|طولی|واسه شورت|واسه لانگ|برای شورت هم|برای لانگ هم)\s)|،", s)
                    out.extend(x.strip() for x in pieces if x.strip())
                else:
                    out.append(s)
    return out


TRIG_PRE = (r"(?:شکست|شکستن|شکوندن|بشکنه|بریک ?اوت|break|بالای|بالا ی|زیر|زیره|پایین|تثبیت|بعد از|بعداز|بعد|after|under|above|zire"
            r"|تریگر|تريگر|trigger|نقطه ورود|ورود|منتظر|از دست رفتن|استاپ بای|استاپ سل|اوردر استاپ|حمایت|مقاومت|سقف|کف|ناحیه|لول|محدوده|ضلع)")
TRIG_POST = r"^\s*(?:\$|دلار)?\s*(?:را|رو|رو هم)?\s*(?:بشکن|بشکون|بشکنه|از دست|شکسته|تثبیت|بریک|break|استاپ بای|استاپ سل|شکست)"
INFO_PRE = r"(?:حواستون|حواسمون|نیم نگاهی|نگاهی|(?<!بعد )(?<!بعد)از مقاومت|(?<!بعد )(?<!بعد)از حمایت|(?<!بعد )(?<!بعد)از سقف|(?<!بعد )(?<!بعد)از کف|(?<!بعد )(?<!بعد)از ناحیه|رسیدن به|رسید به|برخورد با|حمایت شدن از|ریجکت شدن از|مقاومت اول|حمایت اول|قیمت حدود|حوالی|با قیمت|نزدیک)\s*(?:به)?\s*(?:حمایت|مقاومت|ناحیه|لول)?\s*$"
INFO_POST = r"^\s*(?:\$|دلار)?\s*(?:را|رو)?\s*(?:به خوبی |خوب |خیلی خوب )?(?:حفظ|نگه|ریجکت|حمایت شد|واکنش|خریدوفروش|رسیده|رسید\b|برخورد|باشه\b|باشد\b|باشید)"
SHORT_CUE = r"(?:زیر|زیره|پایین|از دست|حمایت|کف|under|zire|ضلع پایین)[^/\d]{0,14}$"
LONG_CUE = r"(?:بالای|بالا ی|بالا|مقاومت|مقاوت|سقف|above|ضلع بالا)[^/\d]{0,14}$"


def classify_numbers(seg: str, side_ctx: str | None):
    """Return list of dicts {v, raw, pos, end, role, cue, dir} for price-like numbers in seg.
    role: level (a break/trigger level), info (descriptive level), target, stop, valid, box_lo/box_hi, rsi."""
    res = []
    has_rsi = re.search(r"rsi|آر ?اس ?آی", seg, re.I) is not None
    prev_end = 0
    for m in NUM_RE.finditer(seg):
        raw, k = m.group(1), m.group(2)
        a, b = m.start(), m.end()
        pre = seg[max(prev_end, a - 30):a]
        prev_end = b
        post = seg[b:b + 25]
        pre_l = pre.lower()
        if re.match(r"\s*(?:ساعت|دقیقه|روز|ماه|هفته|سال|درصد|%|٪|بار|تا (?:ارز|کوین|تحلیل|سیگنال|ترید|پوزیشن|تارگت|حد)|برابر|x\b|کالری|گرم|کیلو|نفر|میلیون|میلیارد|تایی|تاش|th|st|nd|rd|ام\b|امین|m\b|min|h\b|d\b|w\b|H\b|D\b|W\b|ثانیه|اکتبر|آبان|تا پیتزا)", post):
            continue
        if re.search(r"(?:تایم فریم|تایم|time ?frame|ریسک به ریوارد|ریسک ریوارد|\brr|لوریج|لورج|ساعت|sma|ema|\bma|فیبو|fib|قسمت|پارت|روز|#|قانون|شماره|lev(?:erage)?|tp\d|ts)\s*[:\-]?\s*$", pre_l):
            continue
        if re.search(r"(?:sma|ema)\s*\d*\s*(?:و|,)\s*$", pre_l) or re.match(r"\s*(?:فیبو|fib)", post):
            continue
        try:
            v = parse_num(raw, k)
        except ValueError:
            continue
        if v == 0 or (1900 <= v <= 2035 and "." not in raw and re.search(r"سال|20\d\d\s*$|میلادی", pre + post)):
            continue
        cue = re.search(TRIG_PRE + r"[^/\d]{0,20}$", pre, re.I) is not None or re.match(TRIG_POST, post, re.I) is not None
        dr = "short" if re.search(SHORT_CUE, pre, re.I) else ("long" if re.search(LONG_CUE, pre, re.I) else "")
        if has_rsi and (re.search(r"rsi[^0-9]{0,22}$", pre_l) or re.match(r"\s*(?:در|تو|روی)\s*rsi", post, re.I)
                        or (v in (30, 50, 70) and re.search(r"rsi", seg[max(0, a - 60):b + 40], re.I))):
            role = "rsi"
        elif re.search(r"(?:بین|محدوده|باکس|رنج)(?:\s+(?:حمایت|مقاومت|ناحیه|محدوده|ناحیه))?[^/\d]{0,8}$", pre) and re.match(r"\s*(?:\$|دلار)?\s*(?:و|تا|الی|الا|-)\s*(?:حمایت|مقاومت|ناحیه)?\s*\d", post):
            role = "box_lo"
        elif re.search(r"(?:بین|باکس|رنج|محدوده)[^/]{0,40}\d[\d.,]*\s*(?:\$|دلار)?\s*(?:و|تا|الی|الا|-)\s*(?:حمایت|مقاومت|ناحیه)?\s*$", pre):
            role = "box_hi"
        elif re.search(VALID_PRE + r"[^/\d]{0,30}$", pre):
            role = "valid"
        elif re.search(STOP_PRE + r"[^/\d]{0,22}$", pre_l):
            role = "stop"
        elif re.search(TARGET_PRE + r"[^/\d]{0,18}$", pre_l) and not re.search(r"(?:شکست|بالای|زیر)[^/\d]{0,6}$", pre):
            role = "target"
        elif re.match(r"^\s*(?:\$|دلار)?\s*(?:که[^/\d]{0,30})?(?:رو )?(?:هم )?(?:دیروز |دیشب )?(?:فعال (?:شد|شده|کرد|کرده)|فعاله)", post) or re.search(r"(?:قیمت|کوین \w+|بیت ?کوین|اتریوم) (?:بعد از|با) شکست\s*$|(?:تریگر|ناحیه)\s*$", pre) and re.search(r"^[^/]{0,60}(?:فعال (?:شد|شده|کرد|کرده)|ریجکت شد|فیک (?:شد|کرد))", post):
            role = "outcome"
        elif re.search(INFO_PRE, pre) or re.match(INFO_POST, post):
            role = "info"
        elif cue:
            role = "level"
        else:
            role = "info"
        res.append({"v": v, "raw": raw + (k or ""), "pos": a, "end": b, "role": role, "dir": dr})
    # anaphora: "درگیر 71924 هستش؛ در صورت شکست این ناحیه ..." -> promote the last info number
    if not any(n["role"] == "level" for n in res) and re.search(r"شکست(?:ش| اون| این| همین| خودِ)|شکستن این|شکسته (?:بشه|شد)|بریک ?اوت (?:این|اون)|شکستش", seg):
        infos = [n for n in res if n["role"] == "info"]
        if infos:
            infos[-1]["role"] = "level"
    return res


def label_setup(seg: str, post: str) -> str:
    s = seg.lower()
    if re.search(r"فیک|fake", s) and re.search(r"(?:فیک (?:بریک ?اوت|بشه|شد|کنیم|کرد|بودن)|در صورت فیک|اگر[^/]{0,40}فیک|fake)", s):
        return "fakeout"
    if re.search(r"sma|ema|میانگین متحرک", s) and re.search(r"پولبک|رسیدن|برسه|حمایت (?:شد|بشه|نشد)", s):
        return "ma_pullback"
    if re.search(r"ایندیسیژن|indecision|کندل ستاپ|کندل تایید|شدو", s) and re.search(r"(?:با|همراه)[^/]{0,15}(?:کندل ستاپ|ایندیسیژن|کندل تایید)|کندل ستاپ[^/]{0,30}(?:پوزیشن|ورود)|اگه کندل ستاپی|استاپ بای[^/]{0,20}shadow", s):
        return "indecision_trigger"
    if re.search(r"پولبک|pullback", s) and re.search(r"(?:با|روی|در صورت|بعد از)[^/]{0,20}پولبک|پولبک[^/]{0,30}(?:پوزیشن|ورود|تریگر)", s):
        return "pullback"
    if re.search(r"مثلث|(?<![\u0600-\u06FF])(?:وج|کنج)(?![\u0600-\u06FF])|سر و شانه|سقف دوقلو|کف دوقلو|پرچم|وی پترن|v pattern|کانال|ترند(?! صعودی خودش هست)|خط روند|ترند لاین|trend", s) and not re.search(r"باکس|رنج", s):
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


HEADER_RE = re.compile(r"(?im)💵?\s*Pair\s*:\s*#?\S+(?:\s*-\s*Update)?|⏳?\s*Time\s*Frame\s*:\s*#?\w+(?:\s*,\s*#?\w+)?|🕐?\s*TimeFrame\s*:\s*\w+|🫥+|🔗\s*لینک چارت.?|لینک چارت.?|https?://\S+|@\w+|LMN Bot.*$|.*جهت دیدن تحلیل های بیشتر.*$|.*برای دیدن تحلیل های روزانه بیشتر.*$|.*روز رایگان.*$|Trading View \|.*$")


def body_text(t: str) -> str:
    t = HEADER_RE.sub("\n", t)
    t = re.sub(r"#(\w+)", lambda m: " " if (TF_HASH.match(m.group(1)) or m.group(1).lower() in {"daily", "weekly", "tcp", "futures"}) else " " + m.group(1) + " ", t)
    return t


# --------------------------------------------------------------------------- extraction
def extract_post(p) -> tuple[list[dict], str]:
    """Return (rows, status) where status in setup / chart_only / no_setup."""
    raw = p["text"] or ""
    t = norm(raw)
    # Persian writers sometimes use ',' as decimal point ("2,149" for ATOM 2.149): if the other
    # decimals in the post are < 100, treat single-digit "d,ddd" as a decimal number
    decs = [float(x) for x in re.findall(r"(?<![\d,])\d+\.\d+", t)]
    if decs and statistics.median(decs) < 100:
        t = re.sub(r"(?<![\d,.])(\d),(\d{3})(?![\d,])", r"\1.\2", t)
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

    if re.search(r"نتیجه (?:تحلیل|تریگر|کوین)|بریم برای (?:ادامه )?نتیجه|- ?Update|🔥 نتیجه", t[:160]):
        return [], "result_report"
    # clauses that mix a negated/management statement with a new call are split at conjunctions
    MGMT_RE = r"سیو سود|ریسک فری|استاپتون|استاپ ?تون|خارج شید|ببندید|سیو کنید"
    cl2 = []
    for c in clauses:
        c_ = re.sub(r"بدی نیست|بد نیست", "خوبه", c)
        if re.search(NEG_RE, c_) or re.search(MGMT_RE, c_):
            cl2.extend(x.strip() for x in re.split(r"\s(?=(?:اما|ولی)\s)|،|\s,\s|\s(?=و برای)", c_) if x and x.strip())
        else:
            cl2.append(c_)
    clauses = cl2
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
        # assign each level number: direction cue (زیر/حمایت -> short, بالای/مقاومت -> long) if that side is
        # mentioned in the clause, else the nearest side word
        lv_by_side = defaultdict(list)
        if len(sides) == 1:
            for n in levels:
                lv_by_side[sides[0]].append(n)
        else:
            num_pos = sorted([x["pos"] for x in levels])
            for n in levels:
                nxt_num = min([x for x in num_pos if x > n["pos"]], default=10 ** 9)
                prv_num = max([x["end"] for x in levels if x["end"] <= n["pos"]], default=-1)
                after = [h for h in hits if n["end"] <= h[0] < nxt_num and h[0] - n["end"] <= 40]
                before = [h for h in hits if prv_num <= h[0] < n["pos"]]
                if n["dir"] and n["dir"] in sides and not after:
                    lv_by_side[n["dir"]].append(n)
                elif after:
                    lv_by_side[after[0][1]].append(n)
                elif before:
                    lv_by_side[before[-1][1]].append(n)
                elif n["dir"] and n["dir"] in sides:
                    lv_by_side[n["dir"]].append(n)
                else:
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
            if not lv and ci > 0 and re.search(r"(?:شکست|شکستن|بریک ?اوت|تثبیت[^/]{0,12}(?:زیر|بالای))\s*(?:این|همین|اون|خودِ)\s*(?:ناحیه|لول|محدوده|حمایت|مقاومت|سقف|کف|سطح|نواحی|باکس|ناحیه ها)|شکستش|شکست سقف باکس|شکست کف باکس|شکست باکس", seg):
                cand = []
                for cj in range(ci - 1, max(-1, ci - 3), -1):
                    nn = [n for n in classify_numbers(clauses[cj], None) if n["role"] in ("info", "level", "box_lo", "box_hi")]
                    if nn:
                        if any(n["role"] in ("box_lo", "box_hi") for n in nn):
                            want = "box_hi" if sd == "long" else "box_lo"
                            nn = [n for n in nn if n["role"] == want] or nn
                            cand = [nn[-1]]
                        else:
                            cand = [nn[-1]] if not re.search(r"این دو|دو نواحی|نواحی", seg) else nn[-2:]
                        break
                if cand:
                    for n in cand:
                        r = mkrow(p, sym, tf, sd, n["v"], stype, et, bc, tg, cf, sp[0] if sp else None, vl, bx, rr,
                                  "level taken from preceding sentence (anaphora: 'break of this level')", "medium", clauses[cj] + " || " + seg)
                        r["_ci"] = ci
                        rows.append(r)
                    continue
            if not lv:
                # positive statement of a breakout call with level only on chart (e.g. "شکست سقف باکس بهمون پوزیشن لانگ میده")
                if has_break and re.search(r"پوزیشن (?:لانگ|شورت)? ?(?:میده|میدهد|باز کنیم|باز میکنیم|بگیریم)|تریگر (?:لانگ|شورت)|میتونیم[^/]{0,30}پوزیشن|میتونین[^/]{0,30}اقدام|میتوانید[^/]{0,30}اقدام|اقدام (?:کنین|کنید|کنیم|بفرمایید|بنمایید)|میشه (?:لانگ|شورت)", seg):
                    rows.append(mkrow(p, sym, tf, sd, None, stype, et, bc, tg, cf, sp[0] if sp else None, vl, bx, rr, "level not stated in text (chart only)", "low", seg))
                    rows[-1]["_ci"] = ci
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
                r["_ci"] = ci
                rows.append(r)
    # ---- post-level context: confirmations / targets / validity stated in neighbouring clauses
    POSTCONF = ("volume", "RSI", "SMA", "setup candle", "BTC dominance", "New York session", "weekend caution", "order book", "confirmation candle")
    clause_side = [ {h[1] for h in side_hits(c)} for c in clauses ]
    for r in rows:
        ci = r.get("_ci")
        if ci is None:
            continue
        extra = []
        for cj, c in enumerate(clauses):
            if cj == ci:
                continue
            if clause_side[cj] and r["side"] not in clause_side[cj]:
                continue
            for x in confirmations(c, t):
                if x.startswith(POSTCONF):
                    extra.append(x)
        if extra:
            cur = [x for x in r["confirmations"].split("; ") if x]
            r["confirmations"] = "; ".join(dict.fromkeys(cur + extra))
        # following side-less clause(s): targets and validity level
        for cj in (ci + 1, ci + 2):
            if cj >= len(clauses) or clause_side[cj]:
                break
            nums = classify_numbers(clauses[cj], None)
            for n in nums:
                if n["role"] == "target" or (n["role"] == "level" and re.search(r"به سمت|بسمت|حرکت", clauses[cj][n["end"]:n["end"] + 40] + clauses[cj][max(0, n["pos"] - 25):n["pos"]])):
                    r["_targets"].append(n["v"])
                elif n["role"] == "valid" and not r["validity_level"]:
                    r["validity_level"] = fmt(n["v"])
        # momentum (RSI) framing of the same trade
        same = [c for cj, c in enumerate(clauses) if cj == ci or not clause_side[cj] or r["side"] in clause_side[cj]]
        if r["setup_type"] in ("range_breakout_trigger", "other") and any(
                re.search(r"rsi", c, re.I) and re.search(r"اوربای|اورسل|overbuy|oversell|over-extend|بالای 70|بالا 70|زیر 30|تریگر مومنتوم|در rsi", c, re.I)
                and re.search(r"تریگر|تاییدیه|تایید|پوزیشن|مومنتوم", c) for c in same):
            r["setup_type"] = "momentum_trigger_rsi"
        if r["setup_type"] in ("range_breakout_trigger", "other") and any(
                re.search(r"sma|ema", c, re.I) and re.search(r"پولبک|حمایت|برسه|رسیدن", c) for c in same):
            r["setup_type"] = "ma_pullback"
    all_stops = []
    for c in clauses:
        all_stops += [n["v"] for n in classify_numbers(c, None) if n["role"] == "stop"]
    if len(set(all_stops)) == 1:
        for r in rows:
            if r["_stop"] is None:
                r["_stop"] = all_stops[0]
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
    num_sides = {r["side"] for r in rows if r["_trig"] is not None}
    rows = [r for r in rows if r["_trig"] is not None or r["side"] not in num_sides]
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
OUTCOME_PATTERNS = [  # past-tense statements only; conditional ("اگر/در صورت ...") matches are skipped
    ("not_triggered", r"فعال نشده|فعال نشد|نتونست فعال|فعال نکرد|هنوز فعال"),
    ("stop_hit", r"استاپ (?:خورد|خوردیم|شد\b)|حد ضرر خورد"),
    ("faked", r"فیک (?:شد|شده|کرد|کرده)(?![\u0600-\u06FF])|(?:رو|را) فیک کرد|بعد از فیک شدن|داره (?:این ناحیه رو )?فیک میکنه"),
    ("triggered", r"فعال (?:شد|شده|کرد|کرده)(?![\u0600-\u06FF])|فعاله|رو (?:هم )?فعال کرد|شکسته شد|(?:رو|را) (?:با یک کندل بزرگ )?شکست(?:ه)?(?: و|،|\s*$| الان)|پوزیشن(?:مون)? (?:باز|فعال) شد"),
    ("rejected", r"ریجکت (?:شد|شده|خورد)|نتونست (?:بالای|بالا|زیر|تثبیت|به)"),
    ("risk_free", r"ریسک فری"),
    ("save_profit", r"سیو سود"),
    ("target_hit", r"تارگت[^/]{0,20}(?:خورد|زد|رسید)"),
]
COND_RE = r"(?:در صورت|اگر|اگه|احتمال|میتونه|ممکنه)[^/]{0,25}$"


def num_in_text(v: float, t: str) -> bool:
    for m in NUM_RE.finditer(t):
        try:
            x = parse_num(m.group(1), m.group(2))
        except ValueError:
            continue
        if x and abs(x - v) / v <= 0.0003:
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
                        mm = re.search(pat, s)
                        if mm and not re.search(COND_RE, s[:mm.start()]):
                            tags.append(name)
                            break
                tags = list(dict.fromkeys(tags))
                if tags:
                    found.append((q["id"], "+".join(tags), sents[0][:160] if sents else ""))
            elif r.get("_latest_for_symbol_until", "") and q["date"][:19] <= r["_latest_for_symbol_until"]:
                # symbol-level past-tense statements without a price ("نقطه ورود ... فعال شد", "ریسک به ریوارد 7")
                for sq in split_clauses(body_text(tq)):
                    if NUM_RE.search(re.sub(r"ریسک به ریوارد\s*\d+(?:\.\d+)?|\d+\s*درصد|لورج\s*\d+", "", sq)):
                        continue
                    if not re.search(r"نقطه ورود|تریگر|پوزیشن", sq):
                        continue
                    sq_sides = {h[1] for h in side_hits(sq)}
                    if r["side"] not in sq_sides and (sq_sides or r.get("_post_sides") != {r["side"]}):
                        continue
                    tags = []
                    for name, pat in OUTCOME_PATTERNS:
                        mm = re.search(pat, sq)
                        if mm and not re.search(COND_RE, sq[:mm.start()]):
                            tags.append(name)
                    m2 = re.search(r"ریسک به ریوارد\s*(\d+(?:\.\d+)?)|(\d+)\s*درصد", sq)
                    if m2:
                        tags.append(f"RR{m2.group(1)}" if m2.group(1) else f"{m2.group(2)}%")
                    if tags:
                        found.append((q["id"], "+".join(dict.fromkeys(tags)) + " [symbol-level]", sq[:160]))
                        break
            elif trig is None or re.search(r"Update|نتیجه|آپدیت", q["text"] or ""):
                if re.search(r"Update|نتیجه|آپدیت|پوزیشن[^/]{0,30}فعال|ریسک به ریوارد \d", tq) and (dq - d0) <= timedelta(days=10):
                    tags = [name for name, pat in OUTCOME_PATTERNS if (lambda mm: mm and not re.search(COND_RE, tq[:mm.start()]))(re.search(pat, tq))]
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
    for r in all_rows:  # re-apply direction sanity after manual edits
        t0 = r["_trig"]
        if t0 is None:
            continue
        if r["side"] == "long":
            r["_targets"] = [x for x in r["_targets"] if x > t0 * 1.0005]
            if r["_stop"] is not None and r["_stop"] >= t0:
                r["_stop"] = None
        elif r["side"] == "short":
            r["_targets"] = [x for x in r["_targets"] if x < t0 * 0.9995]
            if r["_stop"] is not None and r["_stop"] <= t0:
                r["_stop"] = None
    dd, seen = [], set()
    for r in all_rows:
        k = (r["post_id"], r["side"], r["_trig"]) if r["_trig"] is not None else (r["post_id"], r["side"], id(r))
        if k in seen:
            continue
        seen.add(k)
        dd.append(r)
    all_rows = dd
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

    # for symbol-level follow-ups: a row may claim price-less updates only until the next setup post on that symbol
    by_sym = defaultdict(list)
    for r in all_rows:
        by_sym[r["symbol"]].append(r)
    for sym_, rs in by_sym.items():
        dates = sorted({x["date_utc"] for x in rs})
        for r in rs:
            later = [d for d in dates if d > r["date_utc"]]
            lim = (datetime.fromisoformat(r["date_utc"]) + timedelta(days=10)).isoformat(sep="T")
            r["_latest_for_symbol_until"] = min([later[0].replace(" ", "T")] + [lim]) if later else lim
    ps = defaultdict(set)
    for r in all_rows:
        ps[r["post_id"]].add(r["side"])
    for r in all_rows:
        r["_post_sides"] = ps[r["post_id"]]
    find_followups(all_rows, None, None, sym_index)
    for r in all_rows:
        r["outcome_reported"] = r.get("outcome_override") or summarise_outcome(r.get("_followups", []))
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
MANUAL: dict[int, dict] = {
    # ---------------- 2022 (two-sided "if X breaks -> long / if Y breaks -> short" posts)
    8529: {"drop_side": ["short"], "set": {"notes": "box breakout up = risky long; author prefers to find a short later (no level)"}},
    8593: {"set": {"notes": "restates 8560 short trigger 61.85 with target 55"}},
    8620: {"drop_blank": True, "add": [{"side": "short", "trig": 2523.0, "box": "2552-2570", "break_confirmation": "break",
            "notes": "'if 2523 is lost again we drop sharply'; 2552-2570 = no-trade zone; author waits for the break", "confidence": "medium"}]},
    8636: {"add": [{"side": "long", "trig": None, "setup_type": "pullback", "entry_type": "market", "trigger_role": "risky/early",
            "confirmations": ["confirmation candle"], "notes": "risky long on pullback after downtrend-line break, after a good candle", "confidence": "low"}]},
    8648: {"set": {"trig": 178.5, "confidence": "medium", "notes": "level from same post ('resistance 178.5')"}},
    8669: {"drop_trig": [1.71], "set_trig": {1.71: {}}},
    8671: {"drop_trig": [1.506], "drop_side_trig": {"short": [1.617]}, "set_trig": {1.617: {"trigger_role": "main"}},
           "add": [{"side": "short", "trig": None, "setup_type": "pattern", "entry_type": "", "targets": [1.506], "confirmations": ["confirmation candle"],
                    "notes": "short under the downtrend line if a confirmation candle appears, target support 1.506", "confidence": "low"}]},
    8697: {"set_trig": {}, "fill_blank": {"long": 49.5}},
    8700: {"drop_trig": [22.66], "add": [{"side": "long", "trig": 22.66, "targets": [25.8], "break_confirmation": "close",
            "notes": "'if resistance 22.66 breaks, after confirmation expect targets e.g. 25.8' (side implied)", "confidence": "medium"}]},
    8708: {"set_trig": {4.82: {"side": "long", "notes": "'after break of 4.82 it will grow well' (side implied)"}}, "drop_trig": [4.8223]},
    8730: {"add": [{"side": "short", "trig": 93.71, "box": "93.71-107.8", "notes": "'if support is lost -> good short'; support = box low 93.71", "confidence": "medium"}]},
    8747: {"add": [{"side": "long", "trig": None, "setup_type": "pullback", "entry_type": "market", "break_confirmation": "close", "targets": [1.81, 1.91],
            "confirmations": ["volume", "candle close beyond level"], "notes": "1h resistance broken + pullback; long on close of this candle with good volume; resistances 1.81 / 1.91",
            "confidence": "medium"}]},
    8748: {"set_trig": {2.159: {"setup_type": "range_breakout_trigger", "notes": "broken 1h resistance; long if candle closes with good volume (target text '2.0713' is below entry, likely a typo; omitted)"}},
           "set_blank": {"short": {"setup_type": "fakeout", "targets": [1.89], "notes": "short if the breakout of 2.159 fails to hold"}}},
    8749: {"set_trig": {4.35: {"setup_type": "range_breakout_trigger"}}},
    8768: {"drop_blank": True, "set_trig": {92.0: {"trigger_role": ""}},
           "add": [{"side": "long", "trig": None, "entry_type": "market", "trigger_role": "risky/early", "setup_type": "other",
                    "notes": "'you can go long right here, risky, if it is in your strategy'; better after 96", "confidence": "low"}]},
    8769: {"set": {"notes": "prices as written (5678/5940); ONT traded ~0.57 so likely 0.5678/0.5940"}},
    8801: {"drop_trig": [1.66], "keep_side_trig": {"short": [1.66]}},
    8810: {"set_trig": {15.0: {"notes": "as written 'زیر 15'; context (0.1537 resistance) implies 0.15"}}},
    8819: {"drop_trig": [79.86], "add": [{"side": "short", "trig": 79.86, "targets": [76.61], "break_confirmation": "close", "confidence": "high"},
                                         {"side": "long", "trig": 85.0, "confidence": "high"}]},
    8831: {"drop_trig": [21616.0], "drop_blank": True},
    8834: {"drop_trig": [1.35]},
    8922: {"drop_trig": [387.0], "set": {"box": "364-387"}},
    8946: {"drop_trig": [2.32], "set": {"box": "2.32-2.352"}},
    8956: {"drop_trig": [2.7667], "add": [{"side": "short", "trig": 2.7667, "targets": [2.24], "confidence": "medium",
            "notes": "'if this support is lost, no strong support until 2.24' (side implied)"}]},
    8985: {"drop_trig": [128.5], "keep_side_trig": {"short": [128.5]}},
    9009: {"drop": False, "drop_blank": True, "drop_trig": [147.78], "add": [
        {"side": "short", "trig": None, "setup_type": "pullback", "entry_type": "market", "trigger_role": "risky/early", "notes": "triangle broken down, pulling back: short possible now", "confidence": "low"},
        {"side": "short", "trig": 147.78, "trigger_role": "main", "notes": "safer short entry = break of 147.78 (range may form)", "confidence": "high"},
        {"side": "long", "trig": None, "setup_type": "fakeout", "trigger_role": "risky/early", "notes": "if the downside break is faked: long on break of the triangle's upper side (risky)", "confidence": "low"},
        {"side": "long", "trig": 164.69, "trigger_role": "main", "break_confirmation": "close", "notes": "safer long after close above 164.69", "confidence": "high"}]},
    9017: {"set_trig": {88.26: {"trigger_role": "risky/early", "notes": "after trend-line break, risky"}, 91.2: {"trigger_role": "main"}}, "set": {"box": "83.41-91.2"}},
    9057: {"set_trig": {452.7: {"trigger_role": ""}}},
    9143: {"set": {"symbol": "AAVEUSDT", "timeframe": "15m"}},
    9174: {"set_trig": {1.0152: {"trigger_role": "risky/early"}}},
    9177: {"set_trig": {92.0: {"trigger_role": "risky/early"}}},
    9179: {"set_trig": {99.95: {"trigger_role": "risky/early"}}},
    9219: {"drop": True, "add": [{"side": "short", "trig": 25.0, "box": "25-35", "break_confirmation": "close", "notes": "waits for exit from 25-35 range then enters after confirmation", "confidence": "medium"},
                                 {"side": "long", "trig": 35.0, "box": "25-35", "break_confirmation": "close", "notes": "waits for exit from 25-35 range then enters after confirmation", "confidence": "medium"}]},
    9248: {"fill_blank": {"short": 0.05148}, "set": {"box": "0.05148-0.05572"}},
    9260: {"set_trig": {9.0: {"trigger_role": "main"}}},
    9285: {"drop": True}, 9453: {"drop": True}, 9880: {"drop": True}, 9917: {"drop": True}, 9926: {"drop": True},
    9314: {"fill_blank": {"long": 5.95}},
    # ---------------- 2023-2025
    10587: {"set": {"confidence": "low", "notes": "BTC: shorts meaningless unless 22500 is lost; panic-sell risk below it"}},
    11561: {"drop": True}, 15996: {"drop": True}, 19448: {"drop": True}, 23666: {"drop": True}, 23860: {"drop": True},
    17827: {"set": {"notes": "live report: short opened on break of 2675.90, RR ~5 reached at time of post", "outcome_override": "triggered; RR~5 reported in same post (17827)"}},
    18047: {"add": [{"side": "short", "trig": None, "symbol": "ETHUSDT", "timeframe": "15m", "setup_type": "fakeout", "entry_type": "market",
            "confirmations": ["setup candle"], "notes": "trend weakness + fake top; setup candle gave small stop; author took profit (save-profit)", "confidence": "low",
            "outcome_override": "save_profit (18047 same post)"}]},
    22732: {"set_trig": {110280.0: {"notes": "spot-buy trigger above 110280; futures trigger taken earlier (not stated)"}}},
    23278: {"keep_only_trig": [4.463, 2.756]},
    23290: {"set_trig": {3.076: {"trigger_role": "risky/early", "notes": "spot entry trigger / author longs futures here"}}},
    # ---------------- 2026
    25418: {"drop": True}, 25436: {"drop": True},
    25657: {"set": {"targets": [], "confidence": "low", "notes": "BTC 4h range 63-69: no action inside; loss of 63124 = alt-coin dump risk"}},
    25701: {"fill_blank": {"long": 71362.0}, "set_blank": {"long": {"setup_type": "pullback", "notes": "long on pullback to 71362 with buy volume and a new wave"}}},
    25702: {"fill_blank": {"long": 74967.0}},
    25705: {"drop_trig": [67688.0]},
    25714: {"set_trig": {2186.0: {"side": "long", "trigger_role": "main"}}},
    25721: {"drop_trig": [62827.0], "add": [{"side": "long", "trig": 69105.0, "notes": "next trigger if 62827(sic, earlier trigger) was missed"},
                                           {"side": "long", "trig": 71350.0, "trigger_role": "main", "break_confirmation": "close", "notes": "break & hold above 71350 = main confirmation"}]},
    25738: {"drop_side_trig": {"long": [67827.0, 69105.0]}},
    25750: {"fill_blank": {"short": 66047.0}},
    25761: {"add": [{"side": "short", "trig": 1983.0, "notes": "second short trigger ('2033 and 1983')"}]},
    25764: {"drop_blank": True, "add": [{"side": "long", "trig": 71350.0, "targets": [74967.0], "notes": "next trigger after 69105 activated"},
                                        {"side": "long", "trig": 69105.0, "setup_type": "pullback", "entry_type": "limit", "notes": "or on pullback to 69105"}],
            "outcome_note": "reports 69105 trigger activated"},
    25765: {"set_trig": {2186.0: {"side": "long", "trigger_role": "main"}}},
    25776: {"set_trig": {}, "fix_anaphora": {"long": 0.09339}, "set": {"box": "0.08982-0.09339"}},
    25796: {}, 25800: {"set_trig": {0.10335: {"trigger_role": "main"}}},
    25818: {"drop_trig": [0.0936]},
    25827: {"add": [{"side": "short", "trig": 0.8501, "trigger_role": "main", "box": "0.8501-0.9050", "notes": "main short entry = breakout of 0.8501 (not 0.9050, inside the range)"}]},
    25834: {"fill_blank": {"short": 70770.0}},
    25856: {"drop_trig": [74967.0]},
    25865: {"drop_blank": True},
    25870: {"set_trig": {0.3132: {"trig": 0.3241}}},
    25884: {"set_trig": {75336.0: {"side": "long"}}},
    25905: {"drop_trig": [15.0], "add": [{"side": "long", "trig": None, "setup_type": "indecision_trigger", "entry_type": "stop", "trigger_role": "risky/early",
            "notes": "4h setup candle closing = new risky entry; earlier entry +12%, RR>15", "confidence": "low"}]},
    25906: {"drop_blank": True, "set_trig": {0.10335: {"side": "long"}, 0.8982: {"notes": "as written 0.8982 (DOGE ~0.09: likely 0.08982)"}}},
    25911: {"drop": True},
    25954: {"drop_blank": True, "drop_trig": [72.73], "set": {"box": "77777-78858"}},
    25958: {"fill_blank": {"long": 78858.0}, "set_blank": {"long": {"notes": "wait for another reaction to the top to get exact resistance (~78858)"}}},
    25993: {"fill_blank": {"short": 0.916}, "set_blank": {"short": {"notes": "needs more touches of 0.916 first"}}},
    26020: {"set_trig": {0.07769: {"trig": 0.0841}}},
    26050: {"drop": True},
    26088: {"fill_blank": {"long": 79148.0}},
    26124: {"drop_trig": [0.09511]},
    26125: {"drop_trig": [80418.0]},
    26126: {"fill_blank": {"long": 293.3}},
    26136: {"fill_blank": {"long": 0.1251}, "set": {"box": "0.1213-0.1251"}},
    26154: {"set_trig": {3.0: {"trig": None, "notes": "break of daily resistance with volume (level on chart only)", "confidence": "low"}}},
    26174: {"drop_side_trig": {"short": [81600.0]}},
    26227: {"set": {"symbol": "CRVUSDT", "notes": "header says XRPUSDT but text is about CRV"}},
    26242: {"fill_blank": {"long": 81957.0}},
    26252: {"fill_blank": {"short": 78760.0}, "set_blank": {"short": {"setup_type": "pullback", "notes": "if missed the break of 78760: short on pullback or setup candle; LH/LL below 75557 = trend confirmation"}}},
    26311: {"drop": True},
    26325: {"fill_blank": {"long": 0.3523}, "set_blank": {"long": {"notes": "long needs retest/reject of 0.3523 and a higher low first"}}},
    26326: {"set_trig": {1.998: {"trigger_role": "risky/early"}, 1.864: {"trigger_role": "main"}, 2.149: {"trigger_role": ""}}},
    26334: {"drop_blank": True, "set_trig": {661.63: {"side": "long", "setup_type": "range_breakout_trigger"}, 655.02: {"setup_type": "fakeout"}}},
    26342: {"drop_blank": True, "add": [{"side": "long", "trig": 679.24, "trigger_role": "risky/early"}, {"side": "long", "trig": 724.94, "trigger_role": "main", "notes": "ATH"}]},
    26363: {"drop_trig": [58.976]},
    26627: {"set_trig": {0.08275: {"trigger_role": "first sign", "break_confirmation": "close"}, 0.08385: {"trigger_role": "risky/early"}}},
    26677: {"drop_side_trig": {"short": [0.0868]}},
    26685: {"drop_side_trig": {"long": [0.719]}},
    26941: {"drop_side_trig": {"long": [0.08192]}},
    27041: {"drop_side_trig": {"long": [0.378]}},
    27159: {"fill_blank": {"short": 0.6743}, "set": {"box": "0.6743-0.7012"}},
    27170: {"drop_side_trig": {"long": [0.04074]}},
    27403: {"drop": True},
    25792: {"add": [{"side": "short", "trig": 68088.0, "trigger_role": "risky/early", "notes": "momentum is bullish so no logical short now; if a sharp drop: first short trigger 68088", "confidence": "medium"}]},
    25962: {"add": [{"side": "long", "trig": 0.1337, "confirmations": ["volume"], "notes": "long if price moves to the 0.1337 top with rising volume (break of top)", "confidence": "medium"}]},
    27498: {"add": [{"side": "long", "trig": 0.29, "box": "0.28-0.29", "entry_type": "stop", "confirmations": ["order book"],
                     "notes": "resistance zone 0.28-0.29 full of sell orders; long once price clears them, stop-buy near the zone (re-check order book)", "confidence": "medium"}]},
    27565: {"drop_trig": [116.28]},
    27577: {"drop_trig": [11.467], "set_trig": {10.674: {"side": "long"}}, "set": {"box": "10.07-10.674", "validity_level": ""}},
    27584: {"set_trig": {0.2239: {}}, "fix_anaphora": {"short": 0.2159}, "set": {"box": "0.2159-0.2239"}},
}



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
            T = r["_trig"]
            eq = lambda xs: T is not None and any(abs(T - x) < 1e-9 for x in xs)
            if eq(m.get("drop_trig", [])) and not eq(m.get("keep_side_trig", {}).get(r["side"], [])):
                continue
            if eq(m.get("drop_side_trig", {}).get(r["side"], [])):
                continue
            if r["side"] in m.get("drop_side", []):
                continue
            if m.get("keep_only_trig") and not eq(m["keep_only_trig"]):
                continue
            if T is None and m.get("drop_blank"):
                continue
            if T is None and r["side"] in m.get("fill_blank", {}):
                r["_trig"] = m["fill_blank"][r["side"]]
                r["confidence"] = "medium"
                r["notes"] = (r["notes"] + "; " if r["notes"] else "") + "level filled in manual review from the same post"
                for k, v in m.get("set_blank", {}).get(r["side"], {}).items():
                    set_field(r, k, v)
            elif T is None and r["side"] in m.get("set_blank", {}):
                for k, v in m["set_blank"][r["side"]].items():
                    set_field(r, k, v)
            if r["side"] in m.get("fix_anaphora", {}) and "anaphora" in r["notes"]:
                r["_trig"] = m["fix_anaphora"][r["side"]]
            for k, v in m.get("set", {}).items():
                set_field(r, k, v)
            for tv, fields in m.get("set_trig", {}).items():
                if T is not None and abs(T - tv) < 1e-9:
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
            if "outcome_override" in a:
                r["outcome_override"] = a["outcome_override"]
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
