from __future__ import annotations

import os
from datetime import datetime, timezone

from .cli import (
    _apply_demo_technical_only_profile,
    _demo_spread_limit_overrides,
)
from .config import load_project_config
from .demo_calibration import (
    apply_demo_calibration_risk,
    apply_demo_calibration_threshold,
    apply_demo_deep_analysis_top,
    build_demo_calibration_store,
)
from .demo_correlation_evidence import EvidenceProductionGuardResolver
from .demo_signal_producer import ExplicitDemoTechnicalSignalProducer
from .demo_technical_strategy import (
    _demo_directional_structure_score,
    _demo_structure_conflict,
    _early_structure_valid,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy

UTC = timezone.utc


def _safe_structure_value(value) -> str:
    return "NONE" if value is None else str(value)


def _displacement_text(snapshot) -> tuple[str, int]:
    displacement = getattr(snapshot, "displacement", None)
    if displacement is None:
        return "NONE", 0
    return (
        _safe_structure_value(getattr(displacement, "direction", None)),
        int(bool(getattr(displacement, "valid", False))),
    )


def run() -> int:
    """Run the explicit DEMO-only technical signal-production path.

    No strategy module function is replaced at runtime. The producer binds the
    DEMO technical scan and trade-plan geometry explicitly through
    ExplicitDemoTechnicalSignalProducer.
    """
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("CTRADER_SIGNAL_PRODUCER_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_SIGNAL_PRODUCER_REQUIRE_DEMO")

    cfg, production_execution_min = apply_demo_calibration_threshold(cfg)
    cfg = _apply_demo_technical_only_profile(cfg)
    cfg = apply_demo_deep_analysis_top(cfg)
    cfg, demo_risk_pct = apply_demo_calibration_risk(
        cfg,
        max_risk_pct=float(policy.demo_safety["max_risk_pct"]),
    )
    demo_execution_min = float(cfg.scoring["states"]["execution_candidate_min"])
    demo_deep_top = int(cfg.strategy["selection"]["deep_analysis_top"])
    effective_risk_ceiling = float(cfg.risk["max_risk_per_trade_pct"])
    fvg_max_age = float(os.getenv("CTRADER_DEMO_FVG_MAX_AGE_MINUTES", "90"))
    print(
        "CTRADER_DEMO_EXECUTION_THRESHOLD "
        f"active={demo_execution_min:g} production_default={production_execution_min:g}"
    )
    print("CTRADER_DEMO_PROFILE mode=TECHNICAL_SCALPING macro=DISABLED")
    print("CTRADER_DEMO_CALIBRATION floor=60 hard_guards=ENFORCED")
    print("CTRADER_DEMO_BINDING mode=EXPLICIT trade_plan=DEMO_GEOMETRY monkeypatch=DISABLED")
    print(
        "CTRADER_DEMO_EARLY_ENTRY "
        f"h1_m15=PREARM fresh_fvg_minutes={fvg_max_age:g} "
        "execution_score=60 chase_block_atr=0.50"
    )
    print(
        "CTRADER_DEMO_FAST_PASS universe_tfs=H1,M15,M5 "
        f"slow_hydration_top={max(demo_deep_top, int(cfg.strategy['selection']['macro_compatible_top']))} "
        f"deep_analysis_top={demo_deep_top} slow_tfs=D1,H4 request_pacing=UNCHANGED"
    )
    print(
        "CTRADER_DEMO_RISK "
        f"risk_per_trade_pct={demo_risk_pct:g} "
        f"max_risk_pct={effective_risk_ceiling:g} "
        f"max_lots={float(policy.demo_safety['max_order_lots']):g} "
        f"max_positions={int(policy.demo_safety['max_concurrent_positions'])}"
    )

    symbols = [pair.symbol for pair in cfg.pairs]
    feed = build_ctrader_research_feed(policy, symbols)
    store = build_demo_calibration_store(
        execution_ready_score_floor=demo_execution_min,
    )
    store.ensure_reference_symbols(cfg.pairs)
    print(f"CTRADER_SYMBOL_REFERENCE_OK count={len(cfg.pairs)}")

    spread_overrides = _demo_spread_limit_overrides(cfg)
    if spread_overrides:
        print(
            "CTRADER_DEMO_SPREAD_LIMITS "
            f"default={float(policy.reconciliation['max_execution_spread_pips']):g} "
            + " ".join(
                f"{symbol}={limit:g}"
                for symbol, limit in sorted(spread_overrides.items())
            )
        )

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
    producer = ExplicitDemoTechnicalSignalProducer(
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
        technical_only_scalping=True,
    )

    try:
        report = producer.run_once()
        persisted = store.list_signals_for_run(report.run_id)
        analyses = {
            item.symbol: item
            for item in ((producer.last_deep_report.analyses if producer.last_deep_report else ()))
        }
        state_counts: dict[str, int] = {}
        for row in persisted:
            state = str(row.get("state", "UNKNOWN")).upper()
            state_counts[state] = state_counts.get(state, 0) + 1
        states = ",".join(
            f"{name}:{state_counts[name]}" for name in sorted(state_counts)
        ) or "NONE"
        guard_missing_count = sum(len(names) for names in report.guard_missing.values())
        print(
            "CTRADER_SIGNAL_PRODUCER_OK "
            f"run_id={report.run_id} market={report.market_symbols}/{len(cfg.pairs)} "
            "macro=DISABLED "
            f"ranked={report.ranked_pairs} deep={report.deep_candidates} "
            f"analyses={report.analyses} signals={report.signals_written} "
            f"execution_ready={report.execution_ready} skipped={len(report.skipped)} "
            f"missing_macro=NONE guard_missing={guard_missing_count}"
        )
        print(f"CTRADER_SIGNAL_STATES {states}")

        for row in sorted(persisted, key=lambda item: str(item.get("symbol", ""))):
            symbol = str(row.get("symbol", ""))
            score = row.get("final_score")
            score_text = "NONE" if score is None else f"{float(score):.2f}"
            rr2 = row.get("rr2")
            rr2_text = "NONE" if rr2 is None else f"{float(rr2):.2f}"
            guards = "+".join(str(x) for x in (row.get("active_guards") or [])) or "NONE"
            print(
                "CTRADER_SIGNAL_DETAIL "
                f"symbol={symbol} state={str(row.get('state', 'UNKNOWN')).upper()} "
                f"score={score_text} setup={row.get('setup_type', 'NONE')} "
                f"rr2={rr2_text} guards={guards}"
            )
            for evidence in guard_resolver.last_correlation_evidence.get(symbol, ()):
                print(
                    "CTRADER_CORRELATION_EVIDENCE "
                    f"symbol={symbol} peer={evidence.peer_symbol} "
                    f"corr={evidence.correlation:.4f} threshold={evidence.threshold:.4f} "
                    f"lookback_h1={evidence.lookback_bars} blocked={int(evidence.blocked)}"
                )
            analysis = analyses.get(symbol)
            if analysis is not None:
                h1_score = _demo_directional_structure_score(analysis.h1, analysis.direction)
                m15_score = _demo_directional_structure_score(analysis.m15, analysis.direction)
                h1_disp_dir, h1_disp_valid = _displacement_text(analysis.h1)
                m15_disp_dir, m15_disp_valid = _displacement_text(analysis.m15)
                print(
                    "CTRADER_STRUCTURE_EVIDENCE "
                    f"symbol={symbol} direction={analysis.direction} "
                    f"h1_trend={analysis.h1.trend} "
                    f"h1_score={'NONE' if h1_score is None else f'{h1_score:.1f}'} "
                    f"h1_bos={_safe_structure_value(analysis.h1.bos)} "
                    f"h1_mss={_safe_structure_value(analysis.h1.mss)} "
                    f"h1_disp={h1_disp_dir} h1_disp_valid={h1_disp_valid} "
                    f"m15_trend={analysis.m15.trend} "
                    f"m15_score={'NONE' if m15_score is None else f'{m15_score:.1f}'} "
                    f"m15_bos={_safe_structure_value(analysis.m15.bos)} "
                    f"m15_mss={_safe_structure_value(analysis.m15.mss)} "
                    f"m15_disp={m15_disp_dir} m15_disp_valid={m15_disp_valid} "
                    f"conflict={int(_demo_structure_conflict(analysis))} "
                    f"execution_structure={int(_early_structure_valid(analysis))}"
                )
                plan = analysis.trade_plan
                if plan is None:
                    print(f"CTRADER_SIGNAL_GEOMETRY symbol={symbol} plan=NONE")
                else:
                    print(
                        "CTRADER_SIGNAL_GEOMETRY "
                        f"symbol={symbol} entry_low={plan.entry_low:.8g} "
                        f"entry_high={plan.entry_high:.8g} sl={plan.stop_loss:.8g} "
                        f"tp1={plan.tp1 if plan.tp1 is not None else 'NONE'} "
                        f"tp2={plan.tp2 if plan.tp2 is not None else 'NONE'} "
                        f"rr1={plan.rr1 if plan.rr1 is not None else 'NONE'} "
                        f"rr2={plan.rr2 if plan.rr2 is not None else 'NONE'} "
                        f"chase_atr={plan.chase_distance_atr:.4f}"
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


if __name__ == "__main__":
    raise SystemExit(run())
