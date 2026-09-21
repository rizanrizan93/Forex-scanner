from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Mapping, Sequence

import numpy as np

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_hierarchical_regime_router_v35 import _Asof, build_d1_context
from .research_xau_v134_h3_robustness_v135 import RECENT, START, frozen_h3
from .research_xau_v135_macro_regime_v136 import macro_snapshot

RESEARCH_VERSION = "XAU_V136_STRUCTURAL_REGIME_FORENSIC_V137"
ARTIFACT_CONTRACT = "XAU_V136_STRUCTURAL_REGIME_FORENSIC_V137_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _period(
    trades: Sequence[TournamentTrade], start: datetime, end: datetime
) -> tuple[TournamentTrade, ...]:
    a, b = ensure_utc(start), ensure_utc(end)
    return tuple(t for t in trades if a <= ensure_utc(t.entry_at) < b)


def annotate_structural(
    bars: Sequence[Bar],
    trades: Sequence[TournamentTrade],
    *,
    macro_series,
) -> tuple[dict[str, Any], ...]:
    d1 = build_d1_context(tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp))))
    lookup = _Asof(d1)
    out: list[dict[str, Any]] = []
    for trade in trades:
        row = lookup.row(trade.signal_at)
        if row is None:
            continue
        macro = macro_snapshot(macro_series, trade.signal_at)
        close = float(row.get("close", np.nan))
        ema200 = float(row.get("ema200", np.nan))
        ret60 = float(row.get("ret60", np.nan))
        slope20 = float(row.get("ema200_slope20", np.nan))
        distance = float(row.get("distance_ema200_atr", np.nan))
        out.append(
            {
                "trade": trade,
                "d1_regime": str(row.get("regime")),
                "d1_maturity": str(row.get("maturity")),
                "d1_days_in_regime": int(row.get("days_in_regime") or 0),
                "d1_distance_ema200_atr": distance,
                "d1_ret60": ret60,
                "d1_ema200_slope20": slope20,
                "d1_close_above_ema200": bool(
                    np.isfinite(close) and np.isfinite(ema200) and close > ema200
                ),
                "macro_state": macro.state,
                "macro_real_yield_delta20": macro.real_yield_delta20,
                "macro_usd_return20": macro.usd_return20,
                "macro_policy_2y_delta20": macro.policy_2y_delta20,
                "macro_vix_return20": macro.vix_return20,
            }
        )
    return tuple(out)


def _group_metrics(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    buckets: dict[str, list[TournamentTrade]] = defaultdict(list)
    for row in rows:
        buckets[str(row[key])].append(row["trade"])
    return {k: _metrics(v) for k, v in sorted(buckets.items())}


def _cross_metrics(
    rows: Sequence[Mapping[str, Any]], first: str, second: str
) -> dict[str, Any]:
    buckets: dict[str, list[TournamentTrade]] = defaultdict(list)
    for row in rows:
        key = f"{row[first]}|{row[second]}"
        buckets[key].append(row["trade"])
    return {k: _metrics(v) for k, v in sorted(buckets.items())}


def _feature_summary(rows: Sequence[Mapping[str, Any]], feature: str) -> dict[str, Any]:
    vals = [float(r[feature]) for r in rows if r[feature] is not None and np.isfinite(float(r[feature]))]
    wins = [
        float(r[feature])
        for r in rows
        if r[feature] is not None
        and np.isfinite(float(r[feature]))
        and float(r["trade"].net_r) > 0.0
    ]
    losses = [
        float(r[feature])
        for r in rows
        if r[feature] is not None
        and np.isfinite(float(r[feature]))
        and float(r["trade"].net_r) <= 0.0
    ]
    def pack(x):
        if not x:
            return {"n": 0, "median": None, "mean": None, "q25": None, "q75": None}
        a = np.asarray(x, dtype=float)
        return {
            "n": int(a.size),
            "median": float(np.median(a)),
            "mean": float(np.mean(a)),
            "q25": float(np.quantile(a, 0.25)),
            "q75": float(np.quantile(a, 0.75)),
        }
    return {"all": pack(vals), "wins": pack(wins), "losses": pack(losses)}


def _slice(
    rows: Sequence[Mapping[str, Any]],
    *,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    scoped = tuple(
        row
        for row in rows
        if ensure_utc(start) <= ensure_utc(row["trade"].entry_at) < ensure_utc(end)
    )
    return {
        "metrics": _metrics(tuple(row["trade"] for row in scoped)),
        "count": len(scoped),
        "by_d1_regime": _group_metrics(scoped, "d1_regime"),
        "by_d1_maturity": _group_metrics(scoped, "d1_maturity"),
        "by_macro_state": _group_metrics(scoped, "macro_state"),
        "d1_regime_x_macro": _cross_metrics(scoped, "d1_regime", "macro_state"),
        "d1_maturity_x_macro": _cross_metrics(scoped, "d1_maturity", "macro_state"),
        "feature_summary": {
            feature: _feature_summary(scoped, feature)
            for feature in (
                "d1_days_in_regime",
                "d1_distance_ema200_atr",
                "d1_ret60",
                "d1_ema200_slope20",
                "macro_real_yield_delta20",
                "macro_usd_return20",
                "macro_policy_2y_delta20",
                "macro_vix_return20",
            )
        },
    }


def evaluate_v137(
    bars: Sequence[Bar],
    *,
    macro_series,
    evaluation_end: datetime,
    pip_size: float,
    costs,
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    end = ensure_utc(evaluation_end)
    trades = frozen_h3(rows, evaluation_end=end, pip_size=pip_size, costs=costs)
    annotated = annotate_structural(rows, trades, macro_series=macro_series)

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
            "trade_rule_changes": False,
            "threshold_search": False,
            "calendar_routing": False,
            "future_outcome_routing": False,
            "d1_context_source": "V35 completed D1 bars only",
            "macro_context_source": "V136 prior-day FRED as-of contract",
            "selection_authority": False,
        },
        "full": _slice(annotated, start=START, end=end),
        "pre2025": _slice(annotated, start=START, end=RECENT),
        "recent": _slice(annotated, start=RECENT, end=end),
        "note": (
            "V137 is forensic only. It searches for structural separation between the "
            "weak pre-2025 and strong recent H3 epochs using already-defined V35 D1 "
            "states crossed with the V136 macro states. No new gate is selected here."
        ),
    }
