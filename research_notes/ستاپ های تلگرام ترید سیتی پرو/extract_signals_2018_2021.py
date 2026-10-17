#!/usr/bin/env python3
"""Extract trade calls / setups from Trade City Pro (@tradecity_pro), 2018-2021.

Input : data/cache/telegram/main_signals_A_2018_2021.jsonl  (pre-filtered subset)
        data/cache/telegram/main_all.jsonl                  (full archive, for follow-ups)
Output: signals_2018_2021.csv            (one row per call leg)
        signals_2018_2021_review.txt     (auto-parse vs. text + follow-up candidates, for manual review)
        signals_2018_2021_stats.json     (aggregates used in signals_2018_2021.md)

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
URL = "https://t.me/tradecity_pro/{}"
FOLLOWUP_DAYS = 14

COLUMNS = [
    "post_id", "date_utc", "symbol", "timeframe", "side", "setup_type", "entry", "entry_type",
    "stop", "targets", "stated_rr", "conditions", "outcome_reported", "confidence",
    # extra columns (not requested, but useful and documented in the .md)
    "leg", "url", "risk_pct", "stop_pct", "rr_tp1_calc", "n_targets", "completeness",
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


RE_HASHSYM = re.compile(r"#([A-Za-z]{2,10}(?:[A-Z]\d{2}|usdt|usd|btc|busd)?)\b", re.I)
SKIP_TAGS = {"LONG", "SHORT", "WATCH", "DAILY", "WEEKLY", "RISKY", "VIEW", "RESULT", "RESULTS", "VIP",
             "MONTHLY", "BITMEX", "LOG", "TIP", "4H", "1H", "15M", "4HOURS", "RISKYSHORT", "SHORT", "BUY"}


def find_symbol(t: str, date: str) -> str:
    for m in RE_HASHSYM.finditer(t):
        tag = m.group(1).upper()
        if tag in SKIP_TAGS or tag.startswith("RISKY"):
            continue
        return norm_symbol(tag, date)
    m = re.search(r"(?i)\b(?:buy|long|sell|short)\s+(btc|xrp|ada|eos|eth|trx)\b", t)
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
    for m in re.finditer(r"(?i)(?:target|tp|تارگت)\s*(?:\d|scalp)?\s*[:：]?\s*(" + NUM + r"(?:\s*-\s*" + NUM + r")?)", t):
        v = m.group(1)
        # skip "target 1" style index captured as value
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
    d["entry"] = (grab(r"(?:entry(?: price)?|entery zone|buy zone|sell zone|long zone|buy|long)\s*[:：]?\s*(" + NUM
                       + r"(?:\s*[-_]\s*" + NUM + r")?)", one))
    d["stop"] = grab(r"(?:\bsl\b|stop loss|stoploss|stoop loss|\bstop\b|حد ضرر|استاپ لاس|استاپ)\s*(?:under|above|زیر|بالای)?\s*[:：]?\s*(" + NUM + r"%?)", one)
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
#   origin: "public" = call posted in this channel; "example" = didactic example ("not for trading");
#           "position_note" = author describing own open position/hold advice;
#   conf: parse confidence (high = all stated numbers unambiguous, medium = some interpretation /
#         prose, low = levels only on chart image or heavily conditional)
# Non-call posts are listed in NONCALL with their category.

MANUAL: dict = {}
MANUAL_OUTCOME: dict = {}
NONCALL: dict = {}
# @@MANUAL@@

SETUP_TYPES = ["range_breakout", "trendline_break", "pullback", "indecision_trigger", "fakeout",
               "momentum_rsi", "ma_signal", "pattern", "support_resistance", "fib_retracement",
               "market_scalp", "other"]


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
    e, s = mid(entry), first_num(stop)
    tp = first_num(targets.split(";")[0]) if targets else None
    if not (e and s and tp) or stop.strip().endswith("%"):
        return None
    risk = abs(e - s)
    if risk == 0:
        return None
    rew = (tp - e) if side == "long" else (e - tp)
    return round(rew / risk, 2)


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
            assert leg["side"] in ("long", "short"), (pid, leg["side"])
            sp = stop_pct(leg["entry"], leg["stop"])
            leg["stop_pct"] = "" if sp is None else sp
            rr = rr_tp1(leg["entry"], leg["stop"], leg["targets"], leg["side"])
            leg["rr_tp1_calc"] = "" if rr is None else rr
            leg["n_targets"] = len([x for x in leg["targets"].split(";") if x]) if leg["targets"] else 0
            leg["completeness"] = completeness(leg)
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

    # ------------------------------------------------------------------ stats
    pub = [l for l in legs_out if l["call_origin"] == "public"]
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
