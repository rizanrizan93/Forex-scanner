from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .aggregation import aggregate_ticks
from .collectors.mt5 import MT5Collector
from .config import load_project_config
from .demo import generate_demo_ticks
from .quality import assess_ticks
from .storage.audit import JsonlAuditStore


UTC = timezone.utc


def cmd_validate_config(args: argparse.Namespace) -> int:
    cfg = load_project_config(args.root)
    print(f"CONFIG_OK pairs={len(cfg.pairs)} timeframes={','.join(cfg.timeframes)} mode={cfg.risk['mode']}")
    return 0


def cmd_demo_ingest(args: argparse.Namespace) -> int:
    cfg = load_project_config(args.root)
    if args.symbol.upper() not in cfg.pair_map:
        raise SystemExit(f"unknown configured pair: {args.symbol}")
    start = datetime.now(tz=UTC).replace(second=0, microsecond=0) - timedelta(minutes=args.minutes)
    ticks = generate_demo_ticks(args.symbol.upper(), start, minutes=args.minutes)
    report = assess_ticks(ticks, now=ticks[-1].timestamp)
    bars = aggregate_ticks(ticks, "M1", cfg.timeframes["M1"])
    audit_path = Path(args.root or Path(__file__).resolve().parents[2]) / "data" / "audit" / "demo.jsonl"
    JsonlAuditStore(audit_path).append({
        "timestamp": datetime.now(tz=UTC),
        "kind": "DEMO_INGEST",
        "symbol": args.symbol.upper(),
        "ticks": len(ticks),
        "bars_m1": len(bars),
        "quality_valid": report.valid,
        "issues": list(report.issues),
    })
    print(f"DEMO_OK symbol={args.symbol.upper()} ticks={len(ticks)} bars_m1={len(bars)} quality={report.valid}")
    return 0


def cmd_mt5_smoke(args: argparse.Namespace) -> int:
    cfg = load_project_config(args.root)
    symbol = args.symbol.upper()
    if symbol not in cfg.pair_map:
        raise SystemExit(f"unknown configured pair: {symbol}")
    end = datetime.now(tz=UTC)
    start = end - timedelta(seconds=args.seconds)
    with MT5Collector(args.terminal_path) as collector:
        ticks = collector.fetch_ticks(symbol, start, end)
    report = assess_ticks(ticks, now=end)
    print(f"MT5_READ_OK symbol={symbol} ticks={len(ticks)} quality={report.valid} issues={','.join(report.issues) or 'NONE'}")
    return 0 if report.valid else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fx-scanner")
    parser.add_argument("--root", default=None, help="project root; defaults to package root")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("validate-config")
    p.set_defaults(func=cmd_validate_config)

    p = sub.add_parser("demo-ingest")
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--minutes", type=int, default=10)
    p.set_defaults(func=cmd_demo_ingest)

    p = sub.add_parser("mt5-smoke")
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--seconds", type=int, default=30)
    p.add_argument("--terminal-path", default=None)
    p.set_defaults(func=cmd_mt5_smoke)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
