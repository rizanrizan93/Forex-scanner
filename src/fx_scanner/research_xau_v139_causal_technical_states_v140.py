from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import datetime
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_v134_h3_robustness_v135 import (
    RECENT,
    START,
    frozen_h3,
    frozen_h3_one_h1_bar_lag,
)
from .research_xau_v138_gold_driver_attribution_v139 import build_daily_panel

RESEARCH_VERSION = "XAU_V139_CAUSAL_TECHNICAL_STATES_V140"
ARTIFACT_CONTRACT = "XAU_V139_CAUSAL_TECHNICAL_STATES_V140_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True


class DailyAsof:
    def __init__(self, rows: Sequence[Mapping[str, Any]]):
        ordered = tuple(sorted(rows, key=lambda x: ensure_utc(x["signal_at"])))
        self.rows = ordered
        self.times = tuple(ensure_utc(x["signal_at"]) for x in ordered)

    def row(self, signal_at: datetime) -> Mapping[str, Any] | None:
        i = bisect_right(self.times, ensure_utc(signal_at)) - 1
        return None if i < 0 else self.rows[i]


def causal_state(row: Mapping[str, Any] | None) -> str:
    if row is None:
        return "UNKNOWN"
    opp = str(row.get("opportunity_cost"))
    momentum = str(row.get("momentum_state"))
    if opp == "SUPPORTIVE":
        return "TAILWIND"
    if opp == "MIXED":
        return "MIXED"
    if opp == "HOSTILE" and momentum == "GOLD_MOMENTUM_UP":
        return "RESILIENT_HEADWIND"
    if opp == "HOSTILE" and momentum == "GOLD_MOMENTUM_DOWN":
        return "FRAGILE_HEADWIND"
    return "UNKNOWN"


def annotate_trades(
    trades: Sequence[TournamentTrade],
    *,
    daily_panel: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    lookup = DailyAsof(daily_panel)
    out = []
    for trade in trades:
        row = lookup.row(trade.signal_at)
        out.append(
            {
                "trade": trade,
                "state": causal_state(row),
                "opportunity_cost": None if row is None else row.get("opportunity_cost"),
                "momentum_state": None if row is None else row.get("momentum_state"),
                "risk_state": None if row is None else row.get("risk_state"),
                "inflation_state": None if row is None else row.get("inflation_state"),
                "d1_regime": None if row is None else row.get("d1_regime"),
                "d1_maturity": None if row is None else row.get("d1_maturity"),
            }
        )
    return tuple(out)


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _period(
    rows: Sequence[Mapping[str, Any]], start: datetime, end: datetime
) -> tuple[Mapping[str, Any], ...]:
    a, b = ensure_utc(start), ensure_utc(end)
    return tuple(
        r for r in rows if a <= ensure_utc(r["trade"].entry_at) < b
    )


def _groups(
    rows: Sequence[Mapping[str, Any]], keys: Sequence[str]
) -> dict[str, Any]:
    buckets: dict[str, list[TournamentTrade]] = defaultdict(list)
    for row in rows:
        name = "|".join(str(row.get(k)) for k in keys)
        buckets[name].append(row["trade"])
    return {k: _metrics(v) for k, v in sorted(buckets.items())}


def _slice(
    rows: Sequence[Mapping[str, Any]], *, start: datetime, end: datetime
) -> dict[str, Any]:
    scoped = _period(rows, start, end)
    return {
        "count": len(scoped),
        "metrics": _metrics(tuple(r["trade"] for r in scoped)),
        "by_state": _groups(scoped, ("state",)),
        "state_x_risk": _groups(scoped, ("state", "risk_state")),
        "state_x_d1": _groups(scoped, ("state", "d1_regime")),
        "state_x_inflation": _groups(scoped, ("state", "inflation_state")),
    }


def _pack(
    trades: Sequence[TournamentTrade],
    *,
    daily_panel: Sequence[Mapping[str, Any]],
    end: datetime,
) -> dict[str, Any]:
    annotated = annotate_trades(trades, daily_panel=daily_panel)
    return {
        "full": _slice(annotated, start=START, end=end),
        "pre2025": _slice(annotated, start=START, end=RECENT),
        "recent": _slice(annotated, start=RECENT, end=end),
    }


def evaluate_v140(
    bars: Sequence[Bar],
    *,
    macro_series,
    evaluation_end: datetime,
    pip_size: float,
    baseline_costs,
    super_stress_costs,
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    end = ensure_utc(evaluation_end)
    panel = build_daily_panel(rows, macro_series=macro_series)

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
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "live_execution_enabled": False,
        "contract": {
            "candidate": "V134_H3_C2_H1_STRICT_FROZEN",
            "state_definitions": {
                "TAILWIND": "opportunity cost SUPPORTIVE",
                "MIXED": "opportunity cost MIXED",
                "RESILIENT_HEADWIND": "opportunity cost HOSTILE while completed-D1 gold momentum20 remains UP",
                "FRAGILE_HEADWIND": "opportunity cost HOSTILE while completed-D1 gold momentum20 is DOWN",
            },
            "opportunity_cost_definition": "20-observation 10Y real-yield change plus broad-USD return sign from V139",
            "momentum_definition": "completed-D1 XAU 20-session return sign from V139",
            "threshold_search": False,
            "calendar_routing": False,
            "future_outcome_routing": False,
            "trade_rule_changes": False,
            "selection_authority": False,
            "historical_result_is_not_promotion": True,
        },
        "baseline": _pack(baseline, daily_panel=panel, end=end),
        "super_stress": _pack(super_stress, daily_panel=panel, end=end),
        "one_h1_bar_lag": _pack(lagged, daily_panel=panel, end=end),
        "note": (
            "V140 tests whether macro tailwind versus demonstrated price resilience "
            "against macro headwind explains H3 trade quality. It does not select or "
            "apply a gate."
        ),
    }
