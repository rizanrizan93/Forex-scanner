from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_causal_m15_regime_v132 import _scenario
from .research_xau_v134_h3_robustness_v135 import (
    START,
    RECENT,
    frozen_h3,
    frozen_h3_one_h1_bar_lag,
)

RESEARCH_VERSION = "XAU_V135_MACRO_REGIME_V136"
ARTIFACT_CONTRACT = "XAU_V135_MACRO_REGIME_V136_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False

LOOKBACK_OBSERVATIONS = 20

FRED_SERIES = {
    "real_yield_10y": "DFII10",
    "usd_broad": "DTWEXBGS",
    "policy_2y": "DGS2",
    "vix": "VIXCLS",
}


@dataclass(frozen=True)
class MacroSnapshot:
    signal_date: date
    state: str
    real_yield_asof: date | None
    real_yield_delta20: float | None
    usd_asof: date | None
    usd_return20: float | None
    policy_2y_asof: date | None
    policy_2y_delta20: float | None
    vix_asof: date | None
    vix_return20: float | None

    @property
    def covered(self) -> bool:
        return self.state != "UNKNOWN"

    @property
    def non_hostile(self) -> bool:
        return self.state in {"SUPPORTIVE", "MIXED"}


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _period(
    trades: Sequence[TournamentTrade], start: datetime, end: datetime
) -> tuple[TournamentTrade, ...]:
    a, b = ensure_utc(start), ensure_utc(end)
    return tuple(t for t in trades if a <= ensure_utc(t.entry_at) < b)


def _clean_series(values: Mapping[date, float]) -> tuple[tuple[date, ...], tuple[float, ...]]:
    rows = sorted((d, float(v)) for d, v in values.items())
    return tuple(d for d, _ in rows), tuple(v for _, v in rows)


def _asof_change(
    values: Mapping[date, float],
    signal_date: date,
    *,
    relative: bool,
    lookback: int = LOOKBACK_OBSERVATIONS,
) -> tuple[date | None, float | None]:
    """
    Strict point-in-time rule: same-day macro observations are never used.
    The latest observation must be dated strictly before the signal date.
    """
    dates, vals = _clean_series(values)
    idx = bisect_left(dates, signal_date) - 1
    if idx < lookback or idx < 0:
        return None, None
    now = vals[idx]
    prior = vals[idx - lookback]
    if relative:
        if prior == 0.0:
            return dates[idx], None
        return dates[idx], (now / prior) - 1.0
    return dates[idx], now - prior


def macro_snapshot(
    series: Mapping[str, Mapping[date, float]], signal_at: datetime
) -> MacroSnapshot:
    d = ensure_utc(signal_at).date()

    ry_date, ry = _asof_change(series["real_yield_10y"], d, relative=False)
    usd_date, usd = _asof_change(series["usd_broad"], d, relative=True)
    p2_date, p2 = _asof_change(series["policy_2y"], d, relative=False)
    vix_date, vix = _asof_change(series["vix"], d, relative=True)

    if ry is None or usd is None:
        state = "UNKNOWN"
    elif ry > 0.0 and usd > 0.0:
        state = "HOSTILE"
    elif ry <= 0.0 and usd <= 0.0:
        state = "SUPPORTIVE"
    else:
        state = "MIXED"

    return MacroSnapshot(
        signal_date=d,
        state=state,
        real_yield_asof=ry_date,
        real_yield_delta20=ry,
        usd_asof=usd_date,
        usd_return20=usd,
        policy_2y_asof=p2_date,
        policy_2y_delta20=p2,
        vix_asof=vix_date,
        vix_return20=vix,
    )


def annotate_macro(
    trades: Sequence[TournamentTrade],
    series: Mapping[str, Mapping[date, float]],
) -> tuple[tuple[TournamentTrade, MacroSnapshot], ...]:
    return tuple((t, macro_snapshot(series, t.signal_at)) for t in trades)


def _macro_gate(
    rows: Sequence[tuple[TournamentTrade, MacroSnapshot]],
) -> tuple[TournamentTrade, ...]:
    """
    Frozen V136 candidate:
    keep the exact H3 trade unless both 10Y real yield and broad USD have
    risen over their prior 20 available observations. UNKNOWN fails closed.
    """
    return tuple(t for t, snap in rows if snap.non_hostile)


def _state_metrics(
    rows: Sequence[tuple[TournamentTrade, MacroSnapshot]],
    *,
    start: datetime,
    end: datetime,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for state in ("SUPPORTIVE", "MIXED", "HOSTILE", "UNKNOWN"):
        trades = tuple(
            t
            for t, snap in rows
            if snap.state == state and ensure_utc(start) <= ensure_utc(t.entry_at) < ensure_utc(end)
        )
        out[state] = _metrics(trades)
    return out


def _macro_diagnostics(
    rows: Sequence[tuple[TournamentTrade, MacroSnapshot]],
    *,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    scoped = tuple(
        (t, s)
        for t, s in rows
        if ensure_utc(start) <= ensure_utc(t.entry_at) < ensure_utc(end)
    )
    covered = sum(1 for _, s in scoped if s.covered)
    supportive = sum(1 for _, s in scoped if s.state == "SUPPORTIVE")
    mixed = sum(1 for _, s in scoped if s.state == "MIXED")
    hostile = sum(1 for _, s in scoped if s.state == "HOSTILE")
    unknown = sum(1 for _, s in scoped if s.state == "UNKNOWN")
    return {
        "trades": len(scoped),
        "covered": covered,
        "coverage": (covered / len(scoped)) if scoped else None,
        "supportive": supportive,
        "mixed": mixed,
        "hostile": hostile,
        "unknown": unknown,
        "state_metrics": _state_metrics(rows, start=start, end=end),
    }


def _pack(
    trades: Sequence[TournamentTrade],
    *,
    series: Mapping[str, Mapping[date, float]],
    end: datetime,
    broker_spec,
    leverage_tiers,
) -> dict[str, Any]:
    vals = _period(trades, START, end)
    rows = annotate_macro(vals, series)
    gated = _macro_gate(rows)
    pre = _period(gated, START, RECENT)
    recent = _period(gated, RECENT, end)
    return {
        "all_metrics": _metrics(vals),
        "gated_metrics": _metrics(gated),
        "gated_pre2025_metrics": _metrics(pre),
        "gated_recent_metrics": _metrics(recent),
        "macro_full": _macro_diagnostics(rows, start=START, end=end),
        "macro_pre2025": _macro_diagnostics(rows, start=START, end=RECENT),
        "macro_recent": _macro_diagnostics(rows, start=RECENT, end=end),
        "retention": (len(gated) / len(vals)) if vals else None,
        "gated_full_live100": _scenario(
            gated, broker_spec=broker_spec, leverage_tiers=leverage_tiers
        )["LIVE_100_1_100_CAP50"],
        "gated_recent_live100": _scenario(
            recent, broker_spec=broker_spec, leverage_tiers=leverage_tiers
        )["LIVE_100_1_100_CAP50"],
    }


def evaluate_v136(
    bars: Sequence[Bar],
    *,
    macro_series: Mapping[str, Mapping[date, float]],
    evaluation_end: datetime,
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
            "parent_candidate": "V134_H3_C2_H1_STRICT_FROZEN",
            "v135_result": "FAILED_ROBUSTNESS",
            "macro_gate_candidate": "NON_HOSTILE_20OBS",
            "macro_gate_rule": (
                "exclude exact H3 trade only when BOTH prior-day 10Y real-yield "
                "20-observation delta > 0 and broad-USD 20-observation return > 0"
            ),
            "same_day_macro_allowed": False,
            "unknown_macro_action": "EXCLUDE_FAIL_CLOSED",
            "lookback_observations": LOOKBACK_OBSERVATIONS,
            "threshold_search": False,
            "calendar_routing": False,
            "future_outcome_routing": False,
            "policy_2y_role": "DIAGNOSTIC_ONLY",
            "vix_role": "DIAGNOSTIC_ONLY",
            "execution_authority": False,
        },
        "acceptance_criteria": {
            "macro_coverage_min": 0.95,
            "gated_retention_min": 0.50,
            "baseline_full_expectancy_strictly_gt": 0.0,
            "baseline_pre2025_expectancy_nonnegative_if_exposed": True,
            "baseline_recent_expectancy_min": 0.10,
            "super_stress_full_expectancy_strictly_gt": 0.0,
            "super_stress_pre2025_expectancy_nonnegative_if_exposed": True,
            "super_stress_recent_expectancy_min": 0.08,
            "one_h1_lag_full_expectancy_strictly_gt": 0.0,
            "one_h1_lag_pre2025_expectancy_nonnegative_if_exposed": True,
            "one_h1_lag_recent_expectancy_min": 0.08,
            "super_stress_full_live100_ending_strictly_gt": 100.0,
            "one_h1_lag_full_live100_ending_strictly_gt": 100.0,
            "historical_pass_is_not_promotion": True,
        },
        "fred_series": dict(FRED_SERIES),
        "baseline": _pack(
            baseline,
            series=macro_series,
            end=end,
            broker_spec=broker_spec,
            leverage_tiers=leverage_tiers,
        ),
        "super_stress": _pack(
            super_stress,
            series=macro_series,
            end=end,
            broker_spec=broker_spec,
            leverage_tiers=leverage_tiers,
        ),
        "one_h1_bar_lag": _pack(
            lagged,
            series=macro_series,
            end=end,
            broker_spec=broker_spec,
            leverage_tiers=leverage_tiers,
        ),
        "note": (
            "V136 preregisters one macro permission hypothesis. Real yield and USD "
            "define the gate; 2Y yield and VIX are retained only as diagnostics. "
            "No result-driven threshold or era selection is allowed in this study."
        ),
    }
