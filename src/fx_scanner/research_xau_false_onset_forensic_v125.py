from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_2025_bootstrap_onset_forensic_v122 import build_v122_feature_frame
from .research_xau_champion_onset_reaccel_v123 import build_reaccel_route_frame
from .research_xau_v110_robustness_v111 import assemble_v110_selector

RESEARCH_VERSION = "XAU_FALSE_ONSET_FORENSIC_V125"
ARTIFACT_CONTRACT = "XAU_FALSE_ONSET_FORENSIC_V125_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False

ROUTE_ID = "COMPRESSED_REACCEL"
TRAJECTORY_LAGS = (5, 20)
NORMALIZED_FEATURES = (
    "pct_atr_ratio_252",
    "pct_ema200_distance_atr",
    "pct_atr14_pct",
    "pct_range20_atr",
    "pct_drawdown60_atr",
    "pct_trend60_atr",
    "pct_ret60_atr",
)
LEVEL_FEATURES = NORMALIZED_FEATURES + ("era_score",)


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _net_r(metrics: Mapping[str, Any]) -> float:
    return float(metrics.get("gross_profit_r", 0.0)) - float(metrics.get("gross_loss_r", 0.0))


def _era_label(ts) -> str:
    t = ensure_utc(ts)
    if t < datetime(2019, 1, 1, tzinfo=timezone.utc):
        return "2012_2018"
    if t < datetime(2025, 1, 1, tzinfo=timezone.utc):
        return "2019_2024"
    return "2025_2026YTD"


def _finite(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if isfinite(f) else None


def _asof_index(frame: pd.DataFrame, ts) -> int | None:
    times = frame["available_at"].map(ensure_utc).tolist()
    target = ensure_utc(ts)
    i = int(np.searchsorted(np.asarray(times, dtype="datetime64[ns]"), np.datetime64(target.replace(tzinfo=None)), side="right") - 1)
    return None if i < 0 else i


def _trajectory_snapshot(frame: pd.DataFrame, ts) -> dict[str, Any]:
    x = frame.sort_values("available_at").reset_index(drop=True)
    idx = _asof_index(x, ts)
    if idx is None:
        return {"feature_available_at": None}

    row = x.iloc[idx]
    out: dict[str, Any] = {
        "feature_available_at": ensure_utc(row["available_at"]).isoformat(),
        "state": str(row.get("state") or "UNCLASSIFIED"),
        "species": str(row.get("species") or "UNCLASSIFIED"),
        "raw_state": str(row.get("raw_state") or "UNCLASSIFIED"),
        "direction_state": str(row.get("direction_state") or "UNCLASSIFIED"),
    }
    for feature in LEVEL_FEATURES:
        out[feature] = _finite(row.get(feature))
    for lag in TRAJECTORY_LAGS:
        j = idx - lag
        for feature in NORMALIZED_FEATURES:
            key = f"d{lag}_{feature}"
            if j < 0:
                out[key] = None
                continue
            now = _finite(row.get(feature))
            prev = _finite(x.iloc[j].get(feature))
            out[key] = None if now is None or prev is None else float(now - prev)
    return out


def _period(
    trades: Sequence[TournamentTrade],
    start,
    end_exclusive,
    *,
    side: str | None = None,
) -> tuple[TournamentTrade, ...]:
    a = ensure_utc(start)
    b = None if end_exclusive is None else ensure_utc(end_exclusive)
    out = []
    for t in trades:
        at = ensure_utc(t.entry_at)
        if at < a or (b is not None and at >= b):
            continue
        if side is not None and str(t.direction).upper() != str(side).upper():
            continue
        out.append(t)
    return tuple(out)


def _profile(records: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in keys:
        vals = [_finite(r.get(key)) for r in records]
        arr = np.asarray([x for x in vals if x is not None], dtype=float)
        if len(arr) == 0:
            out[key] = {"n": 0, "p25": None, "median": None, "p75": None, "mean": None}
        else:
            out[key] = {
                "n": int(len(arr)),
                "p25": float(np.quantile(arr, 0.25)),
                "median": float(np.median(arr)),
                "p75": float(np.quantile(arr, 0.75)),
                "mean": float(np.mean(arr)),
            }
    return out


def _robust_effect(a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]], key: str) -> float | None:
    xa = np.asarray([x for x in (_finite(r.get(key)) for r in a) if x is not None], dtype=float)
    xb = np.asarray([x for x in (_finite(r.get(key)) for r in b) if x is not None], dtype=float)
    if len(xa) == 0 or len(xb) == 0:
        return None
    pooled = np.concatenate([xa, xb])
    med = float(np.median(pooled))
    mad = float(np.median(np.abs(pooled - med)))
    if not isfinite(mad) or mad <= 1e-12:
        return None
    return float((np.median(xa) - np.median(xb)) / (1.4826 * mad))


def annotate_compressed_epochs(
    feature_frame: pd.DataFrame,
    epochs: Sequence[Mapping[str, Any]],
    selector_trades: Sequence[TournamentTrade],
) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for ep in epochs:
        start = ensure_utc(pd.Timestamp(ep["start"]).to_pydatetime())
        end = None
        if ep.get("end_exclusive") is not None:
            end = ensure_utc(pd.Timestamp(ep["end_exclusive"]).to_pydatetime())
        side = str(ep["side"]).upper()
        trades = _period(selector_trades, start, end, side=side)
        metrics = _metrics(trades)
        net = _net_r(metrics)
        rec = {
            "start": start.isoformat(),
            "end_exclusive": None if end is None else end.isoformat(),
            "side": side,
            "era": _era_label(start),
            "trade_count": int(metrics["completed_trades"]),
            "net_r": float(net),
            "profit_factor": metrics.get("profit_factor"),
            "expectancy_r": metrics.get("expectancy_r"),
            "max_drawdown_r": metrics.get("max_drawdown_r"),
            "outcome_sign": (
                "NO_TRADES"
                if int(metrics["completed_trades"]) == 0
                else ("POSITIVE_NET_R" if net > 0.0 else "NONPOSITIVE_NET_R")
            ),
        }
        rec.update(_trajectory_snapshot(feature_frame, start))
        records.append(rec)
    return tuple(records)


def evaluate_v125(
    rows: Sequence[Bar],
    *,
    evaluation_end,
    pip_size: float,
    costs,
) -> dict[str, Any]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    end = ensure_utc(evaluation_end)
    feature_frame = build_v122_feature_frame(bars)
    route_frame, epochs = build_reaccel_route_frame(feature_frame, route_id=ROUTE_ID)
    del route_frame

    _, selector_all, _ = assemble_v110_selector(
        bars,
        costs=costs,
        pip_size=pip_size,
        evaluation_end=end,
    )
    selector = tuple(t for t in selector_all if ensure_utc(t.entry_at) < end)
    records = annotate_compressed_epochs(feature_frame, epochs, selector)

    keys = tuple(LEVEL_FEATURES) + tuple(
        f"d{lag}_{feature}" for lag in TRAJECTORY_LAGS for feature in NORMALIZED_FEATURES
    )
    prior = [r for r in records if ensure_utc(pd.Timestamp(r["start"]).to_pydatetime()) < datetime(2025, 1, 1, tzinfo=timezone.utc)]
    prior_positive = [r for r in prior if r["outcome_sign"] == "POSITIVE_NET_R"]
    prior_nonpositive = [r for r in prior if r["outcome_sign"] == "NONPOSITIVE_NET_R"]
    mid_nonpositive = [r for r in prior_nonpositive if r["era"] == "2019_2024"]

    effects = {
        key: _robust_effect(prior_positive, prior_nonpositive, key)
        for key in keys
    }
    ranked = sorted(
        keys,
        key=lambda key: abs(effects[key] or 0.0),
        reverse=True,
    )

    jan2025 = next(
        (r for r in records if str(r["start"]).startswith("2025-01-16")),
        None,
    )

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "contract": {
            "purpose": "forensic separation of good versus false COMPRESSED_REACCEL onsets",
            "base_strategy": "exact frozen V110 selector",
            "base_route": ROUTE_ID,
            "trajectory_lags_completed_d1_rows": list(TRAJECTORY_LAGS),
            "normalized_features_only_for_detector_research": list(NORMALIZED_FEATURES),
            "nominal_price_level_used_as_detector": False,
            "risk_price_used_as_detector": False,
            "future_outcomes_used_only_as_forensic_labels": True,
            "threshold_selected": False,
            "parameter_grid_search": False,
            "calendar_year_used_for_routing": False,
            "execution_authority": False,
        },
        "counts": {
            "epochs": len(records),
            "prior_epochs": len(prior),
            "prior_positive": len(prior_positive),
            "prior_nonpositive": len(prior_nonpositive),
            "mid_2019_2024_nonpositive": len(mid_nonpositive),
        },
        "jan2025_onset": jan2025,
        "profiles": {
            "prior_positive": _profile(prior_positive, keys),
            "prior_nonpositive": _profile(prior_nonpositive, keys),
            "mid_2019_2024_nonpositive": _profile(mid_nonpositive, keys),
        },
        "effect_sizes_prior_positive_vs_nonpositive": effects,
        "ranked_false_onset_separators": ranked,
        "epochs": list(records),
        "note": (
            "V125 is outcome-labelled forensic work only. It may identify candidate causal "
            "onset features, but it deliberately does not turn any discovered feature or "
            "cutoff into a selector. Any gate must be preregistered in a later experiment."
        ),
    }
