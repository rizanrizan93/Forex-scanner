from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any, Mapping, Sequence

import numpy as np

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_v134_h3_robustness_v135 import RECENT, START, frozen_h3
from .research_xau_v136_structural_regime_forensic_v137 import annotate_structural
from .research_xau_v137_cftc_positioning_forensic_v138 import (
    CotRow,
    annotate_cot,
    build_cot_rows,
)
from .research_xau_v135_macro_regime_v136 import _asof_change

RESEARCH_VERSION = "XAU_V138_DRIVER_INTERACTION_FORENSIC_V139"
ARTIFACT_CONTRACT = "XAU_V138_DRIVER_INTERACTION_FORENSIC_V139_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

DRIVER_SERIES = {
    "real_yield_10y": "DFII10",
    "usd_broad": "DTWEXBGS",
    "vix": "VIXCLS",
    "breakeven_10y": "T10YIE",
    "sp500": "SP500",
    "oil_wti": "DCOILWTICO",
}
LOOKBACK = 20


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _driver_snapshot(
    series: Mapping[str, Mapping[date, float]],
    signal_at: datetime,
) -> dict[str, Any]:
    d = ensure_utc(signal_at).date()

    _, real_yield = _asof_change(series["real_yield_10y"], d, relative=False, lookback=LOOKBACK)
    _, usd = _asof_change(series["usd_broad"], d, relative=True, lookback=LOOKBACK)
    _, vix = _asof_change(series["vix"], d, relative=True, lookback=LOOKBACK)
    _, breakeven = _asof_change(series["breakeven_10y"], d, relative=False, lookback=LOOKBACK)
    _, sp500 = _asof_change(series["sp500"], d, relative=True, lookback=LOOKBACK)
    _, oil = _asof_change(series["oil_wti"], d, relative=True, lookback=LOOKBACK)

    if real_yield is None or usd is None:
        opportunity = "UNKNOWN"
    elif real_yield > 0 and usd > 0:
        opportunity = "HEADWIND"
    elif real_yield <= 0 and usd <= 0:
        opportunity = "TAILWIND"
    else:
        opportunity = "MIXED"

    if vix is None or sp500 is None:
        risk = "UNKNOWN"
    elif vix > 0 and sp500 < 0:
        risk = "RISK_OFF"
    elif vix <= 0 and sp500 >= 0:
        risk = "RISK_ON"
    else:
        risk = "MIXED"

    if breakeven is None or oil is None:
        inflation = "UNKNOWN"
    elif breakeven > 0 and oil > 0:
        inflation = "INFLATION_UP"
    elif breakeven <= 0 and oil <= 0:
        inflation = "INFLATION_DOWN"
    else:
        inflation = "MIXED"

    return {
        "opportunity_state": opportunity,
        "risk_state": risk,
        "inflation_state": inflation,
        "real_yield_delta20": real_yield,
        "usd_return20": usd,
        "vix_return20": vix,
        "sp500_return20": sp500,
        "breakeven_delta20": breakeven,
        "oil_return20": oil,
    }


def annotate_drivers(
    rows: Sequence[Mapping[str, Any]],
    *,
    driver_series: Mapping[str, Mapping[date, float]],
) -> tuple[dict[str, Any], ...]:
    out = []
    for row in rows:
        payload = dict(row)
        payload.update(_driver_snapshot(driver_series, row["trade"].signal_at))
        out.append(payload)
    return tuple(out)


def _group(rows: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> dict[str, Any]:
    buckets: dict[str, list[TournamentTrade]] = defaultdict(list)
    for row in rows:
        label = "|".join(str(row[k]) for k in keys)
        buckets[label].append(row["trade"])
    return {key: _metrics(trades) for key, trades in sorted(buckets.items())}


def _slice(rows: Sequence[Mapping[str, Any]], *, start: datetime, end: datetime) -> dict[str, Any]:
    scoped = tuple(
        r for r in rows
        if ensure_utc(start) <= ensure_utc(r["trade"].entry_at) < ensure_utc(end)
    )
    ext = tuple(
        r for r in scoped
        if r["d1_regime"] == "STRONG_BULL" and r["d1_maturity"] == "EXTENDED"
    )
    return {
        "count": len(scoped),
        "metrics": _metrics(tuple(r["trade"] for r in scoped)),
        "by_opportunity": _group(scoped, ("opportunity_state",)),
        "by_risk": _group(scoped, ("risk_state",)),
        "by_inflation": _group(scoped, ("inflation_state",)),
        "opportunity_x_risk": _group(scoped, ("opportunity_state", "risk_state")),
        "opportunity_x_inflation": _group(scoped, ("opportunity_state", "inflation_state")),
        "risk_x_cot": _group(scoped, ("risk_state", "cot_state")),
        "extended_strong_bull": {
            "count": len(ext),
            "metrics": _metrics(tuple(r["trade"] for r in ext)),
            "opportunity_x_risk": _group(ext, ("opportunity_state", "risk_state")),
            "opportunity_x_inflation": _group(ext, ("opportunity_state", "inflation_state")),
            "risk_x_cot": _group(ext, ("risk_state", "cot_state")),
            "risk_x_cot_x_oi": _group(
                ext, ("risk_state", "cot_state", "cot_oi_state")
            ),
        },
    }


def evaluate_v139(
    bars: Sequence[Bar],
    *,
    macro_series,
    driver_series,
    cot_raw_rows,
    evaluation_end: datetime,
    pip_size: float,
    costs,
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    end = ensure_utc(evaluation_end)
    trades = frozen_h3(rows, evaluation_end=end, pip_size=pip_size, costs=costs)
    structural = annotate_structural(rows, trades, macro_series=macro_series)
    cot_rows: tuple[CotRow, ...] = build_cot_rows(cot_raw_rows)
    positioned = annotate_cot(structural, cot_rows)
    annotated = annotate_drivers(positioned, driver_series=driver_series)

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "live_execution_enabled": False,
        "contract": {
            "candidate": "V134_H3_C2_H1_STRICT_FROZEN",
            "driver_framework": {
                "opportunity_cost": "20-observation change in 10Y real yield + broad USD",
                "risk_uncertainty": "20-observation VIX return + S&P500 return",
                "inflation_growth_proxy": "20-observation 10Y breakeven delta + WTI return",
                "momentum_positioning": "existing D1 structural state + CFTC Managed Money/OI",
            },
            "same_day_market_driver_allowed": False,
            "lookback_observations": LOOKBACK,
            "threshold_search": False,
            "calendar_routing": False,
            "future_outcome_routing": False,
            "trade_rule_changes": False,
            "selection_authority": False,
        },
        "driver_series": dict(DRIVER_SERIES),
        "full": _slice(annotated, start=START, end=end),
        "pre2025": _slice(annotated, start=START, end=RECENT),
        "recent": _slice(annotated, start=RECENT, end=end),
        "note": (
            "V139 is interaction forensic only. It tests whether the same CFTC/technical "
            "state behaves differently depending on opportunity-cost, risk and inflation "
            "backdrops. No gate or threshold is selected from these results."
        ),
    }
