from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_causal_m15_regime_v132 import _scenario
from .research_xau_v134_h3_robustness_v135 import START, RECENT, frozen_h3
from .research_xau_v136_structural_regime_forensic_v137 import annotate_structural
from .research_xau_v137_cftc_positioning_forensic_v138 import annotate_cot, build_cot_rows
from .research_xau_v138_driver_interaction_forensic_v139 import annotate_drivers

RESEARCH_VERSION = "XAU_V139_ADAPTIVE_CAUSAL_ROUTER_V140"
ARTIFACT_CONTRACT = "XAU_V139_ADAPTIVE_CAUSAL_ROUTER_V140_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False

WARMUP_COMPLETED_CANDIDATES = 40
SHRINKAGE_ALPHA = 20.0
DECISION_THRESHOLD_R = 0.0

ERA_WINDOWS = (
    ("2012_2018", datetime(2012, 1, 1, tzinfo=timezone.utc), datetime(2019, 1, 1, tzinfo=timezone.utc)),
    ("2019_2024", datetime(2019, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
    ("2025_2026YTD", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2026, 9, 20, tzinfo=timezone.utc)),
)
START_SLICES = (
    ("2012", datetime(2012, 1, 1, tzinfo=timezone.utc)),
    ("2016", datetime(2016, 1, 1, tzinfo=timezone.utc)),
    ("2019", datetime(2019, 1, 1, tzinfo=timezone.utc)),
    ("2022", datetime(2022, 1, 1, tzinfo=timezone.utc)),
    ("2025", datetime(2025, 1, 1, tzinfo=timezone.utc)),
)


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _period(trades: Sequence[TournamentTrade], start, end) -> tuple[TournamentTrade, ...]:
    a, b = ensure_utc(start), ensure_utc(end)
    return tuple(t for t in trades if a <= ensure_utc(t.entry_at) < b)


def _posterior_mean(
    history: Sequence[Mapping[str, Any]],
    *,
    key_fn,
    current: Mapping[str, Any],
) -> tuple[float | None, int]:
    if len(history) < WARMUP_COMPLETED_CANDIDATES:
        return None, 0
    vals = [float(r["trade"].net_r) for r in history]
    global_mean = sum(vals) / len(vals)
    target = key_fn(current)
    group = [float(r["trade"].net_r) for r in history if key_fn(r) == target]
    posterior = (sum(group) + SHRINKAGE_ALPHA * global_mean) / (len(group) + SHRINKAGE_ALPHA)
    return float(posterior), len(group)


def _macro_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("opportunity_state", "UNKNOWN")),
        str(row.get("risk_state", "UNKNOWN")),
        str(row.get("inflation_state", "UNKNOWN")),
    )


def _positioning_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("d1_regime", "UNKNOWN")),
        str(row.get("d1_maturity", "UNKNOWN")),
        str(row.get("cot_state", "UNKNOWN")),
        str(row.get("cot_oi_state", "UNKNOWN")),
    )


def _walk_forward_routes(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, tuple[TournamentTrade, ...]], dict[str, Any]]:
    ordered = tuple(sorted(rows, key=lambda r: ensure_utc(r["trade"].signal_at)))
    selected: dict[str, list[TournamentTrade]] = {
        "A_BASELINE_H3": [],
        "B_WF_MACRO_POSTERIOR_POSITIVE": [],
        "C_WF_POSITIONING_POSTERIOR_POSITIVE": [],
        "D_WF_ENSEMBLE_POSTERIOR_POSITIVE": [],
    }
    trace = defaultdict(lambda: {"considered": 0, "selected": 0, "warmup_skips": 0})
    history: list[Mapping[str, Any]] = []

    for row in ordered:
        trade = row["trade"]
        signal_at = ensure_utc(trade.signal_at)
        history = [h for h in history if ensure_utc(h["trade"].exit_at) < signal_at]
        # Rebuild matured history from all prior candidates, including shadow-skipped ones.
        matured = [
            h for h in ordered
            if ensure_utc(h["trade"].signal_at) < signal_at
            and ensure_utc(h["trade"].exit_at) < signal_at
        ]

        selected["A_BASELINE_H3"].append(trade)
        trace["A_BASELINE_H3"]["considered"] += 1
        trace["A_BASELINE_H3"]["selected"] += 1

        macro_score, macro_n = _posterior_mean(matured, key_fn=_macro_key, current=row)
        pos_score, pos_n = _posterior_mean(matured, key_fn=_positioning_key, current=row)

        for cid in (
            "B_WF_MACRO_POSTERIOR_POSITIVE",
            "C_WF_POSITIONING_POSTERIOR_POSITIVE",
            "D_WF_ENSEMBLE_POSTERIOR_POSITIVE",
        ):
            trace[cid]["considered"] += 1

        if macro_score is None or pos_score is None:
            for cid in (
                "B_WF_MACRO_POSTERIOR_POSITIVE",
                "C_WF_POSITIONING_POSTERIOR_POSITIVE",
                "D_WF_ENSEMBLE_POSTERIOR_POSITIVE",
            ):
                trace[cid]["warmup_skips"] += 1
            continue

        if macro_score > DECISION_THRESHOLD_R:
            selected["B_WF_MACRO_POSTERIOR_POSITIVE"].append(trade)
            trace["B_WF_MACRO_POSTERIOR_POSITIVE"]["selected"] += 1
        if pos_score > DECISION_THRESHOLD_R:
            selected["C_WF_POSITIONING_POSTERIOR_POSITIVE"].append(trade)
            trace["C_WF_POSITIONING_POSTERIOR_POSITIVE"]["selected"] += 1

        macro_weight = macro_n + SHRINKAGE_ALPHA
        pos_weight = pos_n + SHRINKAGE_ALPHA
        ensemble = (macro_score * macro_weight + pos_score * pos_weight) / (macro_weight + pos_weight)
        if ensemble > DECISION_THRESHOLD_R:
            selected["D_WF_ENSEMBLE_POSTERIOR_POSITIVE"].append(trade)
            trace["D_WF_ENSEMBLE_POSTERIOR_POSITIVE"]["selected"] += 1

    return {k: tuple(v) for k, v in selected.items()}, dict(trace)


def _summary(trades, *, end, broker_spec, leverage_tiers) -> dict[str, Any]:
    full = _period(trades, START, end)
    eras = {}
    for label, a, b in ERA_WINDOWS:
        b2 = min(ensure_utc(b), ensure_utc(end))
        vals = _period(trades, a, b2) if ensure_utc(a) < b2 else ()
        eras[label] = {
            "metrics": _metrics(vals),
            "live100": _scenario(vals, broker_spec=broker_spec, leverage_tiers=leverage_tiers)["LIVE_100_1_100_CAP50"],
        }
    starts = {}
    for label, start in START_SLICES:
        vals = _period(trades, start, end)
        starts[label] = {
            "metrics": _metrics(vals),
            "live100": _scenario(vals, broker_spec=broker_spec, leverage_tiers=leverage_tiers)["LIVE_100_1_100_CAP50"],
        }
    return {
        "full_metrics": _metrics(full),
        "full_live100": _scenario(full, broker_spec=broker_spec, leverage_tiers=leverage_tiers)["LIVE_100_1_100_CAP50"],
        "eras": eras,
        "start_sensitivity": starts,
    }


def evaluate_v140(
    bars: Sequence[Bar],
    *,
    macro_series,
    driver_series,
    cot_raw_rows,
    evaluation_end,
    pip_size: float,
    costs,
    broker_spec,
    leverage_tiers,
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    end = ensure_utc(evaluation_end)
    trades = frozen_h3(rows, evaluation_end=end, pip_size=pip_size, costs=costs)
    structural = annotate_structural(rows, trades, macro_series=macro_series)
    positioned = annotate_cot(structural, build_cot_rows(cot_raw_rows))
    annotated = annotate_drivers(positioned, driver_series=driver_series)

    routed, trace = _walk_forward_routes(annotated)

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "contract": {
            "base_signal": "V134_H3_C2_H1_STRICT_FROZEN",
            "routing": "expanding walk-forward empirical-Bayes state posterior",
            "labels_available_only_after_exit": True,
            "skipped_shadow_candidates_may_train_after_exit": True,
            "warmup_completed_candidates": WARMUP_COMPLETED_CANDIDATES,
            "shrinkage_alpha": SHRINKAGE_ALPHA,
            "decision_threshold_r": DECISION_THRESHOLD_R,
            "macro_state": ["opportunity_state", "risk_state", "inflation_state"],
            "positioning_state": ["d1_regime", "d1_maturity", "cot_state", "cot_oi_state"],
            "threshold_grid_search": False,
            "calendar_routing": False,
            "future_outcome_routing": False,
            "same_trade_outcome_used_for_decision": False,
            "capital_test": "LIVE $100 / 1:100 / min 0.01 lot / 20% per-trade and aggregate risk / 50% margin cap",
            "execution_authority": False,
        },
        "router_trace": trace,
        "candidates": {
            cid: _summary(vals, end=end, broker_spec=broker_spec, leverage_tiers=leverage_tiers)
            for cid, vals in routed.items()
        },
        "note": (
            "V140 is an adaptive historical walk-forward experiment. It does not select a production winner. "
            "Any promising candidate must survive independent cost/timing stress and prospective DEMO validation."
        ),
    }
