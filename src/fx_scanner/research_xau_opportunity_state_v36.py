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
from .research_xau_era_robustness_v31 import _dedupe_with_classic, _simulate_d1_classic
from .research_xau_hierarchical_regime_router_v35 import (
    ACCOUNT_LEVERAGE,
    L12_ID,
    L20_ID,
    MARGIN_FLOOR_PCT,
    _Asof,
    _adx,
    _direction_metrics,
    _max_losing_streak,
    _period,
    _trade_stats,
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

RESEARCH_VERSION = "XAU_OPPORTUNITY_STATE_V36"
ARTIFACT_CONTRACT = "XAU_OPPORTUNITY_STATE_V36_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

ATR_MEDIAN_LOOKBACK = 252
ATR_MEDIAN_MIN = 126
EXPANSION_RATIO = 1.10
CONTRACTION_RATIO = 0.90
EFFICIENCY_HIGH = 0.45
EFFICIENCY_MID = 0.25

ROUTES = (
    "MATURE_L12_NORMAL",
    "EXPANSION_ALL_BOTH_NORMAL",
    "EXPANSION_EXTENDED_BOTH_NORMAL",
    "EXPANSION_TRANSITION_EARLY_L12_NORMAL",
    "EXPANSION_HIGH_EFF_ESTABLISHED_L20_NORMAL",
    "OPPORTUNITY_ROUTER_NORMAL",
)


def build_opportunity_d1(rows: Sequence[Bar]) -> pd.DataFrame:
    d1 = build_d1_context(rows).copy()
    prior_median = (
        d1["atr14"].shift(1).rolling(
            ATR_MEDIAN_LOOKBACK,
            min_periods=ATR_MEDIAN_MIN,
        ).median()
    )
    d1["atr_ratio_prior252_median"] = d1["atr14"] / prior_median.replace(0.0, np.nan)

    path20 = d1["close"].diff().abs().rolling(20, min_periods=20).sum()
    d1["efficiency20"] = (
        (d1["close"] - d1["close"].shift(20)).abs()
        / path20.replace(0.0, np.nan)
    )
    adx, plus_di, minus_di = _adx(d1, 14)
    d1["d1_adx14"] = adx
    d1["d1_plus_di14"] = plus_di
    d1["d1_minus_di14"] = minus_di

    ratio = d1["atr_ratio_prior252_median"]
    d1["opportunity_state"] = np.where(
        ratio >= EXPANSION_RATIO,
        "EXPANSION",
        np.where(ratio < CONTRACTION_RATIO, "CONTRACTION", "NORMAL"),
    )
    eff = d1["efficiency20"]
    d1["efficiency_state"] = np.where(
        eff >= EFFICIENCY_HIGH,
        "HIGH",
        np.where(eff >= EFFICIENCY_MID, "MID", "LOW"),
    )
    return d1


def annotate_opportunity(
    trades: Sequence[TournamentTrade],
    *,
    d1_context: pd.DataFrame,
    h1_context: pd.DataFrame,
) -> tuple[dict[str, Any], ...]:
    base = annotate_m15(trades, d1_context=d1_context, h1_context=h1_context)
    d1_lookup = _Asof(d1_context)
    out: list[dict[str, Any]] = []
    for row in base:
        d1 = d1_lookup.row(row["trade"].signal_at)
        if d1 is None:
            continue
        x = dict(row)
        x["atr_ratio_prior252_median"] = float(
            d1.get("atr_ratio_prior252_median", np.nan)
        )
        x["efficiency20"] = float(d1.get("efficiency20", np.nan))
        x["opportunity_state"] = str(d1.get("opportunity_state"))
        x["efficiency_state"] = str(d1.get("efficiency_state"))
        x["d1_adx14"] = float(d1.get("d1_adx14", np.nan))
        out.append(x)
    return tuple(out)


def _family(row: Mapping[str, Any]) -> str:
    return str(row["family"])


def _route_match(row: Mapping[str, Any], route: str) -> bool:
    family = _family(row)
    maturity = str(row["maturity"])
    expansion = str(row["opportunity_state"]) == "EXPANSION"
    high_eff = str(row["efficiency_state"]) == "HIGH"
    aligned = bool(row["d1_match"]) and bool(row["h1_normal"])

    if not aligned:
        return False
    if route == "MATURE_L12_NORMAL":
        return maturity == "MATURE" and family == "L12"
    if route == "EXPANSION_ALL_BOTH_NORMAL":
        return expansion and family in {"L12", "L20"}
    if route == "EXPANSION_EXTENDED_BOTH_NORMAL":
        return expansion and maturity == "EXTENDED" and family in {"L12", "L20"}
    if route == "EXPANSION_TRANSITION_EARLY_L12_NORMAL":
        return (
            expansion
            and maturity == "EARLY"
            and bool(row["transition_from_opposite"])
            and int(row["days_in_regime"]) <= 10
            and family == "L12"
        )
    if route == "EXPANSION_HIGH_EFF_ESTABLISHED_L20_NORMAL":
        return (
            expansion
            and high_eff
            and maturity == "ESTABLISHED"
            and family == "L20"
        )
    if route == "OPPORTUNITY_ROUTER_NORMAL":
        return (
            (maturity == "MATURE" and family == "L12")
            or (
                expansion
                and maturity == "EXTENDED"
                and family in {"L12", "L20"}
            )
            or (
                expansion
                and maturity == "EARLY"
                and bool(row["transition_from_opposite"])
                and int(row["days_in_regime"]) <= 10
                and family == "L12"
            )
            or (
                expansion
                and high_eff
                and maturity == "ESTABLISHED"
                and family == "L20"
            )
        )
    raise ValueError(f"V36_UNKNOWN_ROUTE:{route}")


def _select(
    annotated: Sequence[Mapping[str, Any]],
    route: str,
) -> tuple[TournamentTrade, ...]:
    return tuple(row["trade"] for row in annotated if _route_match(row, route))


def _bucket_stats(
    annotated: Sequence[Mapping[str, Any]],
    *,
    key: str,
    trading_days: int,
) -> dict[str, Any]:
    values = sorted({str(row[key]) for row in annotated})
    return {
        value: _trade_stats(
            tuple(row["trade"] for row in annotated if str(row[key]) == value),
            trading_days,
        )
        for value in values
    }


def _cross_stats(
    annotated: Sequence[Mapping[str, Any]],
    *,
    first: str,
    second: str,
    trading_days: int,
) -> dict[str, Any]:
    keys = sorted({(str(row[first]), str(row[second])) for row in annotated})
    return {
        f"{a}|{b}": _trade_stats(
            tuple(
                row["trade"]
                for row in annotated
                if str(row[first]) == a and str(row[second]) == b
            ),
            trading_days,
        )
        for a, b in keys
    }


def evaluate_v36(
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
    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    if not rows:
        raise ValueError("V36_EMPTY_HISTORY")

    d1 = build_opportunity_d1(rows)
    h1 = build_h1_context(rows)
    signal_map = {
        variant.variant_id: extract_m15_breakout(rows, variant=variant)
        for variant in M15_VARIANTS
    }
    trading_dates = _trading_dates(rows, start=start, end=end)
    trading_days = len(trading_dates)

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        classic = _period(
            _simulate_d1_classic(rows, costs=costs, pip_size=pip_size),
            start=start,
            end=end,
        )
        m15_all: list[TournamentTrade] = []
        for variant in M15_VARIANTS:
            m15_all.extend(
                simulate_m15(
                    rows,
                    signals=signal_map[variant.variant_id],
                    costs=costs,
                    pip_size=pip_size,
                )
            )
        m15 = _period(tuple(m15_all), start=start, end=end)
        annotated = annotate_opportunity(m15, d1_context=d1, h1_context=h1)

        route_payload: dict[str, Any] = {}
        portfolio_payload: dict[str, Any] = {}
        for route in ROUTES:
            selected = _select(annotated, route)
            route_payload[route] = {
                **_trade_stats(selected, trading_days),
                "direction_metrics": _direction_metrics(selected),
            }
            combined = _limit_concurrency(
                _dedupe_with_classic((*classic, *selected))
            )
            payload = {
                **_trade_stats(combined, trading_days),
                "direction_metrics": _direction_metrics(combined),
            }
            if cost_id == "V24_STRESS_4675":
                payload["cash_fixed_001"] = _cash_path_stopout_safe(
                    combined,
                    spec=broker_spec,
                    tiers=leverage_tiers,
                    account_leverage=ACCOUNT_LEVERAGE,
                    stopout_pct=MARGIN_FLOOR_PCT,
                    trading_dates=trading_dates,
                )
            portfolio_payload[f"D1_CLASSIC_PLUS_{route}"] = payload

        aligned = tuple(
            row
            for row in annotated
            if bool(row["d1_match"]) and bool(row["h1_normal"])
        )
        scenario_results[cost_id] = {
            "costs": asdict(costs),
            "routes": route_payload,
            "portfolios": portfolio_payload,
            "diagnostics": {
                "family_x_opportunity": _cross_stats(
                    aligned,
                    first="family",
                    second="opportunity_state",
                    trading_days=trading_days,
                ),
                "family_x_efficiency": _cross_stats(
                    aligned,
                    first="family",
                    second="efficiency_state",
                    trading_days=trading_days,
                ),
                "opportunity_state": _bucket_stats(
                    aligned,
                    key="opportunity_state",
                    trading_days=trading_days,
                ),
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
        "causal_contract": {
            "d1_h1_completed_bars_only": True,
            "atr_baseline_is_prior_only": True,
            "atr_ratio": "ATR14 / prior-252-row median ATR14; current ATR excluded from baseline",
            "expansion_ratio": EXPANSION_RATIO,
            "contraction_ratio": CONTRACTION_RATIO,
            "efficiency20": "abs(close-close20) / sum(abs(daily close changes),20)",
            "efficiency_high": EFFICIENCY_HIGH,
            "efficiency_mid": EFFICIENCY_MID,
            "entry_rules_frozen": [L12_ID, L20_ID],
            "selection_uses_future_outcomes": False,
        },
        "routes": list(ROUTES),
        "scenario_results": scenario_results,
        "note": (
            "V36 is a bounded post-V35 diagnostic. It tests whether the M15 edge requires a "
            "causal daily opportunity/expansion state. Historical eras are already exposed, "
            "so even a successful result is not promotion evidence."
        ),
    }
