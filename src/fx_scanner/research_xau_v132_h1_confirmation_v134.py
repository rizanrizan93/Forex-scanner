from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_2025_bootstrap_onset_forensic_v122 import build_v122_feature_frame
from .research_xau_champion_onset_reaccel_v123 import build_reaccel_route_frame
from .research_xau_false_onset_forensic_v125 import annotate_compressed_epochs
from .research_xau_hierarchical_regime_router_v35 import _Asof, build_h1_context
from .research_xau_multihorizon_100usd_v20 import _dedupe, _limit_concurrency, _portfolio_candidates
from .research_xau_qualitative_reaccel_gate_v126 import passes_qualitative_gate
from .research_xau_v110_robustness_v111 import assemble_v110_selector
from .research_xau_causal_m15_regime_v132 import (
    _scenario,
    _triple_contraction,
)

RESEARCH_VERSION = "XAU_V132_H1_CONFIRMATION_V134"
ARTIFACT_CONTRACT = "XAU_V132_H1_CONFIRMATION_V134_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False

START = datetime(2012, 1, 1, tzinfo=timezone.utc)
PRE2025_END = datetime(2025, 1, 1, tzinfo=timezone.utc)
ERA_WINDOWS = (
    ("2012_2018", datetime(2012, 1, 1, tzinfo=timezone.utc), datetime(2019, 1, 1, tzinfo=timezone.utc)),
    ("2019_2024", datetime(2019, 1, 1, tzinfo=timezone.utc), PRE2025_END),
    ("2025_2026YTD", PRE2025_END, None),
)
CANDIDATES = (
    "H0_C2_BASELINE",
    "H1_C2_H1_SOFT",
    "H2_C2_H1_NORMAL",
    "H3_C2_H1_STRICT",
)


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _period(trades: Sequence[TournamentTrade], start, end) -> tuple[TournamentTrade, ...]:
    a = ensure_utc(start)
    b = ensure_utc(end)
    return tuple(t for t in trades if a <= ensure_utc(t.entry_at) < b)


def _is_c2_epoch(rec: Mapping[str, Any]) -> bool:
    return (
        passes_qualitative_gate(rec)
        and str(rec.get("side", "")).upper() == "LONG"
        and _triple_contraction(rec)
    )


def _epoch_windows(records: Sequence[Mapping[str, Any]], *, evaluation_end) -> tuple[tuple[Any, Any], ...]:
    import pandas as pd

    end = ensure_utc(evaluation_end)
    out = []
    for rec in records:
        if not _is_c2_epoch(rec):
            continue
        a = ensure_utc(pd.Timestamp(rec["start"]).to_pydatetime())
        b = end if rec.get("end_exclusive") is None else ensure_utc(
            pd.Timestamp(rec["end_exclusive"]).to_pydatetime()
        )
        out.append((a, b))
    return tuple(out)


def _route_c2(
    trades: Sequence[TournamentTrade],
    records: Sequence[Mapping[str, Any]],
    *,
    evaluation_end,
) -> tuple[TournamentTrade, ...]:
    windows = _epoch_windows(records, evaluation_end=evaluation_end)
    return tuple(
        t
        for t in sorted(trades, key=lambda x: ensure_utc(x.entry_at))
        if str(t.direction).upper() == "LONG"
        and any(a <= ensure_utc(t.entry_at) < b for a, b in windows)
    )


def _h1_permission(row: Mapping[str, Any] | None, *, side: str, mode: str) -> bool:
    if mode == "BASELINE":
        return True
    if row is None:
        return False

    direction = str(side).upper()
    long_side = direction == "LONG"
    if direction not in {"LONG", "SHORT"}:
        return False

    def f(key: str) -> float:
        try:
            return float(row.get(key))
        except (TypeError, ValueError):
            return float("nan")

    close, ema20, ema50, ema200 = (f("close"), f("ema20"), f("ema50"), f("ema200"))
    if not all(isfinite(x) for x in (close, ema20, ema50, ema200)):
        return False

    soft = close > ema200 if long_side else close < ema200
    if mode == "SOFT":
        return soft

    normal = soft and (ema20 > ema50 if long_side else ema20 < ema50)
    if mode == "NORMAL":
        return normal

    if mode != "STRICT":
        raise ValueError(f"V134_UNKNOWN_H1_MODE:{mode}")

    slope5, adx, plus_di, minus_di = (
        f("ema20_slope5"),
        f("adx14"),
        f("plus_di14"),
        f("minus_di14"),
    )
    if not all(isfinite(x) for x in (slope5, adx, plus_di, minus_di)):
        return False
    return bool(
        normal
        and adx >= 15.0
        and (
            (
                long_side
                and ema50 > ema200
                and slope5 > 0.0
                and plus_di > minus_di
            )
            or (
                (not long_side)
                and ema50 < ema200
                and slope5 < 0.0
                and minus_di > plus_di
            )
        )
    )


def _apply_h1(
    trades: Sequence[TournamentTrade],
    *,
    h1_context,
    mode: str,
) -> tuple[TournamentTrade, ...]:
    lookup = _Asof(h1_context)
    return tuple(
        t
        for t in trades
        if _h1_permission(lookup.row(t.signal_at), side=t.direction, mode=mode)
    )


def _summary(
    trades: Sequence[TournamentTrade],
    *,
    end,
    broker_spec,
    leverage_tiers,
) -> dict[str, Any]:
    full = _period(trades, START, end)
    pre = _period(trades, START, PRE2025_END)
    eras: dict[str, Any] = {}
    for label, a, b in ERA_WINDOWS:
        finish = end if b is None else b
        vals = _period(trades, a, finish)
        eras[label] = {
            "metrics": _metrics(vals),
            "scenarios": _scenario(vals, broker_spec=broker_spec, leverage_tiers=leverage_tiers),
        }
    return {
        "full_metrics": _metrics(full),
        "full_scenarios": _scenario(full, broker_spec=broker_spec, leverage_tiers=leverage_tiers),
        "pre2025_metrics": _metrics(pre),
        "eras": eras,
    }


def evaluate_v134(
    rows: Sequence[Bar],
    *,
    evaluation_end,
    pip_size: float,
    costs,
    broker_spec,
    leverage_tiers,
) -> dict[str, Any]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    end = ensure_utc(evaluation_end)

    candidates = _portfolio_candidates(
        bars, base_costs=costs, stressed_costs=costs, pip_size=pip_size
    )
    raw_l12 = tuple(candidates["M15_L12_ONLY"]["stress"])
    raw_l20 = tuple(candidates["M15_L20_ONLY"]["stress"])
    raw_combined = _limit_concurrency(_dedupe((*raw_l12, *raw_l20)))

    frame = build_v122_feature_frame(bars)
    _, epoch_defs = build_reaccel_route_frame(frame, route_id="COMPRESSED_REACCEL")
    _, selector_all, _ = assemble_v110_selector(
        bars, costs=costs, pip_size=pip_size, evaluation_end=end
    )
    records = annotate_compressed_epochs(frame, epoch_defs, selector_all)

    c2 = _route_c2(raw_combined, records, evaluation_end=end)
    h1 = build_h1_context(bars)
    routed = {
        "H0_C2_BASELINE": c2,
        "H1_C2_H1_SOFT": _apply_h1(c2, h1_context=h1, mode="SOFT"),
        "H2_C2_H1_NORMAL": _apply_h1(c2, h1_context=h1, mode="NORMAL"),
        "H3_C2_H1_STRICT": _apply_h1(c2, h1_context=h1, mode="STRICT"),
    }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "contract": {
            "parent": "V132 C2 exact frozen V126 LONG + 20D triple contraction",
            "h1_rules_source": "frozen V35 completed-H1 definitions; predates V133 outcome",
            "h1_soft": "close on directional side of H1 EMA200",
            "h1_normal": "SOFT plus H1 EMA20/EMA50 directional alignment",
            "h1_strict": "NORMAL plus H1 EMA50/EMA200 stack, EMA20 slope5, ADX>=15, DI alignment",
            "completed_h1_only": True,
            "context_lookup": "as-of trade.signal_at",
            "candidate_count": len(CANDIDATES),
            "threshold_grid_search": False,
            "new_threshold_from_v133": False,
            "calendar_routing": False,
            "future_outcome_routing": False,
            "execution_authority": False,
        },
        "acceptance_criteria": {
            "full_min_trades": 100,
            "full_min_pf": 1.15,
            "full_min_expectancy_r": 0.05,
            "full_max_drawdown_r": 20.0,
            "pre2025_min_trades": 50,
            "pre2025_min_expectancy_r": 0.0,
            "active_pre2025_era_min_expectancy_r": 0.0,
            "recent_min_trades": 100,
            "recent_min_pf": 1.30,
            "recent_min_expectancy_r": 0.10,
            "live100_recent_min_opened": 30,
            "live100_recent_min_pf": 1.20,
            "live100_recent_min_expectancy_r_strictly_gt": 0.0,
            "live100_recent_min_ending_balance_strictly_gt": 100.0,
            "zero_trade_era_semantics": "NO_EXPOSURE; not a negative expectancy observation",
        },
        "candidates": {
            cid: _summary(
                trades,
                end=end,
                broker_spec=broker_spec,
                leverage_tiers=leverage_tiers,
            )
            for cid, trades in routed.items()
        },
        "note": (
            "V134 is a preregistered falsification of an independent H1 tactical layer. "
            "Passing historical criteria is not promotion evidence and cannot enable LIVE."
        ),
    }
