from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_2025_bootstrap_onset_forensic_v122 import build_v122_feature_frame
from .research_xau_champion_onset_reaccel_v123 import build_reaccel_route_frame
from .research_xau_false_onset_forensic_v125 import annotate_compressed_epochs
from .research_xau_hierarchical_regime_router_v35 import _Asof, build_h1_context
from .research_xau_multihorizon_100usd_v20 import _dedupe, _limit_concurrency, _portfolio_candidates
from .research_xau_v110_robustness_v111 import assemble_v110_selector
from .research_xau_v132_h1_confirmation_v134 import (
    _apply_h1,
    _h1_permission,
    _route_c2,
)
from .research_xau_causal_m15_regime_v132 import _scenario

RESEARCH_VERSION = "XAU_V134_H3_ROBUSTNESS_V135"
ARTIFACT_CONTRACT = "XAU_V134_H3_ROBUSTNESS_V135_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False

START = datetime(2012, 1, 1, tzinfo=timezone.utc)
RECENT = datetime(2025, 1, 1, tzinfo=timezone.utc)
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


def frozen_h3(
    bars: Sequence[Bar],
    *,
    evaluation_end,
    pip_size: float,
    costs,
) -> tuple[TournamentTrade, ...]:
    """Reconstruct exact frozen V134 H3; no parameter is selected here."""
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    end = ensure_utc(evaluation_end)

    candidates = _portfolio_candidates(
        rows, base_costs=costs, stressed_costs=costs, pip_size=pip_size
    )
    raw = _limit_concurrency(
        _dedupe(
            (
                *tuple(candidates["M15_L12_ONLY"]["stress"]),
                *tuple(candidates["M15_L20_ONLY"]["stress"]),
            )
        )
    )

    frame = build_v122_feature_frame(rows)
    _, epoch_defs = build_reaccel_route_frame(frame, route_id="COMPRESSED_REACCEL")
    _, selector_all, _ = assemble_v110_selector(
        rows, costs=costs, pip_size=pip_size, evaluation_end=end
    )
    records = annotate_compressed_epochs(frame, epoch_defs, selector_all)
    c2 = _route_c2(raw, records, evaluation_end=end)
    return _apply_h1(c2, h1_context=build_h1_context(rows), mode="STRICT")


def frozen_h3_one_h1_bar_lag(
    bars: Sequence[Bar],
    *,
    trades: Sequence[TournamentTrade],
) -> tuple[TournamentTrade, ...]:
    """Timing stress only: evaluate the same frozen STRICT permission one H1 bar earlier."""
    h1 = build_h1_context(tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp))))
    lookup = _Asof(h1)
    lag = timedelta(hours=1)
    return tuple(
        trade
        for trade in trades
        if _h1_permission(
            lookup.row(ensure_utc(trade.signal_at) - lag),
            side=trade.direction,
            mode="STRICT",
        )
    )


def _pack(
    trades: Sequence[TournamentTrade],
    *,
    end,
    broker_spec,
    leverage_tiers,
) -> dict[str, Any]:
    vals = _period(trades, START, end)
    pre = _period(trades, START, RECENT)
    recent = _period(trades, RECENT, end)
    starts = {}
    for label, start in START_SLICES:
        sliced = _period(trades, start, end)
        starts[label] = {
            "metrics": _metrics(sliced),
            "live100": _scenario(
                sliced,
                broker_spec=broker_spec,
                leverage_tiers=leverage_tiers,
            )["LIVE_100_1_100_CAP50"],
        }
    return {
        "full_metrics": _metrics(vals),
        "pre2025_metrics": _metrics(pre),
        "recent_metrics": _metrics(recent),
        "full_live100": _scenario(
            vals, broker_spec=broker_spec, leverage_tiers=leverage_tiers
        )["LIVE_100_1_100_CAP50"],
        "recent_live100": _scenario(
            recent, broker_spec=broker_spec, leverage_tiers=leverage_tiers
        )["LIVE_100_1_100_CAP50"],
        "start_sensitivity": starts,
    }


def evaluate_v135(
    bars: Sequence[Bar],
    *,
    evaluation_end,
    pip_size: float,
    baseline_costs,
    super_stress_costs,
    broker_spec,
    leverage_tiers,
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    end = ensure_utc(evaluation_end)

    baseline = frozen_h3(
        rows, evaluation_end=end, pip_size=pip_size, costs=baseline_costs
    )
    super_stress = frozen_h3(
        rows, evaluation_end=end, pip_size=pip_size, costs=super_stress_costs
    )
    lagged = frozen_h3_one_h1_bar_lag(rows, trades=baseline)

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "contract": {
            "candidate": "V134_H3_C2_H1_STRICT_FROZEN",
            "rule_changes": False,
            "threshold_search": False,
            "calendar_routing": False,
            "future_outcome_routing": False,
            "baseline_cost_source": "V24_STRESS_4675",
            "super_stress": "additional 1.25x spread and 1.25x slippage on top of V24_STRESS_4675",
            "timing_stress": "same H3 permission evaluated one completed H1 bar earlier",
            "start_slices": [label for label, _ in START_SLICES],
            "broker_scenario": "LIVE $100 / 1:100 / min 0.01 / risk 20% / aggregate 20% / margin cap 50%",
            "execution_authority": False,
        },
        "acceptance_criteria": {
            "baseline_must_reproduce_v134_h3": True,
            "full_live100_min_opened": 30,
            "full_live100_min_ending_balance_strictly_gt": 100.0,
            "super_stress_full_expectancy_strictly_gt": 0.0,
            "super_stress_pre2025_expectancy_nonnegative_if_exposed": True,
            "super_stress_recent_expectancy_min": 0.08,
            "super_stress_max_drawdown_r": 20.0,
            "one_h1_lag_full_expectancy_strictly_gt": 0.0,
            "one_h1_lag_pre2025_expectancy_nonnegative_if_exposed": True,
            "one_h1_lag_recent_expectancy_min": 0.08,
            "eligible_start_slice_rule": "if n>=100 then expectancy_r must be >0 and PF>1.0",
            "historical_pass_is_not_promotion": True,
        },
        "baseline": _pack(
            baseline, end=end, broker_spec=broker_spec, leverage_tiers=leverage_tiers
        ),
        "super_stress": _pack(
            super_stress, end=end, broker_spec=broker_spec, leverage_tiers=leverage_tiers
        ),
        "one_h1_bar_lag": _pack(
            lagged, end=end, broker_spec=broker_spec, leverage_tiers=leverage_tiers
        ),
        "note": (
            "V135 is confirmatory robustness/falsification only. H3 was selected by "
            "preregistered V134 criteria, so V135 makes no further rule selection."
        ),
    }
