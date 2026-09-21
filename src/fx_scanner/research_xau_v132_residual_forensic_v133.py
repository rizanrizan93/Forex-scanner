from __future__ import annotations

from typing import Any, Mapping, Sequence

from .models import Bar, ensure_utc
from .research_xau_2025_bootstrap_onset_forensic_v122 import build_v122_feature_frame
from .research_xau_champion_onset_reaccel_v123 import build_reaccel_route_frame
from .research_xau_false_onset_forensic_v125 import annotate_compressed_epochs
from .research_xau_multihorizon_100usd_v20 import _dedupe, _limit_concurrency, _portfolio_candidates
from .research_xau_qualitative_reaccel_gate_v126 import passes_qualitative_gate
from .research_xau_v110_robustness_v111 import assemble_v110_selector
from .research_xau_v130_epoch_forensic_v131 import (
    FEATURE_KEYS,
    _epoch_trades,
    _era,
    _metrics,
    _net,
    _robust_effect,
)
from .research_xau_causal_m15_regime_v132 import _triple_contraction

RESEARCH_VERSION = "XAU_V132_RESIDUAL_FORENSIC_V133"
ARTIFACT_CONTRACT = "XAU_V132_RESIDUAL_FORENSIC_V133_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False


def _residual_c2(rec: Mapping[str, Any]) -> bool:
    return (
        passes_qualitative_gate(rec)
        and str(rec.get("side", "")).upper() == "LONG"
        and _triple_contraction(rec)
    )


def evaluate_v133(
    rows: Sequence[Bar],
    *,
    evaluation_end,
    pip_size: float,
    costs,
) -> dict[str, Any]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    end = ensure_utc(evaluation_end)

    candidates = _portfolio_candidates(
        bars, base_costs=costs, stressed_costs=costs, pip_size=pip_size
    )
    raw_l12 = tuple(candidates["M15_L12_ONLY"]["stress"])
    raw_l20 = tuple(candidates["M15_L20_ONLY"]["stress"])
    raw_combined = _limit_concurrency(_dedupe((*raw_l12, *raw_l20)))

    frame = build_v122_feature_frame(bars)
    _, epoch_defs = build_reaccel_route_frame(frame, route_id="COMPRESSED_REACCEL")
    _, selector_all, _ = assemble_v110_selector(
        bars, costs=costs, pip_size=pip_size, evaluation_end=end
    )
    records = annotate_compressed_epochs(frame, epoch_defs, selector_all)
    residual = tuple(rec for rec in records if _residual_c2(rec))

    epoch_rows: list[dict[str, Any]] = []
    for rec in residual:
        vals = _epoch_trades(raw_combined, rec, end=end)
        metrics = _metrics(vals)
        start = ensure_utc(__import__("pandas").Timestamp(rec["start"]).to_pydatetime())
        row: dict[str, Any] = {
            "start": start.isoformat(),
            "end_exclusive": rec.get("end_exclusive"),
            "era": _era(start),
            "trade_count": int(metrics["completed_trades"]),
            "profit_factor": metrics["profit_factor"],
            "expectancy_r": metrics["expectancy_r"],
            "net_r": _net(metrics),
            "max_drawdown_r": metrics["max_drawdown_r"],
            "outcome": (
                "NO_TRADES"
                if int(metrics["completed_trades"]) == 0
                else ("POSITIVE" if _net(metrics) > 0 else "NONPOSITIVE")
            ),
            "state": rec.get("state"),
            "species": rec.get("species"),
            "raw_state": rec.get("raw_state"),
            "direction_state": rec.get("direction_state"),
        }
        for key in FEATURE_KEYS:
            row[key] = rec.get(key)
        epoch_rows.append(row)

    pre = [
        row
        for row in epoch_rows
        if row["era"] != "2025_2026YTD" and row["outcome"] != "NO_TRADES"
    ]
    pre_pos = [row for row in pre if row["outcome"] == "POSITIVE"]
    pre_bad = [row for row in pre if row["outcome"] == "NONPOSITIVE"]
    recent = [
        row
        for row in epoch_rows
        if row["era"] == "2025_2026YTD" and row["outcome"] != "NO_TRADES"
    ]

    effects_pre = {
        key: _robust_effect(pre_pos, pre_bad, key)
        for key in FEATURE_KEYS
    }
    ranked_pre = sorted(
        FEATURE_KEYS, key=lambda k: abs(effects_pre[k] or 0.0), reverse=True
    )
    effects_recent = {
        key: _robust_effect(recent, pre_bad, key)
        for key in FEATURE_KEYS
    }
    ranked_recent = sorted(
        FEATURE_KEYS, key=lambda k: abs(effects_recent[k] or 0.0), reverse=True
    )

    by_era: dict[str, dict[str, Any]] = {}
    for label in ("2012_2018", "2019_2024", "2025_2026YTD"):
        vals = []
        for rec in residual:
            start = ensure_utc(__import__("pandas").Timestamp(rec["start"]).to_pydatetime())
            if _era(start) == label:
                vals.extend(_epoch_trades(raw_combined, rec, end=end))
        by_era[label] = _metrics(tuple(vals))

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "contract": {
            "purpose": "forensic attribution of the residual V132 C2 failure only",
            "parent_candidate": "C2_V126_LONG_20D_TRIPLE_CONTRACTION",
            "signal_family": "exact V24 raw M15 L12+L20 combined",
            "base_gate": "exact frozen V126 + LONG + 20D triple contraction",
            "future_outcome_used_only_as_forensic_label": True,
            "threshold_selection": False,
            "parameter_grid_search": False,
            "calendar_routing": False,
            "selector_creation": False,
            "execution_authority": False,
            "next_step_rule": "V133 findings may only motivate a separately preregistered V134 experiment",
        },
        "counts": {
            "residual_epochs": len(epoch_rows),
            "pre_positive": len(pre_pos),
            "pre_nonpositive": len(pre_bad),
            "recent_epochs": len(recent),
        },
        "by_era": by_era,
        "effect_pre_positive_vs_nonpositive": effects_pre,
        "ranked_pre_separator_features": ranked_pre,
        "effect_recent_vs_pre_nonpositive": effects_recent,
        "ranked_recent_vs_prebad_features": ranked_recent,
        "epochs": epoch_rows,
        "note": (
            "V133 is forensic-only. No feature, sign, percentile, threshold, or category "
            "identified here receives routing or execution authority."
        ),
    }
