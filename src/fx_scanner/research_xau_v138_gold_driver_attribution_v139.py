from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .models import Bar, ensure_utc
from .research_xau_hierarchical_regime_router_v35 import (
    _Asof,
    _resample_completed,
    build_d1_context,
)
from .research_xau_v135_macro_regime_v136 import _asof_change

RESEARCH_VERSION = "XAU_V138_GOLD_DRIVER_ATTRIBUTION_V139"
ARTIFACT_CONTRACT = "XAU_V138_GOLD_DRIVER_ATTRIBUTION_V139_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

LOOKBACK_OBSERVATIONS = 20
FORWARD_HORIZONS = (1, 5, 20)

FRED_SERIES = {
    "real_yield_10y": "DFII10",
    "usd_broad": "DTWEXBGS",
    "policy_2y": "DGS2",
    "nominal_10y": "DGS10",
    "breakeven_10y": "T10YIE",
    "vix": "VIXCLS",
    "wti": "DCOILWTICO",
}


def _driver_change(
    series: Mapping[date, float], signal_date: date, *, relative: bool
) -> float | None:
    _, value = _asof_change(
        series,
        signal_date,
        relative=relative,
        lookback=LOOKBACK_OBSERVATIONS,
    )
    return value


def _sign(value: float | None, positive: str, nonpositive: str) -> str:
    if value is None or not np.isfinite(float(value)):
        return "UNKNOWN"
    return positive if float(value) > 0.0 else nonpositive


def build_daily_panel(
    bars: Sequence[Bar],
    *,
    macro_series: Mapping[str, Mapping[date, float]],
) -> tuple[dict[str, Any], ...]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    d1 = _resample_completed(rows, "1D")
    context = build_d1_context(rows)
    d1_lookup = _Asof(context)

    closes = d1["close"].astype(float).to_numpy()
    times = [
        ensure_utc(x.to_pydatetime() if hasattr(x, "to_pydatetime") else x)
        for x in d1["time"]
    ]

    out: list[dict[str, Any]] = []
    for i, (ts, close) in enumerate(zip(times, closes, strict=True)):
        signal_date = ts.date()
        if i < LOOKBACK_OBSERVATIONS:
            continue

        real_yield = _driver_change(
            macro_series["real_yield_10y"], signal_date, relative=False
        )
        usd = _driver_change(macro_series["usd_broad"], signal_date, relative=True)
        policy_2y = _driver_change(
            macro_series["policy_2y"], signal_date, relative=False
        )
        nominal_10y = _driver_change(
            macro_series["nominal_10y"], signal_date, relative=False
        )
        breakeven = _driver_change(
            macro_series["breakeven_10y"], signal_date, relative=False
        )
        vix = _driver_change(macro_series["vix"], signal_date, relative=True)
        wti = _driver_change(macro_series["wti"], signal_date, relative=True)

        if real_yield is None or usd is None:
            opp_cost = "UNKNOWN"
        elif real_yield <= 0.0 and usd <= 0.0:
            opp_cost = "SUPPORTIVE"
        elif real_yield > 0.0 and usd > 0.0:
            opp_cost = "HOSTILE"
        else:
            opp_cost = "MIXED"

        if breakeven is None or wti is None:
            inflation_state = "UNKNOWN"
        elif breakeven > 0.0 and wti > 0.0:
            inflation_state = "INFLATION_PRESSURE_UP"
        elif breakeven <= 0.0 and wti <= 0.0:
            inflation_state = "INFLATION_PRESSURE_DOWN"
        else:
            inflation_state = "MIXED"

        technical = d1_lookup.row(ts)
        ret20 = close / closes[i - LOOKBACK_OBSERVATIONS] - 1.0

        record: dict[str, Any] = {
            "signal_at": ts,
            "close": float(close),
            "gold_ret20": float(ret20),
            "momentum_state": "GOLD_MOMENTUM_UP" if ret20 > 0.0 else "GOLD_MOMENTUM_DOWN",
            "opportunity_cost": opp_cost,
            "real_yield_state": _sign(real_yield, "REAL_YIELD_UP", "REAL_YIELD_DOWN"),
            "usd_state": _sign(usd, "USD_UP", "USD_DOWN"),
            "policy_2y_state": _sign(policy_2y, "POLICY_2Y_UP", "POLICY_2Y_DOWN"),
            "nominal_10y_state": _sign(
                nominal_10y, "NOMINAL_10Y_UP", "NOMINAL_10Y_DOWN"
            ),
            "breakeven_state": _sign(
                breakeven, "BREAKEVEN_UP", "BREAKEVEN_DOWN"
            ),
            "risk_state": _sign(vix, "VIX_UP", "VIX_DOWN"),
            "oil_state": _sign(wti, "WTI_UP", "WTI_DOWN"),
            "inflation_state": inflation_state,
            "real_yield_delta20": real_yield,
            "usd_return20": usd,
            "policy_2y_delta20": policy_2y,
            "nominal_10y_delta20": nominal_10y,
            "breakeven_delta20": breakeven,
            "vix_return20": vix,
            "wti_return20": wti,
            "d1_regime": "UNKNOWN" if technical is None else str(technical.get("regime")),
            "d1_maturity": "UNKNOWN" if technical is None else str(technical.get("maturity")),
        }

        for horizon in FORWARD_HORIZONS:
            j = i + horizon
            record[f"fwd_{horizon}d"] = (
                None if j >= len(closes) else float(closes[j] / close - 1.0)
            )
        out.append(record)

    return tuple(out)


def _forward_stats(rows: Sequence[Mapping[str, Any]], horizon: int) -> dict[str, Any]:
    key = f"fwd_{horizon}d"
    vals = np.asarray(
        [
            float(r[key])
            for r in rows
            if r.get(key) is not None and np.isfinite(float(r[key]))
        ],
        dtype=float,
    )
    if vals.size == 0:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "hit_rate": None,
            "q25": None,
            "q75": None,
        }
    return {
        "n": int(vals.size),
        "mean": float(vals.mean()),
        "median": float(np.median(vals)),
        "hit_rate": float((vals > 0.0).mean()),
        "q25": float(np.quantile(vals, 0.25)),
        "q75": float(np.quantile(vals, 0.75)),
    }


def _bucket(
    rows: Sequence[Mapping[str, Any]], keys: Sequence[str]
) -> dict[str, Any]:
    buckets: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        name = "|".join(str(row[k]) for k in keys)
        buckets[name].append(row)
    return {
        name: {
            f"{h}d": _forward_stats(bucket_rows, h)
            for h in FORWARD_HORIZONS
        }
        for name, bucket_rows in sorted(buckets.items())
    }


def _period(
    rows: Sequence[Mapping[str, Any]], start: datetime, end: datetime
) -> tuple[Mapping[str, Any], ...]:
    a, b = ensure_utc(start), ensure_utc(end)
    return tuple(r for r in rows if a <= ensure_utc(r["signal_at"]) < b)


def _pack(
    rows: Sequence[Mapping[str, Any]], *, start: datetime, end: datetime
) -> dict[str, Any]:
    scoped = _period(rows, start, end)
    return {
        "rows": len(scoped),
        "all": {f"{h}d": _forward_stats(scoped, h) for h in FORWARD_HORIZONS},
        "opportunity_cost": _bucket(scoped, ("opportunity_cost",)),
        "risk": _bucket(scoped, ("risk_state",)),
        "inflation": _bucket(scoped, ("inflation_state",)),
        "policy_2y": _bucket(scoped, ("policy_2y_state",)),
        "momentum": _bucket(scoped, ("momentum_state",)),
        "d1_regime": _bucket(scoped, ("d1_regime",)),
        "d1_regime_x_opportunity_cost": _bucket(
            scoped, ("d1_regime", "opportunity_cost")
        ),
        "d1_regime_x_risk": _bucket(scoped, ("d1_regime", "risk_state")),
        "momentum_x_opportunity_cost": _bucket(
            scoped, ("momentum_state", "opportunity_cost")
        ),
        "momentum_x_risk": _bucket(scoped, ("momentum_state", "risk_state")),
    }


def evaluate_v139(
    bars: Sequence[Bar],
    *,
    macro_series: Mapping[str, Mapping[date, float]],
    evaluation_end: datetime,
) -> dict[str, Any]:
    end = ensure_utc(evaluation_end)
    panel = build_daily_panel(bars, macro_series=macro_series)
    start = datetime(2012, 1, 1, tzinfo=end.tzinfo)
    recent = datetime(2025, 1, 1, tzinfo=end.tzinfo)
    mid = datetime(2019, 1, 1, tzinfo=end.tzinfo)

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "live_execution_enabled": False,
        "contract": {
            "framework": "WGC_STYLE_DRIVER_MAP_WITH_PUBLIC_POINT_IN_TIME_PROXIES",
            "lookback_observations": LOOKBACK_OBSERVATIONS,
            "forward_horizons": list(FORWARD_HORIZONS),
            "same_day_macro_allowed": False,
            "economic_expansion_proxy": "not scored in V139; insufficient daily point-in-time public proxy chosen",
            "risk_uncertainty_proxy": "VIX 20-observation return sign",
            "opportunity_cost_rates_proxy": "10Y real yield + 2Y/10Y nominal yield 20-observation deltas",
            "opportunity_cost_fx_proxy": "broad USD 20-observation return",
            "inflation_proxy": "10Y breakeven delta + WTI return",
            "momentum_proxy": "gold completed-D1 20-session return",
            "technical_context": "V35 completed-D1 regime and maturity",
            "threshold_search": False,
            "calendar_routing": False,
            "future_outcome_routing": False,
            "selection_authority": False,
        },
        "fred_series": dict(FRED_SERIES),
        "full": _pack(panel, start=start, end=end),
        "era_2012_2018": _pack(panel, start=start, end=mid),
        "era_2019_2024": _pack(panel, start=mid, end=recent),
        "era_2025_2026": _pack(panel, start=recent, end=end),
        "note": (
            "V139 is directional forensic research, not a trading gate. It measures "
            "forward gold returns under preregistered sign-based driver states and "
            "their interaction with already-defined D1 technical regimes."
        ),
    }
