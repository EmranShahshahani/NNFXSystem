"""``nnfx`` command line."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from nnfx.brokers.costs import CostModel
from nnfx.config import SystemConfig, load_system_config
from nnfx.data.bars import BarFrame
from nnfx.data.feeds import read_bars_csv
from nnfx.data.gates import run_gates
from nnfx.data.session import resample_to_daily
from nnfx.instruments import InstrumentRegistry, InstrumentSpec


def _registry(args: argparse.Namespace) -> InstrumentRegistry:
    return InstrumentRegistry.load(Path(args.instruments))


def _load(
    args: argparse.Namespace, cfg: SystemConfig, symbol: str, path: str, inst: InstrumentSpec
) -> BarFrame:
    f = read_bars_csv(path, symbol, timeframe=args.timeframe, volume_kind=inst.volume_kind)
    if args.timeframe == "H1":
        f = resample_to_daily(f, inst, cfg.session)
    return f


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", default="config/system.yaml")
    p.add_argument("--instruments", default="config/instruments.yaml")
    p.add_argument("--venue", default="config/venues/backtest.yaml")
    p.add_argument(
        "--timeframe",
        choices=("D1", "H1"),
        default="D1",
        help="H1 input is resampled under the configured session close",
    )
    p.add_argument("--csv", action="append", required=True, metavar="SYMBOL=PATH")


def _pairs(items: Sequence[str]) -> list[tuple[str, str]]:
    out = []
    for it in items:
        if "=" not in it:
            raise SystemExit(f"--csv expects SYMBOL=PATH, got {it!r}")
        s, p = it.split("=", 1)
        out.append((s, p))
    return out


def cmd_backtest(args: argparse.Namespace) -> int:
    from nnfx.harness.backtest import BacktestHarness
    from nnfx.journal.journal import Journal
    from nnfx.research.metrics import compute_metrics

    cfg = load_system_config(args.config)
    reg = _registry(args)
    frames, inst = {}, {}
    for sym, path in _pairs(args.csv):
        inst[sym] = reg.spec(sym)
        frames[sym] = _load(args, cfg, sym, path, inst[sym])
    costs = None if args.zero_costs else CostModel.from_venue(args.venue)
    journal = Journal(args.journal) if args.journal else None
    res = BacktestHarness(
        cfg,
        inst,
        frames,
        costs=costs,
        journal=journal,
        gate_kwargs={"max_missing_sessions": args.max_missing_sessions},
    ).run()
    print("TRADES")
    print(res.trade_table())
    print()
    print("EQUITY")
    print(res.equity_table(every=max(1, len(res.equity) // 40)))
    print()
    print(compute_metrics(res.trades, res.equity, volume_flags=res.volume_flags).summary())
    if args.out:
        res.write(args.out)
        print(f"wrote {args.out} (sha256 {res.digest()[:16]})")
    return 0


def cmd_gates(args: argparse.Namespace) -> int:
    cfg = load_system_config(args.config)
    reg = _registry(args)
    bad = 0
    for sym, path in _pairs(args.csv):
        inst = reg.spec(sym)
        rep = run_gates(
            _load(args, cfg, sym, path, inst),
            inst,
            close_tz=cfg.session.close_tz,
            max_missing_sessions=args.max_missing_sessions,
        )
        print(rep.render())
        bad += len(rep.failures)
    return 1 if bad else 0


def cmd_screen(args: argparse.Namespace) -> int:
    from nnfx.indicators.base import create, registered
    from nnfx.research.lookahead import run_gate_1_2
    from nnfx.research.partition import Partition
    from nnfx.research.screening import ScreeningReport, gate3, gate4, gate5

    cfg = load_system_config(args.config)
    reg = _registry(args)
    frames = [_load(args, cfg, s, p, reg.spec(s)) for s, p in _pairs(args.csv)]
    for o in run_gate_1_2(frames[0], stride=args.stride):
        print(o.render())
    rep = ScreeningReport()
    dev = Partition.for_market(args.market).development
    confs = [create(k, n) for k, n in registered("confirmation")]
    rep.rows += [gate3(c, frames) for c in confs]
    c1 = create("confirmation", cfg.slots.c1.name, cfg.slots.c1.params)
    rep.rows += [gate4(c1, c, frames, dev) for c in confs if c.name != c1.name]
    rep.rows += [gate5(create(k, n), frames[0]) for k, n in registered()]
    print(rep.render())
    return 0


def cmd_catalogue(args: argparse.Namespace) -> int:
    from nnfx.indicators.catalogue import render_catalogue

    print(render_catalogue())
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    from nnfx.research.logs import reconcile_all

    reports = reconcile_all(Path(args.dir), write=not args.dry_run)
    for r in reports:
        print(r.render())
    if not reports:
        print(f"no *.jsonl logs in {args.dir}")
    return 0


def cmd_env(args: argparse.Namespace) -> int:
    from nnfx.env import fingerprint, workstation_id

    fp = fingerprint()
    print(
        json.dumps(
            {"workstation": workstation_id(), "digest": fp.digest, **fp.model_dump(mode="json")},
            indent=1,
        )
    )
    return 0


def cmd_determinism(args: argparse.Namespace) -> int:
    from nnfx.research.determinism import check, write_reference

    if args.write_reference:
        write_reference()
        print("reference written")
        return 0
    res = check()
    print(f"{res.status}: {res.detail}")
    return 0 if res.status == "OK" else 1


def cmd_fetch(args: argparse.Namespace) -> int:
    from nnfx.data.feeds import write_bars_csv
    from nnfx.data.manifest import record_or_verify

    start, end = pd.Timestamp(args.start, tz="UTC"), pd.Timestamp(args.end, tz="UTC")
    if args.feed == "dukascopy":
        from nnfx.data.dukascopy import DukascopyFeed

        feed_name = "dukascopy"
        frame = DukascopyFeed(Path(args.cache) / "dukascopy").bars(args.symbol, start, end)
    else:
        from nnfx.data.ccxt_feed import CcxtFeed, make_exchange

        cf = CcxtFeed(make_exchange(args.exchange))
        feed_name = cf.name
        frame = cf.bars(args.symbol, start, end)
    out = (
        Path(args.cache) / feed_name / (args.symbol.replace("/", "_").replace(":", "_") + ".H1.csv")
    )
    write_bars_csv(frame, out)
    status = record_or_verify(feed_name, frame)
    print(f"{frame}: cached at {out}; manifest {status}")
    return 0


def cmd_ablate(args: argparse.Namespace) -> int:
    from nnfx.research.ablation import run_ablation
    from nnfx.research.evaluate import Evaluator
    from nnfx.research.trials import ResearchState

    cfg = load_system_config(args.config)
    reg = _registry(args)
    frames = {s: _load(args, cfg, s, p, reg.spec(s)) for s, p in _pairs(args.csv)}
    ev = Evaluator(
        {s: reg.spec(s) for s in frames},
        frames,
        market=args.market,
        costs=CostModel.from_venue(args.venue),
        research=ResearchState(Path(args.research)),
    )
    rep = run_ablation(cfg, ev, rules=args.rule or None)
    print(rep.render())
    print(f"\nlogged trial count: {ev.research.trial_count() if ev.research else 'n/a'}")
    return 0


def cmd_live(args: argparse.Namespace) -> int:
    from nnfx.brokers.paper import PaperBroker
    from nnfx.harness.conversion import Conversion
    from nnfx.harness.live import LiveHarness
    from nnfx.journal.journal import Journal

    cfg = load_system_config(args.config)
    reg = _registry(args)
    frames = {s: _load(args, cfg, s, p, reg.spec(s)) for s, p in _pairs(args.csv)}
    inst = {s: reg.spec(s) for s in frames}
    state = Path(args.state_dir)
    now = pd.Timestamp(args.now, tz="UTC") if args.now else pd.Timestamp.now(tz="UTC")
    broker = PaperBroker(
        inst,
        CostModel.from_venue(args.venue).with_toggles(cfg.costs),
        cfg.account.initial_equity,
        cfg.account.currency,
        Conversion(cfg.account.currency, frames),
        state_path=state / "paper_broker.json",
    )
    h = LiveHarness(
        cfg,
        inst,
        list(frames),
        lambda s, t: frames[s].between(None, t),
        broker,
        Journal(state / "journal.jsonl"),
        clock=lambda: now,
        report_dir=Path("reports/daily"),
        alert=lambda m: print("ALERT:", m, file=sys.stderr),
    )
    rep = h.run_cycle()
    print(rep.render())
    return 2 if rep.halted else 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="nnfx", description="NNFX engine and validation platform")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("backtest", help="CSV bars -> trade list and equity curve")
    _add_common(p)
    p.add_argument("--out")
    p.add_argument("--journal")
    p.add_argument("--zero-costs", action="store_true")
    p.add_argument("--max-missing-sessions", type=int, default=0)
    p.set_defaults(fn=cmd_backtest)

    p = sub.add_parser("gates", help="run the integrity gates on CSV bars")
    _add_common(p)
    p.add_argument("--max-missing-sessions", type=int, default=0)
    p.set_defaults(fn=cmd_gates)

    p = sub.add_parser("screen", help="screening gates 1-5 (no performance data)")
    _add_common(p)
    p.add_argument("--market", choices=("fx", "crypto"), default="fx")
    p.add_argument("--stride", type=int, default=25)
    p.set_defaults(fn=cmd_screen)

    p = sub.add_parser("ablate", help="rule ablation on the development segment")
    _add_common(p)
    p.add_argument("--market", choices=("fx", "crypto"), default="fx")
    p.add_argument("--research", default="research")
    p.add_argument("--rule", action="append")
    p.set_defaults(fn=cmd_ablate)

    p = sub.add_parser("live", help="run one daily cycle against the PaperBroker")
    _add_common(p)
    p.add_argument("--state-dir", default="runs/live")
    p.add_argument("--now")
    p.set_defaults(fn=cmd_live)

    p = sub.add_parser(
        "fetch", help="fetch H1 history into the cache and write/verify its manifest"
    )
    p.add_argument("--feed", choices=("dukascopy", "ccxt"), required=True)
    p.add_argument("--exchange", default="binance")
    p.add_argument("--symbol", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--cache", default="data/cache")
    p.set_defaults(fn=cmd_fetch)

    p = sub.add_parser("catalogue", help="list the indicator pool")
    p.set_defaults(fn=cmd_catalogue)

    p = sub.add_parser("env", help="print the environment fingerprint")
    p.set_defaults(fn=cmd_env)

    p = sub.add_parser("determinism", help="reproduce the committed reference run")
    p.add_argument("--write-reference", action="store_true")
    p.set_defaults(fn=cmd_determinism)

    r = sub.add_parser("research", help="research-state utilities")
    rsub = r.add_subparsers(dest="rcmd", required=True)
    p = rsub.add_parser(
        "reconcile", help="dedupe append-only logs by id; report per-workstation counts"
    )
    p.add_argument("--dir", default="research")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_reconcile)

    args = ap.parse_args(argv)
    rc: int = args.fn(args)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
