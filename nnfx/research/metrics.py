"""Decision metrics (doc 03 §4), effective sample size and BCa intervals (§8).

Unit of R: 1R is the cash risked by one position (1% of equity at entry). An
entry risks 2R, and its R-multiple is the sum over its legs - so position 1
resolves near +0.67R / -1R and position 2 loses 1R or runs. Win rate is
reported and never optimised.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from statistics import NormalDist

import numpy as np
import pandas as pd

from nnfx.brokers.sim import Trade
from nnfx.data.bars import BarFrame, ns

_N = NormalDist()


def utc(x: str | pd.Timestamp) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


@dataclass(frozen=True)
class Entry:
    symbol: str
    signal_time: str
    direction: int
    entry_type: str
    entry_time: str
    exit_time: str
    r: float
    net_pnl: float
    risk_cash: float
    carry: float
    spliced: bool = False


def entries_from_trades(trades: Sequence[Trade]) -> list[Entry]:
    groups: dict[tuple[str, str], list[Trade]] = defaultdict(list)
    for t in trades:
        groups[(t.symbol, t.signal_time)].append(t)
    out: list[Entry] = []
    for (sym, sig), legs in sorted(
        groups.items(), key=lambda kv: (min(t.entry_time for t in kv[1]), kv[0])
    ):
        risk = sum(t.risk_cash for t in legs)
        unit = risk / 2.0 if risk > 0 else 1.0
        net = sum(t.net_pnl for t in legs)
        out.append(
            Entry(
                symbol=sym,
                signal_time=sig,
                direction=legs[0].direction,
                entry_type=legs[0].entry_type,
                entry_time=min(t.entry_time for t in legs),
                exit_time=max(t.exit_time for t in legs),
                r=net / unit,
                net_pnl=net,
                risk_cash=risk,
                carry=sum(t.carry for t in legs),
            )
        )
    return out


# ------------------------------------------------------------------ splices
class SplicePoolingError(RuntimeError):
    pass


def tag_spliced_from_frames(
    entries: Sequence[Entry], frames: Mapping[str, BarFrame]
) -> list[Entry]:
    out = []
    for e in entries:
        f = frames.get(e.symbol)
        sp = False
        if f is not None and f.has("spliced"):
            ts = utc(e.entry_time)
            k = int(np.searchsorted(ns(f.index), ts.value, side="right")) - 1
            sp = bool(f.column("spliced")[max(k, 0)])
        out.append(Entry(**{**asdict(e), "spliced": sp}))
    return out


def split_by_splice(entries: Sequence[Entry]) -> tuple[list[Entry], list[Entry]]:
    """(native, spliced) - reported separately, never pooled."""
    return [e for e in entries if not e.spliced], [e for e in entries if e.spliced]


def require_unpooled(entries: Sequence[Entry]) -> None:
    kinds = {e.spliced for e in entries}
    if len(kinds) > 1:
        raise SplicePoolingError(
            "refusing to pool spliced (spot-extended) and native-perp results; report them separately (doc 03 §2b)"
        )


# ----------------------------------------------------------------- bootstrap
def bca_interval(
    x: Sequence[float] | np.ndarray,
    stat: Callable[[np.ndarray], float] = lambda a: float(np.mean(a)),
    *,
    n_boot: int = 5000,
    alpha: float = 0.05,
    rng: np.random.Generator | None = None,
) -> tuple[float, float]:
    """Bias-corrected and accelerated bootstrap interval (Efron 1987).

    R-multiple distributions are right-skewed and fat-tailed, so the normal
    approximation is not used (criterion 1). ``rng`` is injected for determinism.
    """
    a = np.asarray(x, dtype="float64")
    n = len(a)
    if n < 3:
        return (float("nan"), float("nan"))
    rng = rng or np.random.default_rng(0)
    theta = stat(a)
    idx = rng.integers(0, n, size=(n_boot, n))
    boots = np.array([stat(a[i]) for i in idx])
    prop = float(np.mean(boots < theta)) + 0.5 * float(np.mean(boots == theta))
    prop = min(max(prop, 1.0 / (n_boot + 1)), 1 - 1.0 / (n_boot + 1))
    z0 = _N.inv_cdf(prop)
    jack = np.array([stat(np.delete(a, i)) for i in range(n)])
    d = jack.mean() - jack
    denom = 6.0 * (np.sum(d**2) ** 1.5)
    acc = float(np.sum(d**3) / denom) if denom > 0 else 0.0

    def adj(q: float) -> float:
        z = _N.inv_cdf(q)
        return _N.cdf(z0 + (z0 + z) / (1 - acc * (z0 + z)))

    lo_q, hi_q = adj(alpha / 2), adj(1 - alpha / 2)
    return float(np.quantile(boots, lo_q)), float(np.quantile(boots, hi_q))


# ---------------------------------------------------------- effective sample
def effective_sample_size(
    entries: Sequence[Entry],
    closes: Mapping[str, pd.Series] | None = None,
    *,
    rho_override: float | None = None,
    min_overlap: int = 5,
) -> tuple[float, float, float]:
    """``N_eff = N / (1 + (m - 1) * rho)`` (doc 03 §8.1).

    ``m`` is the mean number of concurrent entries (averaged over entries), and
    ``rho`` the mean pairwise correlation of direction-signed daily returns of
    concurrent entries over their overlap. Returns ``(n_eff, m, rho)``.
    """
    n = len(entries)
    if n == 0:
        return 0.0, 0.0, 0.0
    spans = [(utc(e.entry_time), utc(e.exit_time)) for e in entries]
    conc = []
    pairs: list[tuple[int, int, pd.Timestamp, pd.Timestamp]] = []
    for i, (a0, a1) in enumerate(spans):
        k = 1
        for j, (b0, b1) in enumerate(spans):
            if i != j and a0 <= b1 and b0 <= a1:
                k += 1
                if j > i:
                    pairs.append((i, j, max(a0, b0), min(a1, b1)))
        conc.append(k)
    m = float(np.mean(conc))
    if rho_override is not None:
        rho = rho_override
    elif closes is None or not pairs:
        rho = 0.0
    else:
        rets = {s: np.log(c).diff() for s, c in closes.items()}
        cs: list[float] = []
        for i, j, t0, t1 in pairs:
            ei, ej = entries[i], entries[j]
            if ei.symbol == ej.symbol:
                cs.append(1.0)
                continue
            if ei.symbol not in rets or ej.symbol not in rets:
                continue
            ri = rets[ei.symbol].loc[t0:t1] * ei.direction
            rj = rets[ej.symbol].loc[t0:t1] * ej.direction
            both = pd.concat([ri, rj], axis=1, join="inner").dropna()
            if len(both) >= min_overlap and both.std().min() > 0:
                cs.append(float(both.corr().iloc[0, 1]))
        rho = float(np.mean(cs)) if cs else 0.0
    design = 1 + (m - 1) * max(rho, 0.0)
    return n / design, m, rho


# ------------------------------------------------------------------- metrics
@dataclass
class Metrics:
    n_entries: int
    n_legs: int
    expectancy_r: float
    expectancy_ci: tuple[float, float]
    r_std: float
    r_quantiles: dict[str, float]
    win_rate: float
    profit_factor: float
    sharpe: float
    sortino: float
    max_drawdown: float
    max_drawdown_bars: int
    longest_losing_streak: int
    cagr: float
    mar: float
    time_in_market: float
    total_return: float
    carry_share: float
    n_eff: float = float("nan")
    mean_concurrency: float = float("nan")
    mean_rho: float = float("nan")
    per_symbol: dict[str, dict[str, float]] = field(default_factory=dict)
    provisional: bool = True
    flags: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lo, hi = self.expectancy_ci
        return (
            f"entries={self.n_entries} E[R]={self.expectancy_r:+.3f} [{lo:+.3f}, {hi:+.3f}] "
            f"win%={self.win_rate:.1%} PF={self.profit_factor:.2f} Sharpe={self.sharpe:.2f} "
            f"Sortino={self.sortino:.2f} MaxDD={self.max_drawdown:.1%} MAR={self.mar:.2f} "
            f"N_eff={self.n_eff:.0f} TiM={self.time_in_market:.0%}"
            + (" PROVISIONAL(<500 entries)" if self.provisional else "")
            + ("".join(f" [{f}]" for f in self.flags))
        )


def drawdown(equity: pd.Series) -> tuple[float, int]:
    if equity.empty:
        return 0.0, 0
    v = equity.to_numpy(dtype="float64")
    peak = np.maximum.accumulate(v)
    dd = 1 - v / peak
    longest = cur = 0
    for x in dd:
        cur = cur + 1 if x > 1e-12 else 0
        longest = max(longest, cur)
    return float(dd.max()), longest


def losing_streak(rs: Sequence[float]) -> int:
    best = cur = 0
    for r in rs:
        cur = cur + 1 if r < 0 else 0
        best = max(best, cur)
    return best


def compute_metrics(
    trades: Sequence[Trade],
    equity: pd.Series,
    *,
    periods_per_year: float = 252.0,
    closes: Mapping[str, pd.Series] | None = None,
    rng: np.random.Generator | None = None,
    n_boot: int = 2000,
    volume_flags: Sequence[str] = (),
) -> Metrics:
    entries = entries_from_trades(trades)
    rs = np.array([e.r for e in entries], dtype="float64")
    wins, losses = rs[rs > 0].sum(), -rs[rs < 0].sum()
    ret = equity.pct_change().dropna() if len(equity) > 1 else pd.Series(dtype="float64")
    sd = float(ret.std(ddof=1)) if len(ret) > 1 else 0.0
    down = ret[ret < 0]
    dsd = float(np.sqrt(np.mean(np.square(down)))) if len(down) else 0.0
    mu = float(ret.mean()) if len(ret) else 0.0
    max_dd, dd_bars = drawdown(equity)
    years = len(equity) / periods_per_year if len(equity) else 0.0
    total = float(equity.iloc[-1] / equity.iloc[0] - 1) if len(equity) > 1 else 0.0
    cagr = (
        (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else -1.0 if total <= -1 else 0.0
    )
    in_mkt = 0.0
    if len(equity) and entries:
        idx = equity.index
        mask = np.zeros(len(idx), dtype=bool)
        for e in entries:
            mask |= (idx >= utc(e.entry_time)) & (idx <= utc(e.exit_time))
        in_mkt = float(mask.mean())
    per_sym: dict[str, dict[str, float]] = {}
    for s in sorted({e.symbol for e in entries}):
        r_s = np.array([e.r for e in entries if e.symbol == s])
        per_sym[s] = {"entries": float(len(r_s)), "expectancy_r": float(r_s.mean())}
    n_eff, m, rho = effective_sample_size(entries, closes)
    gross_pnl = sum(e.net_pnl for e in entries)
    carry = sum(e.carry for e in entries)
    flags = [f"TICK VOLUME: {s}" for s in volume_flags]
    return Metrics(
        n_entries=len(entries),
        n_legs=len(trades),
        expectancy_r=float(rs.mean()) if len(rs) else 0.0,
        expectancy_ci=bca_interval(rs, rng=rng, n_boot=n_boot)
        if len(rs) >= 3
        else (float("nan"), float("nan")),
        r_std=float(rs.std(ddof=1)) if len(rs) > 1 else 0.0,
        r_quantiles={
            q: float(np.quantile(rs, float(q))) for q in ("0.05", "0.25", "0.5", "0.75", "0.95")
        }
        if len(rs)
        else {},
        win_rate=float((rs > 0).mean()) if len(rs) else 0.0,
        profit_factor=float(wins / losses) if losses > 0 else (math.inf if wins > 0 else 0.0),
        sharpe=mu / sd * math.sqrt(periods_per_year) if sd > 0 else 0.0,
        sortino=mu / dsd * math.sqrt(periods_per_year) if dsd > 0 else 0.0,
        max_drawdown=max_dd,
        max_drawdown_bars=dd_bars,
        longest_losing_streak=losing_streak(rs.tolist()),
        cagr=cagr,
        mar=cagr / max_dd if max_dd > 0 else 0.0,
        time_in_market=in_mkt,
        total_return=total,
        carry_share=carry / gross_pnl if gross_pnl else 0.0,
        n_eff=n_eff,
        mean_concurrency=m,
        mean_rho=rho,
        per_symbol=per_sym,
        provisional=len(entries) < 500,
        flags=flags,
    )
