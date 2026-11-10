"""Market Filter Blocks: the Dominance Regime and the Relative-Strength Sieve (ticket 20, ADR 10 §24).

Videos 12, 59, 66, 83 and 84. Both read the market series in ``StrategyData.market``
(``market.py``) and say not-applicable, never a pass, where a series is missing.

====================  ==========================================================
Block                 What it does
====================  ==========================================================
``dominance_regime``  Market Filter. BTC/USDT's trend against BTC.D's trend picks
                      the allocation: BTC-led, Altseason or Altcoin Flush
``relative_strength`` Market Filter. An altcoin long needs ALT/BTC (and optionally
                      ALT/ETH or ETH/BTC) trending up; a short needs it down
====================  ==========================================================

A trend is the Dow state (``structure.waves``) of a series' closes on the Block's
timeframe role.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import Field

from nnfx.strategy.blocks import (
    BlockKind,
    BlockParams,
    ContextOutput,
    MarketFilterBlock,
    Role,
    StrategyData,
    register,
)
from nnfx.strategy.market import pair_state, series_state


# ----------------------------------------------------------------- regime
class DominanceParams(BlockParams):
    role: Role = Field("hwc", description="تایم‌فریمی که روند BTC و دامیننس روی آن خوانده می‌شود")
    pivot_bars: int = Field(2, ge=1, description="پیوت روند داو: تعداد کندل‌های دو طرف")
    btc_symbol: str = Field("BTC/USDT", description="نماد بیت‌کوین (روند آن از داده یا سری بازار)")
    dominance: str = Field("BTC.D", description="نام سری دامیننس بیت‌کوین در داده‌های بازار")
    max_stale_bars: int = Field(
        3, ge=1, description="سری دامیننس تا این تعداد کندل قدیمی هنوز معتبر است"
    )
    altseason_trades_btc: bool = Field(
        False, description="در آلت‌سیزن خود بیت‌کوین هم لانگ شود (پیش‌فرض: فقط آلت‌کوین‌ها)"
    )


REGIME_CODES = {"btc_led": 1, "altseason": 2, "alt_flush": 3}


@register
class DominanceRegime(MarketFilterBlock[DominanceParams]):
    """The Dominance Regime matrix (video 12): BTC/USDT's trend against BTC.D's trend.

    ===========  ===================================  ===========================================
    Regime       Condition                            Directive
    ===========  ===================================  ===========================================
    BTC-led      BTC up and BTC.D up                  BTC longs only; no altcoin trades
    Altseason    BTC up or ranging and BTC.D down     altcoin longs (BTC too if asked); no shorts
    Alt flush    BTC down and BTC.D up                no BTC short; altcoin shorts, no longs
    ===========  ===================================  ===========================================

    Any other combination (BTC.D ranging, or both falling) is not in the blueprint's table
    and restricts nothing. The traded symbol is BTC when it equals ``btc_symbol``, otherwise
    an altcoin. Candidates are tagged with the regime (``btc_led``, ``altseason``,
    ``alt_flush``). Without the BTC.D series or a BTC trend at a bar the check is
    not-applicable.
    """

    kind = BlockKind.MARKET_FILTER
    type = "dominance_regime"
    title_fa = "رژیم دامیننس (BTC‌محور، آلت‌سیزن، آلت‌فلاش)"
    sources = ("tcp-blueprint 02: video 12 (regime matrix)", "tcp-blueprint 07: video 66")
    Params = DominanceParams

    def compute(self, data: StrategyData) -> ContextOutput:
        p = self.p
        n = len(data)
        is_btc = data.symbol == p.btc_symbol
        btc, btc_ok = series_state(data, p.btc_symbol, p.role, p.pivot_bars, p.max_stale_bars)
        dom, dom_ok = series_state(data, p.dominance, p.role, p.pivot_bars, p.max_stale_bars)
        known = btc_ok & dom_ok
        led = known & (btc > 0) & (dom > 0)
        season = known & (btc >= 0) & (dom < 0)
        flush = known & (btc < 0) & (dom > 0)
        long_ok, short_ok = np.ones(n, bool), np.ones(n, bool)
        if is_btc:
            short_ok &= ~(led | season | flush)  # BTC is never shorted in the table
            if not p.altseason_trades_btc:
                long_ok &= ~season
        else:
            long_ok &= ~(led | flush)
            short_ok &= ~(led | season)
        regime = np.select([led, season, flush], list(REGIME_CODES.values()), 0).astype("int8")
        flags = {"regime": regime, "btc_trend": btc, "dominance_trend": dom}
        tags = {name: (regime == code, regime == code) for name, code in REGIME_CODES.items()}
        return ContextOutput(long_ok, short_ok, flags, tags, available=known)


# ------------------------------------------------------------------ sieve
class SieveParams(BlockParams):
    role: Role = Field("hwc", description="تایم‌فریمی که روند نسبت‌ها روی آن خوانده می‌شود")
    pivot_bars: int = Field(2, ge=1, description="پیوت روند داو: تعداد کندل‌های دو طرف")
    btc_symbol: str = Field("BTC/USDT", description="نماد بیت‌کوین (مخرج نسبت ALT/BTC)")
    eth_symbol: str = Field("ETH/USDT", description="نماد اتریوم (برای ALT/ETH یا ETH/BTC)")
    second: Literal["off", "alt_eth", "eth_btc"] = Field(
        "off", description="شرط دوم غربال سه‌گانه: off، روند ALT/ETH، یا روند ETH/BTC"
    )
    max_stale_bars: int = Field(
        3, ge=1, description="سری نسبت تا این تعداد کندل قدیمی هنوز معتبر است"
    )


@register
class RelativeStrengthSieve(MarketFilterBlock[SieveParams]):
    """The Relative-Strength Sieve (videos 12, 59, 83): admit only altcoins stronger than BTC.

    A long needs the ALT/BTC trend up (a breakout or higher highs and higher lows); with
    ``second`` also ALT/ETH up, or ETH/BTC up (the blueprint's Ultimate Long Sieve). A short
    is the mirror: ALT/BTC down (and ALT/ETH or ETH/BTC down). A ranging ratio admits
    neither. The ratio is the cross pair when given, derived from the two exchange pairs
    otherwise. Bitcoin itself is outside the sieve. Not-applicable where a ratio is unknown.
    """

    kind = BlockKind.MARKET_FILTER
    type = "relative_strength"
    title_fa = "غربال قدرت نسبی (ALT/BTC)"
    sources = (
        "tcp-blueprint 02: video 12 (ultimate long sieve)",
        "tcp-blueprint 06: videos 59, 83 (ALT/BTC sieve)",
    )
    Params = SieveParams

    def compute(self, data: StrategyData) -> ContextOutput:
        p = self.p
        n = len(data)
        if data.symbol == p.btc_symbol:
            return ContextOutput(np.ones(n, bool), np.ones(n, bool), available=np.ones(n, bool))
        args = (p.role, p.pivot_bars, p.max_stale_bars)
        trend, known = pair_state(data, data.symbol, p.btc_symbol, *args)
        if p.second != "off":
            top, bottom = (
                (data.symbol, p.eth_symbol)
                if p.second == "alt_eth"
                else (p.eth_symbol, p.btc_symbol)
            )
            second, second_ok = pair_state(data, top, bottom, *args)
            known = known & second_ok
            up, down = (trend > 0) & (second > 0), (trend < 0) & (second < 0)
        else:
            second = np.zeros(n, "int8")
            up, down = trend > 0, trend < 0
        flags = {"alt_btc_trend": trend, "second_trend": second}
        return ContextOutput(np.where(known, up, True), np.where(known, down, True), flags,
                             available=known)  # fmt: skip
