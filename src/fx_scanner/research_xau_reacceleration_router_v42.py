from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import (
    extract_signals as extract_m15_breakout,
    simulate as simulate_m15,
)
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_era_robustness_v31 import _dedupe_with_classic, _simulate_d1_classic
from .research_xau_hierarchical_regime_router_v35 import (
    ACCOUNT_LEVERAGE,
    L12_ID,
    L20_ID,
    MARGIN_FLOOR_PCT,
    _Asof,
    _direction_metrics,
    _max_losing_streak,
    _period,
    annotate_m15,
    build_d1_context,
    build_h1_context,
)
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    M15_VARIANTS,
    _limit_concurrency,
    _trading_dates,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_REACCELERATION_ROUTER_V42"
ARTIFACT_CONTRACT = "XAU_REACCELERATION_ROUTER_V42_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

ROUTES = (
    "REACCEL_L12_L20_5D_NORMAL",
    "REACCEL_PHASED_20D_NORMAL",
    "REACCEL_L12_L20_20D_NORMAL",
    "REACCEL_PHASED_20D_STRICT",
    "REACCEL_STRONG_D1_L12_L20_20D_NORMAL",
    "REVERSAL_PHASED_20D_NORMAL_REFERENCE",
)


def build_transition_outcome_context(rows: Sequence[Bar]) -> pd.DataFrame:
    d1 = build_d1_context(rows).copy()

    last_nonzero = 0
    transition_open = False
    origin_side = 0
    transition_days = 0

    outcome_type = "NONE"
    outcome_side = 0
    post_age = 0
    episode_transition_days = 0

    origin_values: list[int] = []
    transition_age_values: list[int] = []
    outcome_values: list[str] = []
    outcome_side_values: list[int] = []
    post_age_values: list[int] = []
    episode_days_values: list[int] = []

    for raw_side in d1["regime_side"]:
        side = int(raw_side)

        if side == 0:
            if not transition_open and last_nonzero != 0:
                transition_open = True
                origin_side = last_nonzero
                transition_days = 1
            elif transition_open:
                transition_days += 1

            outcome_type = "NONE"
            outcome_side = 0
            post_age = 0
            episode_transition_days = 0
        else:
            if transition_open:
                if side == origin_side:
                    outcome_type = "REACCELERATION"
                elif side == -origin_side:
                    outcome_type = "REVERSAL"
                else:
                    outcome_type = "NONE"
                outcome_side = side if outcome_type != "NONE" else 0
                post_age = 1 if outcome_type != "NONE" else 0
                episode_transition_days = transition_days if outcome_type != "NONE" else 0

                transition_open = False
                transition_days = 0
                origin_side = 0
            elif outcome_side == side and outcome_type in {"REACCELERATION", "REVERSAL"}:
                post_age += 1
            else:
                outcome_type = "NONE"
                outcome_side = 0
                post_age = 0
                episode_transition_days = 0

            last_nonzero = side

        origin_values.append(origin_side if transition_open else 0)
        transition_age_values.append(transition_days if transition_open else 0)
        outcome_values.append(outcome_type)
        outcome_side_values.append(outcome_side)
        post_age_values.append(post_age)
        episode_days_values.append(episode_transition_days)

    d1["transition_origin_side_v42"] = origin_values
    d1["transition_age_days_v42"] = transition_age_values
    d1["transition_outcome"] = outcome_values
    d1["transition_outcome_side"] = outcome_side_values
    d1["post_transition_age_days"] = post_age_values
    d1["episode_transition_days"] = episode_days_values
    return d1


def annotate_outcome_m15(
    trades: Sequence[TournamentTrade],
    *,
    d1_context: pd.DataFrame,
    h1_context: pd.DataFrame,
) -> tuple[dict[str, Any], ...]:
    base = annotate_m15(trades, d1_context=d1_context, h1_context=h1_context)
    lookup = _Asof(d1_context)
    out: list[dict[str, Any]] = []
    for row in base:
        d1 = lookup.row(row["trade"].signal_at)
        if d1 is None:
            continue
        enriched = dict(row)
        enriched.update(
            {
                "transition_outcome": str(d1.get("transition_outcome") or "NONE"),
                "post_transition_age_days": int(d1.get("post_transition_age_days") or 0),
                "episode_transition_days": int(d1.get("episode_transition_days") or 0),
            }
        )
        out.append(enriched)
    return tuple(out)


def _select(
    annotated: Sequence[Mapping[str, Any]],
    route: str,
) -> tuple[TournamentTrade, ...]:
    out: list[TournamentTrade] = []
    for row in annotated:
        family = str(row["family"])
        outcome = str(row["transition_outcome"])
        age = int(row["post_transition_age_days"])
        match = bool(row["d1_match"])
        normal = bool(row["h1_normal"])
        strict = bool(row["h1_strict"])
        regime = str(row["regime"])

        keep = False
        if route == "REACCEL_L12_L20_5D_NORMAL":
            keep = outcome == "REACCELERATION" and match and normal and 1 <= age <= 5 and family in {"L12", "L20"}
        elif route == "REACCEL_PHASED_20D_NORMAL":
            keep = (
                outcome == "REACCELERATION"
                and match
                and normal
                and (
                    (1 <= age <= 5 and family in {"L12", "L20"})
                    or (6 <= age <= 20 and family == "L20")
                )
            )
        elif route == "REACCEL_L12_L20_20D_NORMAL":
            keep = outcome == "REACCELERATION" and match and normal and 1 <= age <= 20 and family in {"L12", "L20"}
        elif route == "REACCEL_PHASED_20D_STRICT":
            keep = (
                outcome == "REACCELERATION"
                and match
                and strict
                and (
                    (1 <= age <= 5 and family in {"L12", "L20"})
                    or (6 <= age <= 20 and family == "L20")
                )
            )
        elif route == "REACCEL_STRONG_D1_L12_L20_20D_NORMAL":
            keep = (
                outcome == "REACCELERATION"
                and match
                and normal
                and regime in {"STRONG_BULL", "STRONG_BEAR"}
                and 1 <= age <= 20
                and family in {"L12", "L20"}
            )
        elif route == "REVERSAL_PHASED_20D_NORMAL_REFERENCE":
            keep = (
                outcome == "REVERSAL"
                and match
                and normal
                and (
                    (1 <= age <= 5 and family in {"L12", "L20"})
                    or (6 <= age <= 20 and family == "L20")
                )
            )
        else:
            raise ValueError(f"V42_ROUTE_INVALID:{route}")

        if keep:
            out.append(row["trade"])
    return tuple(out)


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _stats(trades: Sequence[TournamentTrade], trading_days: int) -> dict[str, Any]:
    values = tuple(trades)
    return {
        "trades": len(values),
        "trades_per_day": 0.0 if trading_days <= 0 else len(values) / float(trading_days),
        "max_losing_streak": _max_losing_streak(values),
        "metrics": _metrics(values),
        "direction_metrics": _direction_metrics(values),
    }


def _phase(age: int) -> str:
    if 1 <= age <= 5:
        return "1_5"
    if 6 <= age <= 20:
        return "6_20"
    if age > 20:
        return "GT20"
    return "NONE"


def _pause_bucket(days: int) -> str:
    if 1 <= days <= 3:
        return "1_3D"
    if 4 <= days <= 10:
        return "4_10D"
    if days > 10:
        return "GT10D"
    return "NONE"


def _diagnostics(
    annotated: Sequence[Mapping[str, Any]],
    *,
    trading_days: int,
) -> dict[str, Any]:
    return {
        "outcome_family_phase": {
            f"{outcome}|{family}|{phase}": _stats(
                tuple(
                    row["trade"]
                    for row in annotated
                    if str(row["transition_outcome"]) == outcome
                    and str(row["family"]) == family
                    and _phase(int(row["post_transition_age_days"])) == phase
                    and bool(row["d1_match"])
                ),
                trading_days,
            )
            for outcome in ("REACCELERATION", "REVERSAL")
            for family in ("L12", "L20")
            for phase in ("1_5", "6_20", "GT20")
        },
        "reaccel_pause_duration": {
            bucket: _stats(
                tuple(
                    row["trade"]
                    for row in annotated
                    if str(row["transition_outcome"]) == "REACCELERATION"
                    and _pause_bucket(int(row["episode_transition_days"])) == bucket
                    and bool(row["d1_match"])
                ),
                trading_days,
            )
            for bucket in ("1_3D", "4_10D", "GT10D")
        },
    }


def evaluate_v42(
    bars: Sequence[Bar],
    *,
    era_id: str,
    era_start,
    era_end,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
    broker_spec: BrokerLotSpec,
    leverage_tiers: Sequence[LeverageTier],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V42_EMPTY_HISTORY")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    d1_context = build_transition_outcome_context(rows)
    h1_context = build_h1_context(rows)
    trading_dates = _trading_dates(rows, start=start, end=end)
    trading_days = len(trading_dates)

    selected_variants = tuple(
        x for x in M15_VARIANTS if x.variant_id in {L12_ID, L20_ID}
    )
    signal_map = {
        variant.variant_id: extract_m15_breakout(rows, variant=variant)
        for variant in selected_variants
    }

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        classic = _period(
            _simulate_d1_classic(rows, costs=costs, pip_size=pip_size),
            start=start,
            end=end,
        )
        m15_all: list[TournamentTrade] = []
        for variant in selected_variants:
            m15_all.extend(
                simulate_m15(
                    rows,
                    signals=signal_map[variant.variant_id],
                    costs=costs,
                    pip_size=pip_size,
                )
            )
        m15 = _period(tuple(m15_all), start=start, end=end)
        annotated = annotate_outcome_m15(
            m15,
            d1_context=d1_context,
            h1_context=h1_context,
        )
        routes = {route: _select(annotated, route) for route in ROUTES}

        portfolios: dict[str, Any] = {
            "D1_CLASSIC_ONLY": _stats(classic, trading_days),
        }
        for route, selected in routes.items():
            combined = _limit_concurrency(
                _dedupe_with_classic((*classic, *selected))
            )
            payload = _stats(combined, trading_days)
            if cost_id == "V24_STRESS_4675":
                payload["cash_fixed_001"] = _cash_path_stopout_safe(
                    combined,
                    spec=broker_spec,
                    tiers=leverage_tiers,
                    account_leverage=ACCOUNT_LEVERAGE,
                    stopout_pct=MARGIN_FLOOR_PCT,
                    trading_dates=trading_dates,
                )
            portfolios[f"D1_CLASSIC_PLUS_{route}"] = payload

        scenario_results[cost_id] = {
            "costs": asdict(costs),
            "portfolios": portfolios,
            "routed_m15": {
                route: _stats(trades, trading_days)
                for route, trades in routes.items()
            },
            "diagnostics": _diagnostics(annotated, trading_days=trading_days),
        }

    starts = d1_context[d1_context["post_transition_age_days"] == 1]
    episode_counts = {
        outcome: int((starts["transition_outcome"] == outcome).sum())
        for outcome in ("REACCELERATION", "REVERSAL")
    }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "era_id": era_id,
        "era_start": start.isoformat(),
        "era_end_exclusive": end.isoformat(),
        "trading_days": trading_days,
        "episode_counts": episode_counts,
        "preregistered_contract": {
            "reacceleration": "NONZERO_SIDE -> ONE_OR_MORE_TRANSITION_DAYS -> SAME_NONZERO_SIDE",
            "reversal_reference": "NONZERO_SIDE -> ONE_OR_MORE_TRANSITION_DAYS -> OPPOSITE_NONZERO_SIDE",
            "h1_role": "PERMISSION_ONLY",
            "m15_entries": "FROZEN_V20_L12_L20",
            "m15_off_during_transition": True,
            "countertrend_m15_allowed": False,
            "post_transition_windows": ["1_5D", "6_20D", "GT20D_DIAGNOSTIC_ONLY"],
            "pause_duration": "DIAGNOSTIC_ONLY_NO_ROUTE_THRESHOLD",
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
        },
        "routes": list(ROUTES),
        "scenario_results": scenario_results,
        "note": (
            "V42 distinguishes same-side D1 reacceleration from opposite-side reversal. "
            "It does not change L12/L20 entries and cannot authorize execution."
        ),
    }
