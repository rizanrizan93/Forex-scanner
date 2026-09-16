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
from .demo_market_schedule import apply_demo_market_schedule
from .demo_technical_producer import _persist_geometry_events
from .demo_xau_m15_ema_reversal_recovery import (
    EXTENDED_RESEARCH_TARGET_R,
    FORWARD_DEMO_SCORE,
    STRATEGY_CONTRACT,
    STRATEGY_ID,
    SYMBOL,
    TP1_R,
    TP2_R,
    build_xau_m15_ema_reversal_analysis,
    evaluate_xau_m15_ema_reversal_recovery,
    forward_rank,
)
from .demo_xau_m15_evidence_authority import (
    EvidenceAuthorityDecision,
    resolve_xau_m15_evidence_authority,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import ensure_utc
from .signal_producer import CTraderSignalProducer, SignalProducerReport
from .strategy import DeepScanReport, UniverseSelection

UTC = timezone.utc
WORKER_NAME = "ctrader_demo_xau_m15_ema_reversal_candidate_producer"
MARKER_EVENT = "DEMO_XAU_M15_EMA_REVERSAL_SIGNAL_EMITTED"


def _subset_cfg(cfg: ProjectConfig) -> ProjectConfig:
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_M15_EMA_REVERSAL_CONFIG_MISSING")
    return replace(cfg, pairs=(cfg.pair_map[SYMBOL],))


def _with_history_requirements(cfg: ProjectConfig) -> ProjectConfig:
    strategy = dict(cfg.strategy)
    mtf = dict(strategy["mtf"])
    minimum_bars = dict(mtf["minimum_bars"])
    minimum_bars["M15"] = max(240, int(minimum_bars.get("M15", 0)))
    minimum_bars["M5"] = max(60, int(minimum_bars.get("M5", 0)))
    mtf["minimum_bars"] = minimum_bars
    strategy["mtf"] = mtf
    return replace(cfg, strategy=strategy)


def _already_emitted(store, *, signal_bar_at: datetime | None, direction: str | None) -> bool:
    if signal_bar_at is None or direction not in {"LONG", "SHORT"}:
        return False
    try:
        response = (
            store.client.table("broker_order_events")
            .select("payload,code,event_type")
            .eq("event_type", MARKER_EVENT)
            .eq("code", STRATEGY_ID)
            .order("observed_at", desc=True)
            .limit(30)
            .execute()
        )
    except Exception:
        return True
    target = ensure_utc(signal_bar_at).isoformat()
    return any(
        str(dict(row.get("payload") or {}).get("signal_bar_at") or "") == target
        and str(dict(row.get("payload") or {}).get("direction") or "").upper() == direction
        for row in response.data or []
    )


def _record_marker(store, *, signal_id: str, signal, analysis) -> None:
    account_id = os.getenv("CTRADER_ACCOUNT_ID", "").strip() or os.getenv(
        "CTRADER_TRADER_LOGIN", ""
    ).strip()
    if not account_id:
        raise SystemExit("CTRADER_ACCOUNT_ID_REQUIRED_FOR_XAU_M15_REVERSAL_MARKER")
    if signal.direction not in {"LONG", "SHORT"}:
        raise SystemExit("XAU_M15_REVERSAL_MARKER_DIRECTION_INVALID")
    plan = analysis.trade_plan
    point_y_role = (
        "BULLISH_RECOVERY_CONFIRMATION_NOT_SEPARATE_ORDER_TARGET"
        if signal.direction == "LONG"
        else "BEARISH_REJECTION_CONFIRMATION_NOT_SEPARATE_ORDER_TARGET"
    )
    payload = {
        **signal.evidence(),
        "symbol": SYMBOL,
        "direction": signal.direction,
        "strategy_id": STRATEGY_ID,
        "strategy_contract": STRATEGY_CONTRACT,
        "execution_influence": True,
        "environment": "DEMO",
        "live_execution_enabled": False,
        "evidence_authority_required": True,
        "forward_demo_score": FORWARD_DEMO_SCORE,
        "tp1_alias": "AMERICANO_V1",
        "tp1_r": TP1_R,
        "tp1": None if plan is None else plan.tp1,
        "tp2_alias": "KOPI_SUSU_V1",
        "tp2_r": TP2_R,
        "tp2": None if plan is None else plan.tp2,
        "extended_alias": "KOPI_BUTTERSCOTCH_RESEARCH_ONLY_V1",
        "extended_target_r": EXTENDED_RESEARCH_TARGET_R,
        "point_y_role": point_y_role,
    }
    store.record_order_event(
        backend="CTRADER",
        account_id=account_id,
        signal_key=str(signal_id),
        broker_order_id=f"XAU_M15_REV:{signal_id}",
        event_type=MARKER_EVENT,
        accepted=True,
        code=STRATEGY_ID,
        message="evidence-authorized XAU M15 EMA reversal/recovery DEMO candidate emitted",
        payload=payload,
    )


class XauM15EmaReversalProducer(CTraderSignalProducer):
    last_signal = None
    last_deep_report: DeepScanReport | None = None
    last_market_failures: dict[str, str] = {}
    evidence_authority: EvidenceAuthorityDecision | None = None

    def _bar_window(self, timeframe: str, count: int, now: datetime) -> tuple[datetime, datetime]:
        seconds = int(self.cfg.timeframes[timeframe])
        factor = 1.65 if timeframe in {"D1", "H4"} else 1.20
        return now - timedelta(seconds=seconds * (int(count) + 12) * factor), now

    def run_once(self) -> SignalProducerReport:
        snapshot_at = ensure_utc(self.clock())
        run_id = self.store.start_scanner_run(
            mode="DEMO_ONLY",
            code_version=self.code_version,
            data_contract_version="XAU_M15_EMA_REVERSAL_RECOVERY_V2_EVIDENCE_GATED",
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
            signal = evaluate_xau_m15_ema_reversal_recovery(
                tuple(xau_bars.get("M15", ())), as_of=decision_at
            )
            self.last_signal = signal

            analyses = []
            selected = ()
            duplicate = False
            authority = self.evidence_authority
            authority_allowed = bool(authority and authority.execution_authorized)
            authority_blocked = bool(
                signal.active and signal.execution_eligible and not authority_allowed
            )
            if signal.active and signal.execution_eligible and authority_allowed:
                duplicate = _already_emitted(
                    self.store,
                    signal_bar_at=signal.signal_bar_at,
                    direction=signal.direction,
                )
                if not duplicate:
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
                        build_xau_m15_ema_reversal_analysis(
                            signal=signal,
                            bars_by_timeframe=xau_bars,
                            cfg=self.cfg,
                            as_of=decision_at,
                            external_guard_flags=guard_inputs.get(SYMBOL, {}),
                        )
                    )
            if authority_blocked:
                reason = "UNRESOLVED" if authority is None else authority.reason
                failures[SYMBOL] = f"EVIDENCE_AUTHORITY_BLOCKED:{reason}"
            elif duplicate:
                failures[SYMBOL] = "DUPLICATE_M15_SIGNAL_BAR_DIRECTION_BLOCKED"
            elif not signal.active and SYMBOL not in market_failures:
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
    if (
        str(policy.ctrader.get("environment", "")).upper() != "DEMO"
        or not bool(policy.ctrader.get("require_demo", False))
    ):
        raise SystemExit("XAU_M15_EMA_REVERSAL_DEMO_ONLY")

    cfg, production_execution_min = apply_demo_calibration_threshold(cfg)
    cfg = _apply_demo_technical_only_profile(cfg)
    cfg, demo_risk_pct = apply_demo_calibration_risk(
        cfg, max_risk_pct=float(policy.demo_safety["max_risk_pct"])
    )
    cfg = _with_history_requirements(_subset_cfg(cfg))
    demo_execution_min = float(cfg.scoring["states"]["execution_candidate_min"])
    store = build_demo_calibration_store(execution_ready_score_floor=demo_execution_min)
    store.ensure_reference_symbols(cfg.pairs)
    authority = resolve_xau_m15_evidence_authority(store, STRATEGY_ID)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    spread_overrides = {
        key: value for key, value in _demo_spread_limit_overrides(cfg).items() if key == SYMBOL
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
    producer = XauM15EmaReversalProducer(
        cfg,
        feed,
        store,
        code_version=os.getenv("GITHUB_SHA", "LOCAL"),
        historical_request_delay_seconds=float(
            os.getenv("CTRADER_DEMO_HISTORICAL_REQUEST_DELAY_SECONDS", "0.20")
        ),
        signal_ttl_seconds=min(300.0, float(policy.order.get("max_signal_age_seconds", 300))),
        max_quote_age_seconds=float(policy.ctrader["max_quote_age_seconds"]),
        quote_wait_timeout_seconds=float(policy.ctrader["quote_wait_timeout_seconds"]),
        quote_poll_seconds=float(policy.ctrader["quote_poll_seconds"]),
        guard_resolver=guard_resolver,
        technical_only_scalping=True,
    )
    producer.evidence_authority = authority
    try:
        report = producer.run_once()
        persisted = store.list_signals_for_run(report.run_id)
        analyses = {
            item.symbol: item
            for item in (producer.last_deep_report.analyses if producer.last_deep_report else ())
        }
        geometry_written, geometry_missing = _persist_geometry_events(
            store=store,
            policy=policy,
            persisted=persisted,
            analyses=analyses,
        )
        if report.execution_ready:
            ready = [
                row
                for row in persisted
                if str(row.get("state", "")).upper() == "EXECUTION_READY"
                and str(row.get("symbol", "")).upper() == SYMBOL
            ]
            if (
                not authority.execution_authorized
                or len(ready) != 1
                or producer.last_signal is None
                or not analyses.get(SYMBOL)
            ):
                raise SystemExit("XAU_M15_EMA_REVERSAL_READY_AUTHORITY_INVALID")
            _record_marker(
                store,
                signal_id=str(ready[0]["id"]),
                signal=producer.last_signal,
                analysis=analyses[SYMBOL],
            )

        reason = report.skipped.get(
            SYMBOL, None if producer.last_signal is None else producer.last_signal.reason
        )
        direction = None if producer.last_signal is None else producer.last_signal.direction
        store.write_heartbeat(
            WORKER_NAME,
            healthy=True,
            lag_seconds=0.0,
            details={
                "strategy_id": STRATEGY_ID,
                "strategy_contract": STRATEGY_CONTRACT,
                "environment": "DEMO",
                "execution_influence": authority.execution_authorized,
                "live_execution_enabled": False,
                "paper_forward_observation": True,
                "evidence_authority": authority.payload(),
                "supported_directions": ["LONG", "SHORT"],
                "market_schedule_mode": market_schedule_mode,
                "signal_direction": direction,
                "signal_reason": reason,
                "signals_written": report.signals_written,
                "execution_ready": report.execution_ready,
                "geometry_written": geometry_written,
                "geometry_missing_nonready": geometry_missing,
                "forward_demo_score": FORWARD_DEMO_SCORE,
                "expected_conviction_tier": "B",
                "expected_base_lot": 0.01,
                "expected_risk_budget_pct": 1.0,
                "production_execution_min": production_execution_min,
                "demo_execution_min": demo_execution_min,
                "global_demo_risk_ceiling_pct": demo_risk_pct,
                "tp1_alias": "AMERICANO_V1",
                "tp1_r": TP1_R,
                "tp2_alias": "KOPI_SUSU_V1",
                "tp2_r": TP2_R,
                "extended_alias": "KOPI_BUTTERSCOTCH_RESEARCH_ONLY_V1",
                "extended_target_r": EXTENDED_RESEARCH_TARGET_R,
            },
        )
        print(
            "CTRADER_DEMO_XAU_M15_EMA_REVERSAL_OK "
            f"direction={direction or 'NONE'} signals={report.signals_written} "
            f"ready={report.execution_ready} geometry={geometry_written} "
            f"reason={reason or 'NONE'} authority={int(authority.execution_authorized)} "
            f"lifecycle={authority.lifecycle_stage} score=70 expected_lot=0.01 "
            "expected_risk_pct=1.0 bidirectional=1"
        )
        return 0
    finally:
        close = getattr(feed, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    raise SystemExit(run())
