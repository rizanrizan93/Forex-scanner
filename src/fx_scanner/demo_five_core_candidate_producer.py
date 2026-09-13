from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from .cli import _apply_demo_technical_only_profile, _demo_spread_limit_overrides
from .config import ProjectConfig, load_project_config
from .demo_calibration import (
    apply_demo_calibration_risk,
    apply_demo_calibration_threshold,
    build_demo_calibration_store,
)
from .demo_correlation_evidence import EvidenceProductionGuardResolver
from .demo_five_core_authority import (
    AUTHORITY_CONTRACT,
    EXECUTION_SYMBOLS,
    SHADOW_SYMBOLS,
    execution_authorized,
)
from .demo_five_core_router import (
    FIVE_CORE_SYMBOLS,
    FORWARD_DEMO_SCORE,
    NO_TRADE_SYMBOLS,
    PAIR_STRATEGY_IDS,
    build_gbpusd_execution_analysis,
    build_usdjpy_execution_analysis,
    build_xau_execution_analysis,
    evaluate_gbpusd_h4_mean_revert_z2_to_sma20,
    evaluate_usdjpy_d1_donchian55_200,
    evaluate_xau_d1_tsmom_60_200,
    five_core_policy_snapshot,
    forward_rank,
)
from .demo_market_schedule import apply_demo_market_schedule
from .demo_technical_producer import _persist_geometry_events
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import ensure_utc
from .signal_producer import CTraderSignalProducer, SignalProducerReport
from .strategy import DeepScanReport, UniverseSelection

UTC = timezone.utc
MARKER_EVENT = "DEMO_FIVE_CORE_SIGNAL_EMITTED"
WORKER_NAME = "ctrader_demo_five_core_candidate_producer"
HISTORY_WINDOW_CALENDAR_FACTOR = {
    "D1": 1.65,
    "H4": 1.65,
}


def _subset_cfg(cfg: ProjectConfig, symbols: tuple[str, ...]) -> ProjectConfig:
    selected = tuple(cfg.pair_map[symbol] for symbol in symbols if symbol in cfg.pair_map)
    if len(selected) != len(symbols):
        missing = sorted(set(symbols) - set(cfg.pair_map))
        raise SystemExit(f"FIVE_CORE_CONFIG_MISSING:{','.join(missing)}")
    return replace(cfg, pairs=selected)


def _with_history_requirements(cfg: ProjectConfig) -> ProjectConfig:
    strategy = dict(cfg.strategy)
    mtf = dict(strategy["mtf"])
    minimum_bars = dict(mtf["minimum_bars"])
    minimum_bars["D1"] = max(220, int(minimum_bars.get("D1", 0)))
    minimum_bars["H4"] = max(220, int(minimum_bars.get("H4", 0)))
    mtf["minimum_bars"] = minimum_bars
    strategy["mtf"] = mtf
    return replace(cfg, strategy=strategy)


def _history_window_seconds(timeframe: str, count: int, timeframe_seconds: int) -> float:
    base_periods = int(count) + 12
    factor = float(HISTORY_WINDOW_CALENDAR_FACTOR.get(str(timeframe).upper(), 1.0))
    return float(timeframe_seconds) * float(base_periods) * factor


def _already_emitted(
    store,
    *,
    signal_bar_at: datetime | None,
    strategy_id: str,
) -> bool:
    if signal_bar_at is None:
        return False
    try:
        response = (
            store.client.table("broker_order_events")
            .select("payload,code,event_type")
            .eq("event_type", MARKER_EVENT)
            .eq("code", strategy_id)
            .order("observed_at", desc=True)
            .limit(20)
            .execute()
        )
    except Exception:
        # Fail closed when duplicate evidence cannot be read.
        return True
    target = ensure_utc(signal_bar_at).isoformat()
    for raw in response.data or []:
        payload = dict(raw.get("payload") or {})
        if str(payload.get("signal_bar_at") or "") == target:
            return True
    return False


def _record_emitted_marker(store, *, signal_id: str, signal) -> None:
    account_id = (
        os.getenv("CTRADER_ACCOUNT_ID", "").strip()
        or os.getenv("CTRADER_TRADER_LOGIN", "").strip()
    )
    if not account_id:
        raise SystemExit("CTRADER_ACCOUNT_ID_REQUIRED_FOR_FIVE_CORE_MARKER")
    store.record_order_event(
        backend="CTRADER",
        account_id=account_id,
        signal_key=str(signal_id),
        broker_order_id=f"FIVE_CORE:{signal_id}",
        event_type=MARKER_EVENT,
        accepted=True,
        code=signal.strategy_id,
        message="five-core pair-specific strategy execution candidate emitted",
        payload={
            "symbol": signal.symbol,
            "direction": signal.direction,
            "strategy_id": signal.strategy_id,
            "signal_bar_at": None if signal.signal_bar_at is None else ensure_utc(signal.signal_bar_at).isoformat(),
            "next_entry_at": None if signal.next_entry_at is None else ensure_utc(signal.next_entry_at).isoformat(),
            "execution_influence": True,
            "environment": "DEMO",
        },
    )


class FiveCoreSignalProducer(CTraderSignalProducer):
    last_deep_report: DeepScanReport | None = None
    last_signals: dict[str, Any] = {}
    # Backward-compatible observability attributes.
    last_xau_signal = None
    last_usdjpy_shadow = None
    last_market_failures: dict[str, str] = {}

    def _bar_window(self, timeframe: str, count: int, now: datetime) -> tuple[datetime, datetime]:
        seconds = int(self.cfg.timeframes[timeframe])
        lookback_seconds = _history_window_seconds(timeframe, count, seconds)
        return now - timedelta(seconds=lookback_seconds), now

    def run_once(self) -> SignalProducerReport:
        snapshot_at = ensure_utc(self.clock())
        run_id = self.store.start_scanner_run(
            mode="DEMO_ONLY",
            code_version=self.code_version,
            data_contract_version="FIVE_CORE_PAIR_SPECIFIC_ROUTER_V2",
            started_at=snapshot_at,
        )
        failures: dict[str, str] = {}
        guard_missing: dict[str, Any] = {}
        calendar_error = None
        try:
            self.feed.ensure_connected()
            bars_by_symbol, market_failures = self._fetch_market(as_of=snapshot_at)
            self.last_market_failures = dict(market_failures)
            failures.update(market_failures)
            decision_at = ensure_utc(self.clock())

            xau_bars = bars_by_symbol.get("XAUUSD", {})
            usdjpy_bars = bars_by_symbol.get("USDJPY", {})
            gbpusd_bars = bars_by_symbol.get("GBPUSD", {})

            signals = {
                "XAUUSD": evaluate_xau_d1_tsmom_60_200(
                    tuple(xau_bars.get("D1", ())), as_of=decision_at
                ),
                "USDJPY": evaluate_usdjpy_d1_donchian55_200(
                    tuple(usdjpy_bars.get("D1", ())), as_of=decision_at
                ),
                "GBPUSD": evaluate_gbpusd_h4_mean_revert_z2_to_sma20(
                    tuple(gbpusd_bars.get("H4", ())), as_of=decision_at
                ),
            }
            self.last_signals = signals
            self.last_xau_signal = signals["XAUUSD"]
            self.last_usdjpy_shadow = signals["USDJPY"]

            selected_ranks = []
            active_symbols = []
            for symbol, signal in signals.items():
                if symbol in market_failures:
                    continue
                if not signal.active:
                    failures[symbol] = signal.reason
                    continue
                if not signal.execution_eligible or not execution_authorized(symbol):
                    failures[symbol] = "SIGNAL_NO_EXECUTION_AUTHORITY"
                    continue
                if _already_emitted(
                    self.store,
                    signal_bar_at=signal.signal_bar_at,
                    strategy_id=signal.strategy_id,
                ):
                    failures[symbol] = "DUPLICATE_SIGNAL_BAR_BLOCKED"
                    continue
                selected_ranks.append(forward_rank(signal))
                active_symbols.append(symbol)

            selected = tuple(selected_ranks)
            guard_inputs: dict[str, dict[str, bool]] = {}
            if selected and self.guard_resolver is not None:
                resolution = self.guard_resolver.resolve(
                    candidates=selected,
                    bars_by_symbol=bars_by_symbol,
                    as_of=decision_at,
                )
                guard_inputs = resolution.flags_by_symbol
                guard_missing = resolution.missing_by_symbol
                calendar_error = resolution.calendar_error

            builders = {
                "XAUUSD": build_xau_execution_analysis,
                "USDJPY": build_usdjpy_execution_analysis,
                "GBPUSD": build_gbpusd_execution_analysis,
            }
            analyses = []
            for symbol in active_symbols:
                signal = signals[symbol]
                try:
                    analyses.append(
                        builders[symbol](
                            signal=signal,
                            bars_by_timeframe=bars_by_symbol[symbol],
                            cfg=self.cfg,
                            as_of=decision_at,
                            external_guard_flags=guard_inputs.get(symbol, {}),
                        )
                    )
                except ValueError as exc:
                    failures[symbol] = f"PAIR_PLAN_INVALID:{exc}"

            for symbol in sorted(NO_TRADE_SYMBOLS):
                failures[symbol] = "NO_TRADE_UNTIL_VALIDATED"

            # Persist only ranks whose analyses survived plan construction.
            analysis_symbols = {item.symbol for item in analyses}
            persisted_ranks = tuple(rank for rank in selected if rank.symbol in analysis_symbols)
            selection = UniverseSelection(persisted_ranks, persisted_ranks)
            deep = DeepScanReport(selection, tuple(analyses), dict(sorted(failures.items())))
            self.last_deep_report = deep
            signals_written, ready = self._persist_signals(
                run_id,
                as_of=decision_at,
                report=deep,
            )
            self.store.finish_scanner_run(
                run_id,
                status="COMPLETED",
                finished_at=self.clock(),
            )
            return SignalProducerReport(
                run_id=run_id,
                observed_at=decision_at,
                market_symbols=len(bars_by_symbol),
                macro_currencies=0,
                ranked_pairs=len(persisted_ranks),
                deep_candidates=len(persisted_ranks),
                analyses=len(analyses),
                signals_written=signals_written,
                execution_ready=ready,
                skipped=dict(sorted(failures.items())),
                missing_macro=(),
                guard_missing=guard_missing,
                calendar_error=calendar_error,
            )
        except Exception:
            try:
                self.store.finish_scanner_run(
                    run_id,
                    status="FAILED",
                    finished_at=self.clock(),
                )
            except Exception:
                pass
            raise


def run() -> int:
    cfg = load_project_config(None)
    cfg, market_schedule_mode = apply_demo_market_schedule(cfg)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("FIVE_CORE_ROUTER_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("FIVE_CORE_ROUTER_REQUIRE_DEMO")

    cfg, production_execution_min = apply_demo_calibration_threshold(cfg)
    cfg = _apply_demo_technical_only_profile(cfg)
    cfg, demo_risk_pct = apply_demo_calibration_risk(
        cfg,
        max_risk_pct=float(policy.demo_safety["max_risk_pct"]),
    )
    cfg = _subset_cfg(cfg, FIVE_CORE_SYMBOLS)
    cfg = _with_history_requirements(cfg)

    demo_execution_min = float(cfg.scoring["states"]["execution_candidate_min"])
    store = build_demo_calibration_store(execution_ready_score_floor=demo_execution_min)
    store.ensure_reference_symbols(cfg.pairs)
    feed = build_ctrader_research_feed(policy, FIVE_CORE_SYMBOLS)

    spread_overrides = {
        symbol: limit
        for symbol, limit in _demo_spread_limit_overrides(cfg).items()
        if symbol in FIVE_CORE_SYMBOLS
    }
    guard_resolver = EvidenceProductionGuardResolver(
        cfg,
        feed,
        calendar_provider=None,
        max_quote_age_seconds=float(policy.ctrader["max_quote_age_seconds"]),
        max_spread_pips=float(policy.reconciliation["max_execution_spread_pips"]),
        demo_max_risk_pct=float(policy.demo_safety["max_risk_pct"]),
        max_spread_pips_by_symbol=spread_overrides,
        quote_wait_timeout_seconds=float(policy.ctrader["quote_wait_timeout_seconds"]),
        quote_poll_seconds=float(policy.ctrader["quote_poll_seconds"]),
        clock=lambda: datetime.now(tz=UTC),
        disabled_guards=("NEWS_BLOCK",),
    )

    request_delay = float(os.getenv("CTRADER_DEMO_HISTORICAL_REQUEST_DELAY_SECONDS", "0.20"))
    producer = FiveCoreSignalProducer(
        cfg,
        feed,
        store,
        code_version=os.getenv("GITHUB_SHA", "LOCAL"),
        historical_request_delay_seconds=request_delay,
        signal_ttl_seconds=min(300.0, float(policy.order.get("max_signal_age_seconds", 300))),
        max_quote_age_seconds=float(policy.ctrader["max_quote_age_seconds"]),
        quote_wait_timeout_seconds=float(policy.ctrader["quote_wait_timeout_seconds"]),
        quote_poll_seconds=float(policy.ctrader["quote_poll_seconds"]),
        guard_resolver=guard_resolver,
        technical_only_scalping=True,
    )

    report = producer.run_once()
    persisted = store.list_signals_for_run(report.run_id)
    analyses = {
        item.symbol: item
        for item in (
            producer.last_deep_report.analyses if producer.last_deep_report else ()
        )
    }
    geometry_written, geometry_missing = _persist_geometry_events(
        store=store,
        policy=policy,
        persisted=persisted,
        analyses=analyses,
    )

    ready_rows = [
        row for row in persisted
        if str(row.get("state", "")).upper() == "EXECUTION_READY"
    ]
    for row in ready_rows:
        symbol = str(row.get("symbol") or "").upper().strip()
        signal = producer.last_signals.get(symbol)
        if signal is None or not execution_authorized(symbol):
            raise SystemExit("FIVE_CORE_READY_SIGNAL_AUTHORITY_INVALID")
        _record_emitted_marker(store, signal_id=str(row["id"]), signal=signal)

    strategy_reasons = {
        symbol: report.skipped.get(
            symbol,
            producer.last_market_failures.get(
                symbol,
                None if producer.last_signals.get(symbol) is None else producer.last_signals[symbol].reason,
            ),
        )
        for symbol in ("XAUUSD", "USDJPY", "GBPUSD")
    }
    store.write_heartbeat(
        WORKER_NAME,
        healthy=True,
        lag_seconds=0.0,
        details={
            "mode": "FIVE_CORE_PAIR_SPECIFIC_ROUTER_V2",
            "authority_contract": AUTHORITY_CONTRACT,
            "universe": list(FIVE_CORE_SYMBOLS),
            "execution_symbols": sorted(EXECUTION_SYMBOLS),
            "shadow_symbols": sorted(SHADOW_SYMBOLS),
            "no_trade_symbols": sorted(NO_TRADE_SYMBOLS),
            "pair_strategy_ids": five_core_policy_snapshot(),
            "market_symbols": report.market_symbols,
            "market_failures": dict(sorted(producer.last_market_failures.items())),
            "strategy_reasons": strategy_reasons,
            "signals_written": report.signals_written,
            "execution_ready": report.execution_ready,
            "geometry_written": geometry_written,
            "geometry_missing_nonready": geometry_missing,
            "market_schedule_mode": market_schedule_mode,
            "production_execution_min": production_execution_min,
            "demo_execution_min": demo_execution_min,
            "forward_demo_score": FORWARD_DEMO_SCORE,
            "risk_per_trade_pct": demo_risk_pct,
        },
    )
    print(
        "CTRADER_DEMO_FIVE_CORE_ROUTER_OK "
        f"market={report.market_symbols}/{len(FIVE_CORE_SYMBOLS)} "
        f"signals={report.signals_written} ready={report.execution_ready} "
        f"geometry={geometry_written} authorized={','.join(sorted(EXECUTION_SYMBOLS))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
