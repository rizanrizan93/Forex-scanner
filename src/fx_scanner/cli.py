from __future__ import annotations

import argparse
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import sleep
from uuid import uuid4

from .aggregation import aggregate_ticks
from .collectors.mt5 import MT5Collector
from .config import load_project_config
from .demo import generate_demo_ticks
from .quality import assess_ticks
from .providers.factory import build_provider_runtime
from .macro_ingestion import MacroEvidenceRefresher
from .cloud_runtime import CTraderCloudResearchRuntime
from .signal_producer import CTraderSignalProducer
from .producer_guards import ProductionGuardResolver
from .providers.news import ForexFactoryCalendarProvider
from .providers.transport import UrllibHttpTransport
from .execution.factory import build_broker_gateway, build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .execution.models import ExecutionMode, OrderIntent, OrderSide, OrderType
from .execution.router import ExecutionRouter
from .execution.control_plane import ControlPlaneGate, ControlPlaneRefreshWorker
from .execution.demo_autotrade import CTraderDemoAutoExecutor, SupabaseOrderAuditSink
from .execution.runtime import RuntimeSupervisor, ScheduledJob
from .storage.audit import JsonlAuditStore
from .storage.supabase_operational import SupabaseOperationalStore
from .storage.supabase_research import SupabaseResearchStore


UTC = timezone.utc


def _apply_demo_execution_threshold(cfg):
    """Apply an explicitly DEMO-only execution threshold override.

    The canonical production/research threshold in config/scoring.yaml remains
    unchanged. This override is only consumed by the cTrader DEMO signal
    producer after the broker policy has already been proven DEMO-only.
    """
    raw = os.getenv("CTRADER_DEMO_EXECUTION_CANDIDATE_MIN")
    if raw is None or not raw.strip():
        return cfg, float(cfg.scoring["states"]["execution_candidate_min"])
    try:
        demo_min = float(raw)
    except ValueError as exc:
        raise SystemExit("CTRADER_DEMO_EXECUTION_THRESHOLD_INVALID") from exc
    production_min = float(cfg.scoring["states"]["execution_candidate_min"])
    watch_min = float(cfg.scoring["states"]["watch_min"])
    if not watch_min <= demo_min <= production_min:
        raise SystemExit("CTRADER_DEMO_EXECUTION_THRESHOLD_OUT_OF_RANGE")
    states = dict(cfg.scoring["states"])
    states["execution_candidate_min"] = demo_min
    scoring = dict(cfg.scoring)
    scoring["states"] = states
    return replace(cfg, scoring=scoring), production_min


def _demo_technical_only_enabled() -> bool:
    return os.getenv("CTRADER_DEMO_TECHNICAL_ONLY", "0").strip() == "1"


def _demo_spread_limit_overrides(cfg) -> dict[str, float]:
    """Read explicit DEMO-only per-instrument spread limits."""
    raw = os.getenv("CTRADER_DEMO_XAUUSD_MAX_SPREAD_PIPS", "").strip()
    if not raw:
        return {}
    try:
        limit = float(raw)
    except ValueError as exc:
        raise SystemExit("CTRADER_DEMO_XAU_SPREAD_LIMIT_INVALID") from exc
    if "XAUUSD" not in cfg.pair_map or not 4.0 <= limit <= 50.0:
        raise SystemExit("CTRADER_DEMO_XAU_SPREAD_LIMIT_OUT_OF_RANGE")
    return {"XAUUSD": limit}


def _apply_demo_technical_only_profile(cfg):
    """Return a DEMO-only technical scalping configuration.

    Macro, cross-asset and positioning evidence are removed from conviction,
    and NEWS_BLOCK is removed from required execution guards. Canonical config
    files remain unchanged and LIVE remains locked by execution policy.
    """
    technical_weights = {
        "htf_structure": 20.0,
        "liquidity": 20.0,
        "smc_structure": 20.0,
        "displacement": 15.0,
        "session": 10.0,
        "execution_quality": 15.0,
    }
    scoring = dict(cfg.scoring)
    scoring["execution_conviction"] = technical_weights
    scoring["hard_guards"] = [
        name for name in cfg.scoring["hard_guards"] if name != "NEWS_BLOCK"
    ]
    return replace(cfg, scoring=scoring)


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


def cmd_research_cloud(args: argparse.Namespace) -> int:
    cfg = load_project_config(args.root)
    policy = load_execution_policy(args.root)
    symbols = [pair.symbol for pair in cfg.pairs]
    feed = build_ctrader_research_feed(policy, symbols)
    store = SupabaseOperationalStore.from_env()
    runtime = CTraderCloudResearchRuntime(cfg, feed, store)
    try:
        if args.once:
            report = runtime.probe(include_mtf=not args.spot_only)
            print(
                "CTRADER_CLOUD_OK "
                f"healthy={report.healthy} quotes={report.quotes_ok}/{report.quotes_total} "
                f"mtf={report.mtf_ok}/{report.mtf_total} failures={len(report.failures)}"
            )
            return 0 if report.healthy else 2
        runtime.run_forever(
            heartbeat_seconds=float(args.heartbeat),
            mtf_refresh_seconds=float(args.mtf_refresh),
        )
        return 0
    finally:
        feed.close()


def cmd_macro_source_smoke(args: argparse.Namespace) -> int:
    """Read-only diagnostic of configured official macro bindings."""
    cfg = load_project_config(args.root)
    runtime = build_provider_runtime(cfg.providers)
    refresher = MacroEvidenceRefresher(
        cfg,
        store=None,
        runtime=runtime,
    )
    currencies = sorted(cfg.providers["macro_ingestion"]["currency_areas"])
    refresher.prefetch_sources(currencies)
    for currency in currencies:
        parts = []
        for factor, bindings in refresher._bindings(currency).items():
            binding = bindings[0]
            result = runtime.orchestrator.fetch(
                binding.provider,
                binding.series,
                max_age_seconds=binding.max_age_seconds,
            )
            score = None
            if result.usable and result.value is not None:
                try:
                    score = binding.normalizer.score(result.value)
                except Exception:
                    score = None
            age = None if result.freshness is None else round(result.freshness.age_seconds, 1)
            parts.append(
                f"{factor}:{result.status.value}:"
                f"error={result.error_category.value}:score={score}:age={age}"
            )
        print(f"MACRO_SOURCE_SMOKE {currency} " + " ".join(parts))
    return 0


def cmd_macro_refresh(args: argparse.Namespace) -> int:
    """Refresh durable official macro evidence; never touches broker execution."""
    cfg = load_project_config(args.root)
    store = SupabaseResearchStore.from_env()
    report = MacroEvidenceRefresher(cfg, store).run_once()
    coverage = ",".join(
        f"{currency}:{report.coverage_by_currency[currency]:.2f}"
        for currency in sorted(report.coverage_by_currency)
    )
    below = ",".join(
        currency
        for currency in sorted(report.coverage_by_currency)
        if report.coverage_by_currency[currency] < float(cfg.macro["minimum_coverage"])
    ) or "NONE"
    print(
        "MACRO_REFRESH_OK "
        f"valid={report.valid_currencies}/{report.currencies_total} "
        f"coverage={coverage} below_minimum={below}"
    )
    configured_factors = set(cfg.providers["macro_ingestion"]["factors"])
    source_gaps = []
    for currency in sorted(report.missing_by_currency):
        gaps = sorted(configured_factors.intersection(report.missing_by_currency[currency]))
        if gaps:
            source_gaps.append(f"{currency}=" + "+".join(gaps))
    print("MACRO_REFRESH_SOURCE_GAPS " + (";".join(source_gaps) or "NONE"))
    return 0


def cmd_ctrader_signal_producer(args: argparse.Namespace) -> int:
    """Run one DEMO-only signal-production cycle; never submits broker orders."""
    cfg = load_project_config(args.root)
    policy = load_execution_policy(args.root)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("CTRADER_SIGNAL_PRODUCER_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_SIGNAL_PRODUCER_REQUIRE_DEMO")
    cfg, production_execution_min = _apply_demo_execution_threshold(cfg)
    technical_only = _demo_technical_only_enabled()
    if technical_only:
        cfg = _apply_demo_technical_only_profile(cfg)
    demo_execution_min = float(cfg.scoring["states"]["execution_candidate_min"])
    print(
        "CTRADER_DEMO_EXECUTION_THRESHOLD "
        f"active={demo_execution_min:g} production_default={production_execution_min:g}"
    )
    print(
        "CTRADER_DEMO_PROFILE "
        f"mode={'TECHNICAL_SCALPING' if technical_only else 'CANONICAL'} "
        f"macro={'DISABLED' if technical_only else 'ENABLED'}"
    )
    symbols = [pair.symbol for pair in cfg.pairs]
    feed = build_ctrader_research_feed(policy, symbols)
    store = SupabaseOperationalStore.from_env(
        execution_ready_score_floor=demo_execution_min,
    )
    store.ensure_reference_symbols(cfg.pairs)
    print(f"CTRADER_SYMBOL_REFERENCE_OK count={len(cfg.pairs)}")

    transport_cfg = cfg.providers["transport"]
    calendar_cfg = cfg.providers["calendar"]["FOREX_FACTORY_WEEKLY"]
    calendar_transport = UrllibHttpTransport(
        timeout_seconds=float(transport_cfg["timeout_seconds"]),
        max_response_bytes=int(transport_cfg["max_response_bytes"]),
        user_agent=str(transport_cfg["user_agent"]),
    )
    calendar_provider = None
    if not technical_only:
        calendar_provider = ForexFactoryCalendarProvider(
            calendar_transport,
            url=str(calendar_cfg["base_url"]),
            allowed_host=str(calendar_cfg["allowed_host"]),
        )
    spread_overrides = _demo_spread_limit_overrides(cfg) if technical_only else {}
    if spread_overrides:
        print(
            "CTRADER_DEMO_SPREAD_LIMITS "
            f"default={float(policy.reconciliation['max_execution_spread_pips']):g} "
            + " ".join(
                f"{symbol}={limit:g}"
                for symbol, limit in sorted(spread_overrides.items())
            )
        )
    guard_resolver = ProductionGuardResolver(
        cfg,
        feed,
        calendar_provider=calendar_provider,
        max_quote_age_seconds=float(policy.ctrader["max_quote_age_seconds"]),
        max_spread_pips=float(policy.reconciliation["max_execution_spread_pips"]),
        demo_max_risk_pct=float(policy.demo_safety["max_risk_pct"]),
        max_spread_pips_by_symbol=spread_overrides,
        quote_wait_timeout_seconds=float(policy.ctrader["quote_wait_timeout_seconds"]),
        quote_poll_seconds=float(policy.ctrader["quote_poll_seconds"]),
        clock=lambda: datetime.now(tz=UTC),
        disabled_guards=("NEWS_BLOCK",) if technical_only else (),
    )
    producer = CTraderSignalProducer(
        cfg,
        feed,
        store,
        code_version=os.getenv("GITHUB_SHA", "LOCAL"),
        signal_ttl_seconds=min(
            300.0,
            float(policy.order.get("max_signal_age_seconds", 300)),
        ),
        max_quote_age_seconds=float(policy.ctrader["max_quote_age_seconds"]),
        quote_wait_timeout_seconds=float(policy.ctrader["quote_wait_timeout_seconds"]),
        quote_poll_seconds=float(policy.ctrader["quote_poll_seconds"]),
        guard_resolver=guard_resolver,
        technical_only_scalping=technical_only,
    )
    try:
        report = producer.run_once()
        persisted = store.list_signals_for_run(report.run_id)
        state_counts: dict[str, int] = {}
        for row in persisted:
            state = str(row.get("state", "UNKNOWN")).upper()
            state_counts[state] = state_counts.get(state, 0) + 1
        states = ",".join(
            f"{name}:{state_counts[name]}" for name in sorted(state_counts)
        ) or "NONE"
        missing_macro = ",".join(report.missing_macro) or "NONE"
        guard_missing_count = sum(
            len(names) for names in report.guard_missing.values()
        )
        print(
            "CTRADER_SIGNAL_PRODUCER_OK "
            f"run_id={report.run_id} market={report.market_symbols}/{len(cfg.pairs)} "
            f"macro={'DISABLED' if technical_only else str(report.macro_currencies) + '/8'} "
            f"ranked={report.ranked_pairs} "
            f"deep={report.deep_candidates} analyses={report.analyses} "
            f"signals={report.signals_written} execution_ready={report.execution_ready} "
            f"skipped={len(report.skipped)} missing_macro={missing_macro} "
            f"guard_missing={guard_missing_count}"
        )
        print(f"CTRADER_SIGNAL_STATES {states}")
        for row in sorted(persisted, key=lambda item: str(item.get("symbol", ""))):
            score = row.get("final_score")
            score_text = "NONE" if score is None else f"{float(score):.2f}"
            rr2 = row.get("rr2")
            rr2_text = "NONE" if rr2 is None else f"{float(rr2):.2f}"
            guards = "+".join(str(x) for x in (row.get("active_guards") or [])) or "NONE"
            print(
                "CTRADER_SIGNAL_DETAIL "
                f"symbol={row.get('symbol')} state={str(row.get('state', 'UNKNOWN')).upper()} "
                f"score={score_text} setup={row.get('setup_type', 'NONE')} "
                f"rr2={rr2_text} guards={guards}"
            )
        if report.skipped:
            reason_counts: dict[str, int] = {}
            safe_skips: list[str] = []
            for symbol, reason in sorted(report.skipped.items()):
                code = str(reason).split(":", 1)[0] or "UNKNOWN"
                reason_counts[code] = reason_counts.get(code, 0) + 1
                safe_skips.append(f"{symbol}:{code}")
            reason_summary = ",".join(
                f"{name}:{reason_counts[name]}" for name in sorted(reason_counts)
            )
            print(f"CTRADER_SIGNAL_SKIP_REASONS {reason_summary}")
            print("CTRADER_SIGNAL_SKIPS " + ",".join(safe_skips))
        if report.guard_missing:
            missing_items = [
                f"{symbol}:{'+'.join(names)}"
                for symbol, names in sorted(report.guard_missing.items())
                if names
            ]
            if missing_items:
                print("CTRADER_SIGNAL_GUARD_MISSING " + ",".join(missing_items))
        if report.calendar_error:
            print(f"CTRADER_SIGNAL_CALENDAR_UNAVAILABLE {report.calendar_error}")
        if report.execution_ready:
            ready_rows = [
                row for row in persisted
                if str(row.get("state", "")).upper() == "EXECUTION_READY"
            ]
            if len(ready_rows) != report.execution_ready:
                raise SystemExit("CTRADER_SIGNAL_PERSISTENCE_MISMATCH")
            if any(row.get("active_guards") not in ([], ()) for row in ready_rows):
                raise SystemExit("CTRADER_SIGNAL_READY_HAS_GUARDS")
        return 0
    finally:
        feed.close()


def _require_demo_autotrade_opt_in(policy) -> None:
    safety = policy.demo_safety
    name = str(safety.get("enable_env", ""))
    value = str(safety.get("enable_value", ""))
    if not name or os.getenv(name, "") != value:
        raise SystemExit("CTRADER_DEMO_AUTOTRADE_OPT_IN_REQUIRED")


def cmd_ctrader_demo_preflight(args: argparse.Namespace) -> int:
    cfg = load_project_config(args.root)
    policy = load_execution_policy(args.root)
    symbols = [pair.symbol for pair in cfg.pairs]
    gateway, session = build_broker_gateway(policy, symbols, backend="CTRADER")
    try:
        account = gateway.account_snapshot()
        positions = gateway.position_count()
        print(
            "CTRADER_DEMO_PREFLIGHT_OK "
            f"account_bound={bool(account.account_id)} trade_allowed={account.trade_allowed} "
            f"positions={positions} symbols={len(symbols)}"
        )
        return 0 if account.trade_allowed else 2
    finally:
        session.close()


def cmd_ctrader_demo_control(args: argparse.Namespace) -> int:
    policy = load_execution_policy(args.root)
    store = SupabaseOperationalStore.from_env()
    if args.enable:
        _require_demo_autotrade_opt_in(policy)
        snapshot = store.set_execution_control(
            execution_mode="AUTO",
            new_orders_enabled=True,
            emergency_stop=False,
            close_all_requested=False,
            source="github_phone_demo_enable",
        )
    else:
        snapshot = store.set_execution_control(
            execution_mode="DISABLED",
            new_orders_enabled=False,
            emergency_stop=True,
            close_all_requested=False,
            source="github_phone_demo_disable",
        )
    print(
        "CTRADER_DEMO_CONTROL_OK "
        f"mode={snapshot.execution_mode} new_orders={snapshot.new_orders_enabled} "
        f"emergency_stop={snapshot.emergency_stop} version={snapshot.version}"
    )
    return 0


def cmd_ctrader_demo_autotrade(args: argparse.Namespace) -> int:
    cfg = load_project_config(args.root)
    base_policy = load_execution_policy(args.root)
    _require_demo_autotrade_opt_in(base_policy)
    cfg, _production_execution_min = _apply_demo_execution_threshold(cfg)
    if _demo_technical_only_enabled():
        cfg = _apply_demo_technical_only_profile(cfg)
    demo_execution_min = float(cfg.scoring["states"]["execution_candidate_min"])
    policy = replace(base_policy, mode=ExecutionMode.AUTO)
    symbols = [pair.symbol for pair in cfg.pairs]
    gateway, session = build_broker_gateway(policy, symbols, backend="CTRADER")
    store = SupabaseOperationalStore.from_env(
        execution_ready_score_floor=demo_execution_min,
    )
    gate = ControlPlaneGate(
        max_age_seconds=float(policy.live_safety.get("control_state_max_age_seconds", 5))
    )
    router = ExecutionRouter(
        policy,
        gateway=gateway,
        session=session,
        control_gate=gate,
        audit_sink=SupabaseOrderAuditSink(store),
    )
    executor = CTraderDemoAutoExecutor(
        cfg=cfg,
        policy=policy,
        gateway=gateway,
        router=router,
        store=store,
    )
    interval = float(policy.demo_safety.get("poll_seconds", 1.0))
    control_worker = ControlPlaneRefreshWorker(
        store,
        gate,
        interval_seconds=min(
            1.0,
            max(0.25, float(policy.live_safety.get("control_state_max_age_seconds", 5)) / 3.0),
        ),
    )
    control_worker.refresh_once()
    control_worker.start()

    def run_once():
        report = executor.poll_once(limit=int(args.limit))
        store.write_heartbeat(
            "ctrader_demo_autotrade",
            healthy=True,
            lag_seconds=0.0,
            details={
                "mode": "AUTO",
                "environment": "DEMO",
                "scanned": report.scanned,
                "eligible": report.eligible,
                "claimed": report.claimed,
                "executed": report.executed,
                "skipped": list(report.skipped[:20]),
            },
        )
        print(
            "CTRADER_DEMO_AUTOTRADE_OK "
            f"scanned={report.scanned} eligible={report.eligible} "
            f"claimed={report.claimed} executed={report.executed} "
            f"skipped={len(report.skipped)}"
        )
        return report

    try:
        if args.once:
            run_once()
            return 0
        while True:
            try:
                run_once()
            except Exception as exc:
                try:
                    store.write_heartbeat(
                        "ctrader_demo_autotrade",
                        healthy=False,
                        details={"error": f"{type(exc).__name__}: {exc}"},
                    )
                except Exception:
                    pass
                print(f"CTRADER_DEMO_AUTOTRADE_ERROR {type(exc).__name__}: {exc}")
            sleep(interval)
    except KeyboardInterrupt:
        print("CTRADER_DEMO_AUTOTRADE_STOPPED")
        return 0
    finally:
        control_worker.stop()
        session.close()


def _build_ctrader_demo_smoke_intent(cfg, gateway, *, symbol: str = "EURUSD") -> OrderIntent:
    symbol = str(symbol).upper()
    pair = cfg.pair_map.get(symbol)
    if pair is None:
        raise SystemExit(f"unknown configured pair: {symbol}")
    quote = gateway.market_quote(symbol)
    entry = float(quote.ask)
    stop_loss = entry - 20.0 * float(pair.pip_size)
    take_profit = entry + 40.0 * float(pair.pip_size)
    return OrderIntent(
        signal_id=f"DEMO-SMOKE-{uuid4().hex[:24]}",
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        created_at=datetime.now(tz=UTC),
        volume=0.01,
        entry_price=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_pct=0.25,
        comment="CONTROLLED_DEMO_ORDER_SMOKE",
    )


def cmd_ctrader_demo_order_smoke(args: argparse.Namespace) -> int:
    if not bool(args.confirmed):
        raise SystemExit("CONTROLLED_DEMO_ORDER_CONFIRMATION_REQUIRED")
    cfg = load_project_config(args.root)
    base_policy = load_execution_policy(args.root)
    _require_demo_autotrade_opt_in(base_policy)
    policy = replace(base_policy, mode=ExecutionMode.AUTO)
    symbols = [pair.symbol for pair in cfg.pairs]
    gateway, session = build_broker_gateway(policy, symbols, backend="CTRADER")
    store = SupabaseOperationalStore.from_env()
    gate = ControlPlaneGate(
        max_age_seconds=float(policy.live_safety.get("control_state_max_age_seconds", 5))
    )
    router = ExecutionRouter(
        policy,
        gateway=gateway,
        session=session,
        control_gate=gate,
        audit_sink=SupabaseOrderAuditSink(store),
    )
    control_worker = ControlPlaneRefreshWorker(
        store,
        gate,
        interval_seconds=min(
            1.0,
            max(0.25, float(policy.live_safety.get("control_state_max_age_seconds", 5)) / 3.0),
        ),
    )
    control_worker.refresh_once()
    control_worker.start()
    try:
        intent = _build_ctrader_demo_smoke_intent(cfg, gateway, symbol=args.symbol)
        receipt = router.execute(intent)
        if not receipt.accepted:
            raise SystemExit("CTRADER_DEMO_ORDER_SMOKE_NOT_ACCEPTED")
        print(
            "CTRADER_DEMO_ORDER_SMOKE_OK "
            f"symbol={intent.symbol} side={intent.side.value} volume={intent.volume:.2f} "
            f"broker_order_id={receipt.broker_order_id or 'UNKNOWN'} "
            f"executed_price={receipt.executed_price or 0.0}"
        )
        return 0
    finally:
        control_worker.stop()
        session.close()


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

    p = sub.add_parser("research-cloud")
    p.add_argument("--once", action="store_true")
    p.add_argument("--spot-only", action="store_true")
    p.add_argument("--heartbeat", type=float, default=8.0)
    p.add_argument("--mtf-refresh", type=float, default=900.0)
    p.set_defaults(func=cmd_research_cloud)

    p = sub.add_parser("mt5-monitor")
    p.add_argument("--terminal-path", default=None)
    p.add_argument("--interval", type=float, default=15.0)
    p.add_argument("--environment", choices=["DEMO", "LIVE"], default="DEMO")
    p.add_argument("--once", action="store_true")
    p.set_defaults(func=cmd_mt5_monitor)

    p = sub.add_parser("macro-source-smoke")
    p.set_defaults(func=cmd_macro_source_smoke)

    p = sub.add_parser("macro-refresh")
    p.set_defaults(func=cmd_macro_refresh)

    p = sub.add_parser("ctrader-signal-producer")
    p.set_defaults(func=cmd_ctrader_signal_producer)

    p = sub.add_parser("ctrader-demo-preflight")
    p.set_defaults(func=cmd_ctrader_demo_preflight)

    p = sub.add_parser("ctrader-demo-control")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--enable", action="store_true")
    group.add_argument("--disable", action="store_true")
    p.set_defaults(func=cmd_ctrader_demo_control)

    p = sub.add_parser("ctrader-demo-autotrade")
    p.add_argument("--once", action="store_true")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_ctrader_demo_autotrade)

    p = sub.add_parser("ctrader-demo-order-smoke")
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--confirmed", action="store_true")
    p.set_defaults(func=cmd_ctrader_demo_order_smoke)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
