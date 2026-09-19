from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import (
    extract_signals as extract_m15_breakout,
    simulate as simulate_m15,
)
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_cost_viability_router_v43 import _annotate_cost
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
from .research_xau_reacceleration_router_v42 import (
    build_transition_outcome_context,
)

RESEARCH_VERSION = "XAU_SECULAR_REGIME_ROUTER_V46"
ARTIFACT_CONTRACT = "XAU_SECULAR_REGIME_ROUTER_V46_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

SECULAR_MOMENTUM_DAYS = 252
SECULAR_SLOPE_DAYS = 60
COST_R_CAP = 0.10

ROUTES = (
    "SECULAR_BULL_LONG_L12_L20_COST10",
    "SECULAR_BULL_LONG_L20_COST10",
    "SECULAR_BULL_REACCEL_LONG_L12_L20_COST10",
    "SECULAR_BEAR_SHORT_L12_L20_COST10_CONTROL",
    "SECULAR_TREND_BOTH_L12_L20_COST10",
)


def build_secular_d1(rows: Sequence[Bar]) -> pd.DataFrame:
    d1 = build_transition_outcome_context(rows).copy()
    d1["ret252"] = d1["close"] / d1["close"].shift(SECULAR_MOMENTUM_DAYS) - 1.0
    d1["ema200_slope60"] = d1["ema200"] - d1["ema200"].shift(SECULAR_SLOPE_DAYS)

    bull = (
        (d1["close"] > d1["ema200"])
        & (d1["ret252"] > 0.0)
        & (d1["ema200_slope60"] > 0.0)
    )
    bear = (
        (d1["close"] < d1["ema200"])
        & (d1["ret252"] < 0.0)
        & (d1["ema200_slope60"] < 0.0)
    )
    d1["secular_side"] = np.where(bull, 1, np.where(bear, -1, 0)).astype(int)
    d1["secular_regime"] = np.where(
        bull,
        "SECULAR_BULL",
        np.where(bear, "SECULAR_BEAR", "SECULAR_NEUTRAL"),
    )
    return d1


def annotate_secular(
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
                "secular_side": int(d1.get("secular_side") or 0),
                "secular_regime": str(d1.get("secular_regime") or "SECULAR_NEUTRAL"),
                "ret252": float(d1.get("ret252", np.nan)),
                "ema200_slope60": float(d1.get("ema200_slope60", np.nan)),
                "transition_outcome": str(d1.get("transition_outcome") or "NONE"),
                "post_transition_age_days": int(d1.get("post_transition_age_days") or 0),
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
        trade = row["trade"]
        side = 1 if str(trade.direction).upper() == "LONG" else -1
        secular_side = int(row["secular_side"])
        cost_ok = float(row["entry_friction_r"]) <= COST_R_CAP
        h1_ok = bool(row["h1_normal"])
        d1_match = bool(row["d1_match"])
        age = int(row["post_transition_age_days"])
        reaccel = str(row["transition_outcome"]) == "REACCELERATION"

        keep = False
        if route == "SECULAR_BULL_LONG_L12_L20_COST10":
            keep = (
                side == 1
                and secular_side == 1
                and d1_match
                and h1_ok
                and family in {"L12", "L20"}
                and cost_ok
            )
        elif route == "SECULAR_BULL_LONG_L20_COST10":
            keep = (
                side == 1
                and secular_side == 1
                and d1_match
                and h1_ok
                and family == "L20"
                and cost_ok
            )
        elif route == "SECULAR_BULL_REACCEL_LONG_L12_L20_COST10":
            keep = (
                side == 1
                and secular_side == 1
                and d1_match
                and h1_ok
                and reaccel
                and 1 <= age <= 20
                and family in {"L12", "L20"}
                and cost_ok
            )
        elif route == "SECULAR_BEAR_SHORT_L12_L20_COST10_CONTROL":
            keep = (
                side == -1
                and secular_side == -1
                and d1_match
                and h1_ok
                and family in {"L12", "L20"}
                and cost_ok
            )
        elif route == "SECULAR_TREND_BOTH_L12_L20_COST10":
            keep = (
                secular_side == side
                and secular_side != 0
                and d1_match
                and h1_ok
                and family in {"L12", "L20"}
                and cost_ok
            )
        else:
            raise ValueError(f"V46_ROUTE_INVALID:{route}")

        if keep:
            out.append(trade)
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


def evaluate_v46(
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
        raise ValueError("V46_EMPTY_HISTORY")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    d1_context = build_secular_d1(rows)
    h1_context = build_h1_context(rows)
    trading_dates = _trading_dates(rows, start=start, end=end)
    trading_days = len(trading_dates)

    variants = tuple(x for x in M15_VARIANTS if x.variant_id in {L12_ID, L20_ID})
    signal_map = {
        variant.variant_id: extract_m15_breakout(rows, variant=variant)
        for variant in variants
    }

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        classic = _period(
            _simulate_d1_classic(rows, costs=costs, pip_size=pip_size),
            start=start,
            end=end,
        )

        m15_all: list[TournamentTrade] = []
        for variant in variants:
            m15_all.extend(
                simulate_m15(
                    rows,
                    signals=signal_map[variant.variant_id],
                    costs=costs,
                    pip_size=pip_size,
                )
            )
        m15 = _period(tuple(m15_all), start=start, end=end)
        annotated = annotate_secular(
            m15,
            d1_context=d1_context,
            h1_context=h1_context,
        )
        annotated = _annotate_cost(annotated, pip_size=pip_size, costs=costs)
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
            "routes": {route: _stats(trades, trading_days) for route, trades in routes.items()},
            "portfolios": portfolios,
            "secular_day_counts": {
                "bull": int((d1_context["secular_regime"] == "SECULAR_BULL").sum()),
                "bear": int((d1_context["secular_regime"] == "SECULAR_BEAR").sum()),
                "neutral": int((d1_context["secular_regime"] == "SECULAR_NEUTRAL").sum()),
            },
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
        "preregistered_contract": {
            "secular_momentum_days": SECULAR_MOMENTUM_DAYS,
            "secular_ema200_slope_days": SECULAR_SLOPE_DAYS,
            "secular_bull": "close>EMA200 AND ret252>0 AND EMA200_slope60>0",
            "secular_bear": "close<EMA200 AND ret252<0 AND EMA200_slope60<0",
            "h1_role": "NORMAL_PERMISSION_ONLY",
            "entry_families": [L12_ID, L20_ID],
            "cost_r_cap": COST_R_CAP,
            "year_or_era_feature_used": False,
            "signal_logic_retuned": False,
            "dense_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "routes": list(ROUTES),
        "scenario_results": scenario_results,
        "note": (
            "V46 tests a causal one-year secular state rather than calendar-era labels. "
            "It preserves the frozen V20 L12/L20 entries and V43 cost gate."
        ),
    }
