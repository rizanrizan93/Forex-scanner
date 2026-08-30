from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import sleep

from .aggregation import aggregate_ticks
from .collectors.mt5 import MT5Collector
from .config import load_project_config
from .demo import generate_demo_ticks
from .quality import assess_ticks
from .providers.factory import build_provider_runtime
from .execution.factory import build_broker_gateway
from .execution.policy import load_execution_policy
from .execution.runtime import RuntimeSupervisor, ScheduledJob
from .storage.audit import JsonlAuditStore
from .storage.supabase_operational import SupabaseOperationalStore


UTC = timezone.utc


def cmd_validate_config(args: argparse.Namespace) -> int:
    cfg = load_project_config(args.root)
    execution = load_execution_policy(args.root)
    print(
        f"CONFIG_OK pairs={len(cfg.pairs)} timeframes={','.join(cfg.timeframes)} "
        f"research_mode={cfg.risk['mode']} execution_mode={execution.mode.value} "
        f"workers={execution.runtime['concurrent_workers']}"
    )
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


def cmd_runtime_smoke(args: argparse.Namespace) -> int:
    policy = load_execution_policy(args.root)
    counts = {"heavy_scan": 0, "fast_setup": 0, "execution_watch": 0, "position_monitor": 0}
    supervisor = RuntimeSupervisor()
    lag = policy.runtime["max_lag_seconds"]

    def handler(name: str):
        def run():
            counts[name] += 1
        return run

    mapping = {
        "heavy_scan": "heavy_scan_seconds",
        "fast_setup": "fast_setup_seconds",
        "execution_watch": "execution_watch_seconds",
        "position_monitor": "position_monitor_seconds",
    }
    for name, key in mapping.items():
        supervisor.add_job(ScheduledJob(name, policy.scheduler[key], lag[name], handler(name)))

    step = float(policy.runtime["supervisor_tick_seconds"])
    iterations = int(float(args.seconds) / step) + 1
    for i in range(iterations):
        supervisor.tick(i * step)
    health = supervisor.health()
    print(
        "RUNTIME_SMOKE_OK "
        + " ".join(f"{k}={v}" for k, v in counts.items())
        + f" healthy={health.healthy} ticks={iterations}"
    )
    return 0 if health.healthy else 2


def cmd_provider_smoke(args: argparse.Namespace) -> int:
    cfg = load_project_config(args.root)
    smoke = cfg.providers["smoke_series"].get(args.series)
    if smoke is None:
        raise SystemExit(f"unknown configured provider smoke series: {args.series}")
    runtime = build_provider_runtime(cfg.providers)
    provider_name = str(smoke["provider"])
    provider = runtime.providers[provider_name]
    result = runtime.orchestrator.fetch(
        provider,
        str(smoke["series"]),
        max_age_seconds=float(smoke["max_age_seconds"]),
    )
    value = None if result.value is None else result.value.value
    observed = None if result.value is None else result.value.observed_at.isoformat()
    age = None if result.freshness is None else round(result.freshness.age_seconds, 3)
    print(
        f"PROVIDER_SMOKE status={result.status.value} provider={provider_name} "
        f"series={smoke['series']} value={value} observed_at={observed} age_seconds={age}"
    )
    return 0 if result.usable else 2


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


def cmd_mt5_monitor(args: argparse.Namespace) -> int:
    cfg = load_project_config(args.root)
    policy = load_execution_policy(args.root)
    symbols = [pair.symbol for pair in cfg.pairs]
    gateway, session = build_broker_gateway(
        policy,
        symbols,
        backend="MT5",
        mt5_terminal_path=args.terminal_path,
    )
    store = SupabaseOperationalStore.from_env()
    interval = max(5.0, float(args.interval))
    reconnect_attempts = int(
        policy.runtime.get("reconnect", {}).get("max_attempts", 3)
    )

    def publish_once() -> None:
        session.ensure_connected(max_attempts=reconnect_attempts)
        account = gateway.account_snapshot()
        positions = gateway.open_positions()
        snapshot_id = store.publish_broker_telemetry(
            account,
            positions,
            broker_name=str(policy.mt5.get("broker_label", "HFM_CENT")),
            environment=str(args.environment).upper(),
            connection_healthy=True,
        )
        store.write_heartbeat(
            "mt5_account_monitor",
            healthy=True,
            lag_seconds=0.0,
            details={
                "account_id": account.account_id,
                "positions": len(positions),
                "snapshot_id": snapshot_id,
                "execution_mode": policy.mode.value,
            },
        )
        print(
            "MT5_MONITOR_OK "
            f"account={account.account_id} balance={account.balance:.2f} "
            f"equity={account.equity:.2f} currency={account.currency or 'UNKNOWN'} "
            f"positions={len(positions)} snapshot={snapshot_id}"
        )

    try:
        if args.once:
            publish_once()
            return 0
        while True:
            try:
                publish_once()
            except Exception as exc:
                try:
                    store.write_heartbeat(
                        "mt5_account_monitor",
                        healthy=False,
                        details={"error": f"{type(exc).__name__}: {exc}"},
                    )
                except Exception:
                    pass
                print(f"MT5_MONITOR_ERROR {type(exc).__name__}: {exc}")
            sleep(interval)
    except KeyboardInterrupt:
        print("MT5_MONITOR_STOPPED")
        return 0
    finally:
        gateway.close()


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

    p = sub.add_parser("runtime-smoke")
    p.add_argument("--seconds", type=int, default=3600)
    p.set_defaults(func=cmd_runtime_smoke)

    p = sub.add_parser("provider-smoke")
    p.add_argument("--series", default="ECB_EURUSD_REFERENCE")
    p.set_defaults(func=cmd_provider_smoke)

    p = sub.add_parser("mt5-smoke")
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--seconds", type=int, default=30)
    p.add_argument("--terminal-path", default=None)
    p.set_defaults(func=cmd_mt5_smoke)

    p = sub.add_parser("mt5-monitor")
    p.add_argument("--terminal-path", default=None)
    p.add_argument("--interval", type=float, default=15.0)
    p.add_argument("--environment", choices=["DEMO", "LIVE"], default="DEMO")
    p.add_argument("--once", action="store_true")
    p.set_defaults(func=cmd_mt5_monitor)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
