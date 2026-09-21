from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_2025_bootstrap_onset_forensic_v122 import build_v122_feature_frame
from .research_xau_champion_onset_reaccel_v123 import _cash, build_reaccel_route_frame
from .research_xau_false_onset_forensic_v125 import annotate_compressed_epochs
from .research_xau_qualitative_reaccel_gate_v126 import MEDIAN, passes_qualitative_gate
from .research_xau_v110_robustness_v111 import assemble_v110_selector

RESEARCH_VERSION = "XAU_V126_ROBUSTNESS_V127"
ARTIFACT_CONTRACT = "XAU_V126_ROBUSTNESS_V127_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False

RULES = (
    "ATR_LEVEL",
    "ATR_RATIO_LEVEL",
    "ATR_20D_COMPRESSION",
    "ATR_RATIO_20D_COMPRESSION",
    "EMA200_SIDE",
    "TREND_5D_REACCEL",
)

START_DATES = (
    ("2012", datetime(2012, 1, 1, tzinfo=timezone.utc)),
    ("2015", datetime(2015, 1, 1, tzinfo=timezone.utc)),
    ("2019", datetime(2019, 1, 1, tzinfo=timezone.utc)),
    ("2022", datetime(2022, 1, 1, tzinfo=timezone.utc)),
    ("2025_JAN", datetime(2025, 1, 1, tzinfo=timezone.utc)),
    ("2025_APR", datetime(2025, 4, 1, tzinfo=timezone.utc)),
    ("2025_JUL", datetime(2025, 7, 1, tzinfo=timezone.utc)),
    ("2026_JAN", datetime(2026, 1, 1, tzinfo=timezone.utc)),
)


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _passes(record: Mapping[str, Any], *, omit: str | None = None) -> bool:
    side = str(record.get("side") or "").upper()
    if side not in {"LONG", "SHORT"}:
        return False
    required = (
        "pct_atr14_pct",
        "pct_atr_ratio_252",
        "d20_pct_atr14_pct",
        "d20_pct_atr_ratio_252",
        "pct_ema200_distance_atr",
        "d5_pct_trend60_atr",
    )
    if any(record.get(k) is None for k in required):
        return False

    checks = {
        "ATR_LEVEL": float(record["pct_atr14_pct"]) <= MEDIAN,
        "ATR_RATIO_LEVEL": float(record["pct_atr_ratio_252"]) <= MEDIAN,
        "ATR_20D_COMPRESSION": float(record["d20_pct_atr14_pct"]) < 0.0,
        "ATR_RATIO_20D_COMPRESSION": float(record["d20_pct_atr_ratio_252"]) < 0.0,
        "EMA200_SIDE": (
            float(record["pct_ema200_distance_atr"]) >= MEDIAN
            if side == "LONG"
            else float(record["pct_ema200_distance_atr"]) <= MEDIAN
        ),
        "TREND_5D_REACCEL": (
            float(record["d5_pct_trend60_atr"]) > 0.0
            if side == "LONG"
            else float(record["d5_pct_trend60_atr"]) < 0.0
        ),
    }
    return all(v for k, v in checks.items() if k != omit)


def _route(
    trades: Sequence[TournamentTrade],
    epochs: Sequence[Mapping[str, Any]],
    *,
    end,
    predicate: Callable[[Mapping[str, Any]], bool],
) -> tuple[TournamentTrade, ...]:
    windows = []
    finish = ensure_utc(end)
    for rec in epochs:
        if not predicate(rec):
            continue
        a = ensure_utc(pd.Timestamp(rec["start"]).to_pydatetime())
        b = finish if rec.get("end_exclusive") is None else ensure_utc(pd.Timestamp(rec["end_exclusive"]).to_pydatetime())
        windows.append((a, b, str(rec["side"]).upper()))

    out = []
    for trade in sorted(trades, key=lambda t: ensure_utc(t.entry_at)):
        at = ensure_utc(trade.entry_at)
        side = str(trade.direction).upper()
        if any(a <= at < b and side == s for a, b, s in windows):
            out.append(trade)
    return tuple(out)


def _period(trades: Sequence[TournamentTrade], start, end) -> tuple[TournamentTrade, ...]:
    a = ensure_utc(start)
    b = ensure_utc(end)
    return tuple(t for t in trades if a <= ensure_utc(t.entry_at) < b)


def evaluate_v127(
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

    frame = build_v122_feature_frame(bars)
    _, epoch_defs = build_reaccel_route_frame(frame, route_id="COMPRESSED_REACCEL")
    _, selector_all, _ = assemble_v110_selector(
        bars,
        costs=costs,
        pip_size=pip_size,
        evaluation_end=end,
    )
    selector = tuple(t for t in selector_all if ensure_utc(t.entry_at) < end)
    epochs = annotate_compressed_epochs(frame, epoch_defs, selector)

    # Contract check: V127's frozen rule implementation must match V126 exactly.
    for rec in epochs:
        if _passes(rec) != passes_qualitative_gate(rec):
            raise AssertionError("V127_V126_GATE_PARITY_FAILED")

    base = _route(selector, epochs, end=end, predicate=passes_qualitative_gate)
    base_metrics = _metrics(base)

    start_sensitivity = {}
    for label, start in START_DATES:
        vals = _period(base, start, end)
        start_sensitivity[label] = {
            "metrics": _metrics(vals),
            "fresh_100_cash": _cash(
                base,
                bars=bars,
                start=start,
                end=end,
                broker_spec=broker_spec,
                leverage_tiers=leverage_tiers,
            ),
        }

    annual = {}
    for year in range(2012, end.year + 1):
        a = datetime(year, 1, 1, tzinfo=timezone.utc)
        b = min(end, datetime(year + 1, 1, 1, tzinfo=timezone.utc))
        annual[str(year)] = _metrics(_period(base, a, b))

    ablations = {}
    for rule in RULES:
        routed = _route(selector, epochs, end=end, predicate=lambda r, rule=rule: _passes(r, omit=rule))
        metrics = _metrics(routed)
        cash = _cash(
            routed,
            bars=bars,
            start=datetime(2012, 1, 1, tzinfo=timezone.utc),
            end=end,
            broker_spec=broker_spec,
            leverage_tiers=leverage_tiers,
        )
        ablations[rule] = {
            "metrics": metrics,
            "continuous_100_cash": cash,
            "eligible_epochs": sum(_passes(r, omit=rule) for r in epochs),
        }

    base_cash = _cash(
        base,
        bars=bars,
        start=datetime(2012, 1, 1, tzinfo=timezone.utc),
        end=end,
        broker_spec=broker_spec,
        leverage_tiers=leverage_tiers,
    )

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "contract": {
            "gate": "exact frozen V126 MEDIAN_COMPRESSION_REACCEL",
            "gate_changed": False,
            "rules": list(RULES),
            "start_dates_preregistered": [label for label, _ in START_DATES],
            "ablation_only": True,
            "ablation_not_used_for_rule_selection": True,
            "parameter_grid_search": False,
            "calendar_year_used_for_routing": False,
            "execution_authority": False,
        },
        "base": {
            "metrics": base_metrics,
            "continuous_100_cash": base_cash,
            "eligible_epochs": sum(passes_qualitative_gate(r) for r in epochs),
        },
        "start_sensitivity": start_sensitivity,
        "annual_metrics": annual,
        "leave_one_rule_out": ablations,
        "note": (
            "V127 freezes V126 and tests path/start sensitivity plus rule dependence. "
            "It does not select an ablation winner or alter the gate."
        ),
    }
