from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from .cli import _apply_demo_technical_only_profile, _demo_spread_limit_overrides
from .config import ProjectConfig, load_project_config
from .demo_calibration import apply_demo_calibration_risk, apply_demo_calibration_threshold, build_demo_calibration_store
from .demo_correlation_evidence import EvidenceProductionGuardResolver
from .demo_market_schedule import apply_demo_market_schedule
from .demo_technical_producer import _persist_geometry_events
from .demo_xau_expansion_v42 import (
    FORWARD_DEMO_SCORE,
    STRATEGY_ID,
    build_xau_expansion_v42_analysis,
    evaluate_xau_d1_expansion_v42,
    forward_rank,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import ensure_utc
from .signal_producer import CTraderSignalProducer, SignalProducerReport
from .strategy import DeepScanReport, UniverseSelection

UTC = timezone.utc
SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_expansion_v42_candidate_producer"
MARKER_EVENT = "DEMO_XAU_EXPANSION_V42_SIGNAL_EMITTED"
HISTORY_WINDOW_CALENDAR_FACTOR = 1.65


def _subset_cfg(cfg: ProjectConfig) -> ProjectConfig:
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_EXPANSION_V42_CONFIG_MISSING")
    return replace(cfg, pairs=(cfg.pair_map[SYMBOL],))


def _with_history_requirements(cfg: ProjectConfig) -> ProjectConfig:
    strategy = dict(cfg.strategy)
    mtf = dict(strategy["mtf"])
    minimum_bars = dict(mtf["minimum_bars"])
    minimum_bars["D1"] = max(220, int(minimum_bars.get("D1", 0)))
    mtf["minimum_bars"] = minimum_bars
    strategy["mtf"] = mtf
    return replace(cfg, strategy=strategy)


def _already_emitted(store, *, signal_bar_at: datetime | None) -> bool:
    if signal_bar_at is None:
        return False
    try:
        response = (
            store.client.table("broker_order_events")
            .select("payload,code,event_type")
            .eq("event_type", MARKER_EVENT)
            .eq("code", STRATEGY_ID)
            .order("observed_at", desc=True)
            .limit(20)
            .execute()
        )
    except Exception:
        return True
    target = ensure_utc(signal_bar_at).isoformat()
    return any(str(dict(row.get("payload") or {}).get("signal_bar_at") or "") == target for row in response.data or [])


def _record_marker(store, *, signal_id: str, signal) -> None:
    account_id = os.getenv("CTRADER_ACCOUNT_ID", "").strip() or os.getenv("CTRADER_TRADER_LOGIN", "").strip()
    if not account_id:
        raise SystemExit("CTRADER_ACCOUNT_ID_REQUIRED_FOR_XAU_EXPANSION_V42_MARKER")
    store.record_order_event(
        backend="CTRADER",
        account_id=account_id,
        signal_key=str(signal_id),
        broker_order_id=f"XAU_V42:{signal_id}",
        event_type=MARKER_EVENT,
        accepted=True,
        code=STRATEGY_ID,
        message="user-authorized XAU Expansion V4.2 DEMO candidate emitted",
        payload={
            "symbol": SYMBOL,
            "direction": signal.direction,
            "strategy_id": STRATEGY_ID,
            "signal_bar_at": None if signal.signal_bar_at is None else ensure_utc(signal.signal_bar_at).isoformat(),
            "next_entry_at": None if signal.next_entry_at is None else ensure_utc(signal.next_entry_at).isoformat(),
            "execution_influence": True,
            "environment": "DEMO",
            "live_execution_enabled": False,
        },
    )


class XauExpansionV42Producer(CTraderSignalProducer):
    last_signal = None
    last_deep_report: DeepScanReport | None = None
    last_market_failures: dict[str, str] = {}

    def _bar_window(self, timeframe: str, count: int, now: datetime) -> tuple[datetime, datetime]:
        seconds = int(self.cfg.timeframes[timeframe])
        factor = HISTORY_WINDOW_CALENDAR_FACTOR if timeframe in {"D1", "H4"} else 1.0
        return now - timedelta(seconds=seconds * (int(count) + 12) * factor), now

    def run_once(self) -> SignalProducerReport:
        snapshot_at = ensure_utc(self.clock())
        run_id = self.store.start_scanner_run(
            mode="DEMO_ONLY",
            code_version=self.code_version,
            data_contract_version="XAU_EXPANSION_S2R2T2H0_V42_DEMO_V1",
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
            xau_bars = bars_by_symbol.get(SYMBOL, {})
            signal = evaluate_xau_d1_expansion_v42(tuple(xau_bars.get("D1", ())), as_of=decision_at)
            self.last_signal = signal

            analyses = []
            selected = ()
            if signal.active and signal.execution_eligible and not _already_emitted(self.store, signal_bar_at=signal.signal_bar_at):
                rank = forward_rank(signal)
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
                    build_xau_expansion_v42_analysis(
                        signal=signal,
                        bars_by_timeframe=xau_bars,
                        cfg=self.cfg,
                        as_of=decision_at,
                        external_guard_flags=guard_inputs.get(SYMBOL, {}),
                    )
                )
            elif signal.active:
                failures[SYMBOL] = "DUPLICATE_D1_SIGNAL_BAR_BLOCKED"
            elif SYMBOL not in market_failures:
                failures[SYMBOL] = signal.reason

            selection = UniverseSelection(tuple(selected), tuple(selected))
            deep = DeepScanReport(selection, tuple(analyses), dict(sorted(failures.items())))
            self.last_deep_report = deep
            signals_written, ready = self._persist_signals(run_id, as_of=decision_at, report=deep)
            self.store.finish_scanner_run(run_id, status="COMPLETED", finished_at=self.clock())
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
                self.store.finish_scanner_run(run_id, status="FAILED", finished_at=self.clock())
            except Exception:
                pass
            raise


def run() -> int:
    cfg = load_project_config(None)
    cfg, market_schedule_mode = apply_demo_market_schedule(cfg)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO" or not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_EXPANSION_V42_DEMO_ONLY")

    cfg, production_execution_min = apply_demo_calibration_threshold(cfg)
    cfg = _apply_demo_technical_only_profile(cfg)
    cfg, demo_risk_pct = apply_demo_calibration_risk(cfg, max_risk_pct=float(policy.demo_safety["max_risk_pct"]))
    cfg = _with_history_requirements(_subset_cfg(cfg))
    demo_execution_min = float(cfg.scoring["states"]["execution_candidate_min"])
    store = build_demo_calibration_store(execution_ready_score_floor=demo_execution_min)
    store.ensure_reference_symbols(cfg.pairs)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    spread_overrides = {k: v for k, v in _demo_spread_limit_overrides(cfg).items() if k == SYMBOL}
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
    producer = XauExpansionV42Producer(
        cfg,
        feed,
        store,
        code_version=os.getenv("GITHUB_SHA", "LOCAL"),
        historical_request_delay_seconds=float(os.getenv("CTRADER_DEMO_HISTORICAL_REQUEST_DELAY_SECONDS", "0.20")),
        signal_ttl_seconds=min(300.0, float(policy.order.get("max_signal_age_seconds", 300))),
        max_quote_age_seconds=float(policy.ctrader["max_quote_age_seconds"]),
        quote_wait_timeout_seconds=float(policy.ctrader["quote_wait_timeout_seconds"]),
        quote_poll_seconds=float(policy.ctrader["quote_poll_seconds"]),
        guard_resolver=guard_resolver,
        technical_only_scalping=True,
    )
    try:
        report = producer.run_once()
        persisted = store.list_signals_for_run(report.run_id)
        analyses = {item.symbol: item for item in (producer.last_deep_report.analyses if producer.last_deep_report else ())}
        geometry_written, geometry_missing = _persist_geometry_events(
            store=store, policy=policy, persisted=persisted, analyses=analyses
        )
        if report.execution_ready:
            ready = [row for row in persisted if str(row.get("state", "")).upper() == "EXECUTION_READY" and str(row.get("symbol", "")).upper() == SYMBOL]
            if len(ready) != 1 or producer.last_signal is None:
                raise SystemExit("XAU_EXPANSION_V42_READY_CARDINALITY_INVALID")
            _record_marker(store, signal_id=str(ready[0]["id"]), signal=producer.last_signal)
        reason = report.skipped.get(SYMBOL, None if producer.last_signal is None else producer.last_signal.reason)
        store.write_heartbeat(
            WORKER_NAME,
            healthy=True,
            lag_seconds=0.0,
            details={
                "strategy_id": STRATEGY_ID,
                "environment": "DEMO",
                "execution_influence": True,
                "live_execution_enabled": False,
                "market_schedule_mode": market_schedule_mode,
                "signal_reason": reason,
                "signals_written": report.signals_written,
                "execution_ready": report.execution_ready,
                "geometry_written": geometry_written,
                "geometry_missing_nonready": geometry_missing,
                "forward_demo_score": FORWARD_DEMO_SCORE,
                "production_execution_min": production_execution_min,
                "demo_execution_min": demo_execution_min,
                "risk_per_trade_pct": demo_risk_pct,
            },
        )
        print(
            "CTRADER_DEMO_XAU_EXPANSION_V42_OK "
            f"signals={report.signals_written} ready={report.execution_ready} geometry={geometry_written} reason={reason or 'NONE'}"
        )
        return 0
    finally:
        close = getattr(feed, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    raise SystemExit(run())
