from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_causal_m15_regime_v132 import _scenario
from .research_xau_v134_h3_robustness_v135 import (
    START,
    RECENT,
    frozen_h3,
    frozen_h3_one_h1_bar_lag,
)
from .research_xau_v136_structural_regime_forensic_v137 import annotate_structural
from .research_xau_v137_cftc_positioning_forensic_v138 import annotate_cot, build_cot_rows
from .research_xau_v138_driver_interaction_forensic_v139 import annotate_drivers
from .research_xau_v139_adaptive_causal_router_v140 import _walk_forward_routes

RESEARCH_VERSION = "XAU_V140_ROBUSTNESS_V141"
ARTIFACT_CONTRACT = "XAU_V140_ROBUSTNESS_V141_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False

CANDIDATES = (
    "A_BASELINE_H3",
    "B_WF_MACRO_POSTERIOR_POSITIVE",
    "D_WF_ENSEMBLE_POSTERIOR_POSITIVE",
)


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _period(trades: Sequence[TournamentTrade], start, end) -> tuple[TournamentTrade, ...]:
    a, b = ensure_utc(start), ensure_utc(end)
    return tuple(t for t in trades if a <= ensure_utc(t.entry_at) < b)


def _annotate(rows, trades, *, macro_series, driver_series, cot_rows):
    structural = annotate_structural(rows, trades, macro_series=macro_series)
    positioned = annotate_cot(structural, cot_rows)
    return annotate_drivers(positioned, driver_series=driver_series)


def _pack(routes, *, end, broker_spec, leverage_tiers):
    out = {}
    for cid in CANDIDATES:
        trades = routes[cid]
        full = _period(trades, START, end)
        recent = _period(trades, RECENT, end)
        out[cid] = {
            "full_metrics": _metrics(full),
            "recent_metrics": _metrics(recent),
            "full_live100": _scenario(full, broker_spec=broker_spec, leverage_tiers=leverage_tiers)["LIVE_100_1_100_CAP50"],
            "recent_live100": _scenario(recent, broker_spec=broker_spec, leverage_tiers=leverage_tiers)["LIVE_100_1_100_CAP50"],
        }
    return out


def evaluate_v141(
    bars: Sequence[Bar],
    *,
    macro_series,
    driver_series,
    cot_raw_rows,
    evaluation_end,
    pip_size,
    baseline_costs,
    super_stress_costs,
    broker_spec,
    leverage_tiers,
):
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    end = ensure_utc(evaluation_end)
    cot_rows = build_cot_rows(cot_raw_rows)

    base_trades = frozen_h3(rows, evaluation_end=end, pip_size=pip_size, costs=baseline_costs)
    base_routes, _ = _walk_forward_routes(
        _annotate(rows, base_trades, macro_series=macro_series, driver_series=driver_series, cot_rows=cot_rows)
    )

    stress_trades = frozen_h3(rows, evaluation_end=end, pip_size=pip_size, costs=super_stress_costs)
    stress_routes, _ = _walk_forward_routes(
        _annotate(rows, stress_trades, macro_series=macro_series, driver_series=driver_series, cot_rows=cot_rows)
    )

    lag_trades = frozen_h3_one_h1_bar_lag(rows, trades=base_trades)
    lag_routes, _ = _walk_forward_routes(
        _annotate(rows, lag_trades, macro_series=macro_series, driver_series=driver_series, cot_rows=cot_rows)
    )

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "contract": {
            "candidate_rules_changed": False,
            "candidates": list(CANDIDATES),
            "baseline_cost_source": "V24_STRESS_4675",
            "super_stress": "1.25x additional spread and slippage",
            "timing_stress": "same router built on H3 signals requiring one completed H1 bar earlier",
            "capital": "$100 / 1:100 / 20% risk / 50% margin cap",
            "historical_pass_is_not_promotion": True,
            "execution_authority": False,
        },
        "baseline": _pack(base_routes, end=end, broker_spec=broker_spec, leverage_tiers=leverage_tiers),
        "super_stress": _pack(stress_routes, end=end, broker_spec=broker_spec, leverage_tiers=leverage_tiers),
        "h1_lag_1bar": _pack(lag_routes, end=end, broker_spec=broker_spec, leverage_tiers=leverage_tiers),
    }
