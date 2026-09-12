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
    build_xau_execution_analysis,
    evaluate_usdjpy_h4_compression_breakout,
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


def _already_emitted(store, *, signal_bar_at: datetime | None) -> bool:
    if signal_bar_at is None:
        return False
    try:
        response = (
            store.client.table("broker_order_events")
            .select("payload,code,event_type")
            .eq("event_type", MARKER_EVENT)
            .eq("code", PAIR_STRATEGY_IDS["XAUUSD"])
            .order("observed_at", desc=True)
            .limit(20)
            .execute()
        )
    except Exception:
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
        message="five-core strategy execution candidate emitted",
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
    last_xau_signal = None
    last_usdjpy_shadow = None
    last_market_failures: dict[str, str] = {}

    def _bar_window(self, timeframe: str, count: int, now: datetime) -> tuple[datetime, datetime]:
        """Pad slow-timeframe calendar windows for 24/5 weekend gaps.

        The base producer assumes count * timeframe_seconds spans count bars. That
        is valid for continuous markets but under-fetches FX/metals D1/H4 history
        because Saturday/Sunday contain no bars. The feed still receives the same
        bounded count; only the calendar lookback is widened.
        """
        seconds = int(self.cfg.timeframes[timeframe])
        lookback_seconds = _history_window_seconds(timeframe, count, seconds)
        return now - timedelta(seconds=lookback_seconds), now

    def run_once(self) -> SignalProducerReport:
        snapshot_at = ensure_utc(self.clock())
        run_id = self.store.start_scanner_run(
            mode="DEMO_ONLY",
            code_version=self.code_version,
            data_contract_version="FIVE_CORE_ROUTER_V1",
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
            xau_signal = evaluate_xau_d1_tsmom_60_200(
                tuple(xau_bars.get("D1", ())),
                as_of=decision_at,
            )
            self.last_xau_signal = xau_signal

            usdjpy_bars = bars_by_symbol.get("USDJPY", {})
            usdjpy_shadow = evaluate_usdjpy_h4_compression_breakout(
                tuple(usdjpy_bars.get("H4", ())),
                as_of=decision_at,
            )
            self.last_usdjpy_shadow = usdjpy_shadow

            analyses = []
            selected = ()
            xau_execution_authorized = (
                xau_signal.execution_eligible and execution_authorized("XAUUSD")
            )
            if (
                xau_signal.active
                and xau_execution_authorized
                and not _already_emitted(
                    self.store, signal_bar_at=xau_signal.signal_bar_at
                )
            ):
                rank = forward_rank(xau_signal)
                selected = (rank,)
                guard_inputs = {}
                if self.guard_resolver is not None:
                    resolution = self.guard_resolver.resolve(
                        candidates=selected,
                        bars_by_symbol=bars_by_symbol,
                        as_of=decision_at,
                    )
                    guard_inputs = resolution.flags_by_symbol
                    guard_missing = resolution.missing_by_symbol
                    calendar_error = resolution.calendar_error
                analyses.append(
                    build_xau_execution_analysis(
                        signal=xau_signal,
                        bars_by_timeframe=xau_bars,
                        cfg=self.cfg,
                        as_of=decision_at,
                        external_guard_flags=guard_inputs.get("XAUUSD", {}),
                    )
                )
            elif xau_signal.active and xau_execution_authorized:
                failures["XAUUSD"] = "DUPLICATE_D1_SIGNAL_BAR_BLOCKED"
            elif xau_signal.active:
                failures["XAUUSD"] = "SHADOW_SIGNAL_NO_EXECUTION_AUTHORITY"
            elif "XAUUSD" not in market_failures:
                failures["XAUUSD"] = xau_signal.reason

            if usdjpy_shadow.active:
                failures["USDJPY"] = "SHADOW_SIGNAL_NO_EXECUTION_AUTHORITY"
            elif "USDJPY" not in market_failures:
                failures["USDJPY"] = usdjpy_shadow.reason
            for symbol in sorted(NO_TRADE_SYMBOLS):
                failures[symbol] = "NO_TRADE_UNTIL_VALIDATED"

            selection = UniverseSelection(tuple(selected), tuple(selected))
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
                ranked_pairs=len(selected),
                deep_candidates=len(selected),
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

    if producer.last_xau_signal is not None and report.execution_ready:
        ready_rows = [
            row for row in persisted
            if str(row.get("state", "")).upper() == "EXECUTION_READY"
            and str(row.get("symbol", "")).upper() == "XAUUSD"
        ]
        if len(ready_rows) != 1:
            raise SystemExit("FIVE_CORE_READY_SIGNAL_CARDINALITY_INVALID")
        _record_emitted_marker(
            store,
            signal_id=str(ready_rows[0]["id"]),
            signal=producer.last_xau_signal,
        )

    shadow = producer.last_usdjpy_shadow
    xau_runtime_reason = report.skipped.get(
        "XAUUSD",
        producer.last_market_failures.get(
            "XAUUSD",
            None if producer.last_xau_signal is None else producer.last_xau_signal.reason,
        ),
    )
    usdjpy_runtime_reason = report.skipped.get(
        "USDJPY",
        producer.last_market_failures.get(
            "USDJPY",
            None if shadow is None else shadow.reason,
        ),
    )
    store.write_heartbeat(
        WORKER_NAME,
        healthy=True,
        lag_seconds=0.0,
        details={
            "mode": "FIVE_CORE_STRATEGY_ROUTER_V1",
            "authority_contract": AUTHORITY_CONTRACT,
            "universe": list(FIVE_CORE_SYMBOLS),
            "execution_symbols": sorted(EXECUTION_SYMBOLS),
            "shadow_symbols": sorted(SHADOW_SYMBOLS),
            "no_trade_symbols": sorted(NO_TRADE_SYMBOLS),
            "pair_strategy_ids": five_core_policy_snapshot(),
            "market_symbols": report.market_symbols,
            "market_failures": dict(sorted(producer.last_market_failures.items())),
            "xau_execution_authorized": execution_authorized("XAUUSD"),
            "xau_signal_reason": xau_runtime_reason,
            "usdjpy_shadow_active": bool(shadow and shadow.active),
            "usdjpy_shadow_direction": None if shadow is None else shadow.direction,
            "usdjpy_shadow_reason": usdjpy_runtime_reason,
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
        f"geometry={geometry_written} xau={xau_runtime_reason or 'NONE'} "
        f"xau_authorized={execution_authorized('XAUUSD')} "
        f"usdjpy_shadow={'ACTIVE' if shadow and shadow.active else 'INACTIVE'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
