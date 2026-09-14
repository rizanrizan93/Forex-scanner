from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from .cli import _apply_demo_technical_only_profile, _demo_spread_limit_overrides
from .config import load_project_config
from .demo_calibration import (
    apply_demo_calibration_risk,
    apply_demo_calibration_threshold,
    build_demo_calibration_store,
)
from .demo_correlation_evidence import EvidenceProductionGuardResolver
from .demo_euraud_gbpaud_execution import (
    DEMO_EXECUTION_CONTRACT,
    EXECUTION_SYMBOLS,
    FETCH_SYMBOLS,
    build_euraud_execution_analysis,
    build_gbpaud_execution_analysis,
    evaluate_euraud_demo_signal,
    evaluate_gbpaud_demo_signal,
)
from .demo_five_core_authority import execution_authorized
from .demo_five_core_candidate_producer import (
    _history_window_seconds,
    _subset_cfg,
    _with_history_requirements,
)
from .demo_five_core_router import FORWARD_DEMO_SCORE, forward_rank
from .demo_market_schedule import apply_demo_market_schedule
from .demo_technical_producer import _persist_geometry_events
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import ensure_utc
from .signal_producer import CTraderSignalProducer, SignalProducerReport
from .strategy import DeepScanReport, UniverseSelection

UTC = timezone.utc
WORKER_NAME = "ctrader_demo_euraud_gbpaud_candidate_producer"
MARKER_EVENT = "DEMO_EURAUD_GBPAUD_SIGNAL_EMITTED"


def _already_emitted(store, *, signal_bar_at: datetime | None, strategy_id: str) -> bool:
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
        return True
    target = ensure_utc(signal_bar_at).isoformat()
    return any(
        str(dict(row.get("payload") or {}).get("signal_bar_at") or "") == target
        for row in response.data or []
    )


def _record_marker(store, *, signal_id: str, signal) -> None:
    account_id = (
        os.getenv("CTRADER_ACCOUNT_ID", "").strip()
        or os.getenv("CTRADER_TRADER_LOGIN", "").strip()
    )
    if not account_id:
        raise SystemExit("CTRADER_ACCOUNT_ID_REQUIRED_FOR_EURAUD_GBPAUD_MARKER")
    store.record_order_event(
        backend="CTRADER",
        account_id=account_id,
        signal_key=str(signal_id),
        broker_order_id=f"EURAUD_GBPAUD:{signal_id}",
        event_type=MARKER_EVENT,
        accepted=True,
        code=signal.strategy_id,
        message="user-authorized frozen EURAUD/GBPAUD DEMO candidate emitted",
        payload={
            "symbol": signal.symbol,
            "direction": signal.direction,
            "strategy_id": signal.strategy_id,
            "signal_bar_at": None
            if signal.signal_bar_at is None
            else ensure_utc(signal.signal_bar_at).isoformat(),
            "next_entry_at": None
            if signal.next_entry_at is None
            else ensure_utc(signal.next_entry_at).isoformat(),
            "execution_influence": True,
            "environment": "DEMO",
            "live_execution_enabled": False,
        },
    )


class EuraudGbpaudSignalProducer(CTraderSignalProducer):
    last_deep_report: DeepScanReport | None = None
    last_signals: dict[str, Any] = {}
    last_market_failures: dict[str, str] = {}

    def _bar_window(self, timeframe: str, count: int, now: datetime):
        seconds = int(self.cfg.timeframes[timeframe])
        return now - __import__("datetime").timedelta(
            seconds=_history_window_seconds(timeframe, count, seconds)
        ), now

    def run_once(self) -> SignalProducerReport:
        snapshot_at = ensure_utc(self.clock())
        run_id = self.store.start_scanner_run(
            mode="DEMO_ONLY",
            code_version=self.code_version,
            data_contract_version=DEMO_EXECUTION_CONTRACT,
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

            euraud_bars = bars_by_symbol.get("EURAUD", {})
            gbpaud_bars = bars_by_symbol.get("GBPAUD", {})
            gbpusd_bars = bars_by_symbol.get("GBPUSD", {})
            audusd_bars = bars_by_symbol.get("AUDUSD", {})
            signals = {
                "EURAUD": evaluate_euraud_demo_signal(
                    tuple(euraud_bars.get("D1", ())), as_of=decision_at
                ),
                "GBPAUD": evaluate_gbpaud_demo_signal(
                    {
                        "GBPAUD": tuple(gbpaud_bars.get("D1", ())),
                        "GBPUSD": tuple(gbpusd_bars.get("D1", ())),
                        "AUDUSD": tuple(audusd_bars.get("D1", ())),
                    },
                    as_of=decision_at,
                ),
            }
            self.last_signals = signals

            selected_ranks = []
            active_symbols = []
            for symbol, signal in signals.items():
                if symbol in market_failures:
                    continue
                if not signal.active:
                    failures[symbol] = signal.reason
                    continue
                if not signal.execution_eligible or not execution_authorized(symbol):
                    failures[symbol] = "SIGNAL_NO_DEMO_EXECUTION_AUTHORITY"
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
                "EURAUD": build_euraud_execution_analysis,
                "GBPAUD": build_gbpaud_execution_analysis,
            }
            analyses = []
            for symbol in active_symbols:
                try:
                    analyses.append(
                        builders[symbol](
                            signal=signals[symbol],
                            bars_by_timeframe=bars_by_symbol[symbol],
                            cfg=self.cfg,
                            as_of=decision_at,
                            external_guard_flags=guard_inputs.get(symbol, {}),
                        )
                    )
                except ValueError as exc:
                    failures[symbol] = f"PAIR_PLAN_INVALID:{exc}"

            analysis_symbols = {item.symbol for item in analyses}
            persisted_ranks = tuple(
                rank for rank in selected if rank.symbol in analysis_symbols
            )
            selection = UniverseSelection(persisted_ranks, persisted_ranks)
            deep = DeepScanReport(
                selection, tuple(analyses), dict(sorted(failures.items()))
            )
            self.last_deep_report = deep
            signals_written, ready = self._persist_signals(
                run_id, as_of=decision_at, report=deep
            )
            self.store.finish_scanner_run(
                run_id, status="COMPLETED", finished_at=self.clock()
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
                    run_id, status="FAILED", finished_at=self.clock()
                )
            except Exception:
                pass
            raise


def run() -> int:
    cfg = load_project_config(None)
    cfg, market_schedule_mode = apply_demo_market_schedule(cfg)
    policy = load_execution_policy(None)
    if (
        str(policy.ctrader.get("environment", "")).upper() != "DEMO"
        or not bool(policy.ctrader.get("require_demo", False))
    ):
        raise SystemExit("EURAUD_GBPAUD_DEMO_ONLY")

    cfg, production_execution_min = apply_demo_calibration_threshold(cfg)
    cfg = _apply_demo_technical_only_profile(cfg)
    cfg, demo_risk_pct = apply_demo_calibration_risk(
        cfg, max_risk_pct=float(policy.demo_safety["max_risk_pct"])
    )
    # Validate every configured DEMO spread override against the full project
    # universe before narrowing this worker to its support symbols. This keeps
    # the global fail-closed contract while preventing unrelated valid overrides
    # (for example XAUUSD) from failing a subset-only producer.
    all_demo_spread_overrides = _demo_spread_limit_overrides(cfg)
    cfg = _with_history_requirements(_subset_cfg(cfg, FETCH_SYMBOLS))
    demo_execution_min = float(cfg.scoring["states"]["execution_candidate_min"])
    store = build_demo_calibration_store(
        execution_ready_score_floor=demo_execution_min
    )
    store.ensure_reference_symbols(cfg.pairs)
    feed = build_ctrader_research_feed(policy, FETCH_SYMBOLS)
    spread_overrides = {
        symbol: limit
        for symbol, limit in all_demo_spread_overrides.items()
        if symbol in FETCH_SYMBOLS
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
    producer = EuraudGbpaudSignalProducer(
        cfg,
        feed,
        store,
        code_version=os.getenv("GITHUB_SHA", "LOCAL"),
        historical_request_delay_seconds=float(
            os.getenv("CTRADER_DEMO_HISTORICAL_REQUEST_DELAY_SECONDS", "0.20")
        ),
        signal_ttl_seconds=min(
            300.0, float(policy.order.get("max_signal_age_seconds", 300))
        ),
        max_quote_age_seconds=float(policy.ctrader["max_quote_age_seconds"]),
        quote_wait_timeout_seconds=float(policy.ctrader["quote_wait_timeout_seconds"]),
        quote_poll_seconds=float(policy.ctrader["quote_poll_seconds"]),
        guard_resolver=guard_resolver,
        technical_only_scalping=True,
    )

    try:
        report = producer.run_once()
        persisted = store.list_signals_for_run(report.run_id)
        analyses = {
            item.symbol: item
            for item in (
                producer.last_deep_report.analyses
                if producer.last_deep_report
                else ()
            )
        }
        geometry_written, geometry_missing = _persist_geometry_events(
            store=store,
            policy=policy,
            persisted=persisted,
            analyses=analyses,
        )
        ready_rows = [
            row
            for row in persisted
            if str(row.get("state", "")).upper() == "EXECUTION_READY"
        ]
        for row in ready_rows:
            symbol = str(row.get("symbol") or "").upper().strip()
            signal = producer.last_signals.get(symbol)
            if signal is None or symbol not in EXECUTION_SYMBOLS:
                raise SystemExit("EURAUD_GBPAUD_READY_SIGNAL_AUTHORITY_INVALID")
            _record_marker(store, signal_id=str(row["id"]), signal=signal)

        strategy_reasons = {
            symbol: report.skipped.get(
                symbol,
                None
                if producer.last_signals.get(symbol) is None
                else producer.last_signals[symbol].reason,
            )
            for symbol in EXECUTION_SYMBOLS
        }
        store.write_heartbeat(
            WORKER_NAME,
            healthy=True,
            lag_seconds=0.0,
            details={
                "contract": DEMO_EXECUTION_CONTRACT,
                "environment": "DEMO",
                "execution_influence": True,
                "live_execution_enabled": False,
                "execution_symbols": list(EXECUTION_SYMBOLS),
                "fetch_symbols": list(FETCH_SYMBOLS),
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
            "CTRADER_DEMO_EURAUD_GBPAUD_ROUTER_OK "
            f"market={report.market_symbols}/{len(FETCH_SYMBOLS)} "
            f"signals={report.signals_written} ready={report.execution_ready} "
            f"geometry={geometry_written}"
        )
        return 0
    finally:
        close = getattr(feed, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    raise SystemExit(run())
