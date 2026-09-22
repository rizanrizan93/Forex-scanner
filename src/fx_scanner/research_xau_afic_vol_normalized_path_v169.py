from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Sequence

import numpy as np

from .models import Bar, ensure_utc
from .research_xau_afic_h4_map_selector_v161 import WINDOWS
from .research_xau_afic_independent_path_confirm_v166 import (
    CANDIDATE_RULE,
    CONTROL_RULE,
    RULES,
    build_independent_rule_path,
)
from .research_xau_m15_continuation_tournament import _indicator_series

RESEARCH_VERSION = "XAU_AFIC_VOL_NORMALIZED_PATH_V169"
ARTIFACT_CONTRACT = "XAU_AFIC_VOL_NORMALIZED_PATH_V169_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

PRIMARY_BARRIER_ATR = 1.0
SENSITIVITY_BARRIERS_ATR = (0.5, 1.5)
HORIZON_M15 = 32  # 8h, frozen to V166 second-leg horizon
RETURN_OFFSETS = (4, 16, 32)  # 1h, 4h, 8h


def _quantiles(values: Sequence[float]) -> dict[str, float] | None:
    if not values:
        return None
    arr = np.asarray(values, dtype=float)
    return {
        "q10": float(np.quantile(arr, 0.10)),
        "q25": float(np.quantile(arr, 0.25)),
        "q50": float(np.quantile(arr, 0.50)),
        "q75": float(np.quantile(arr, 0.75)),
        "q90": float(np.quantile(arr, 0.90)),
    }


def _barrier_outcome(
    rows: Sequence[Bar],
    *,
    anchor_index: int,
    direction: str,
    atr: float,
    barrier_atr: float,
    horizon: int = HORIZON_M15,
) -> dict[str, Any] | None:
    if direction not in {"LONG", "SHORT"}:
        raise ValueError(f"V169_DIRECTION_INVALID:{direction}")
    if not isfinite(float(atr)) or float(atr) <= 0:
        return None
    if anchor_index < 0 or anchor_index + horizon >= len(rows):
        return None

    anchor = float(rows[anchor_index].close)
    sign = 1.0 if direction == "LONG" else -1.0
    favorable_level = anchor + sign * float(barrier_atr) * float(atr)
    adverse_level = anchor - sign * float(barrier_atr) * float(atr)

    favorable_bar = None
    adverse_bar = None
    mfe = 0.0
    mae = 0.0

    for offset in range(1, horizon + 1):
        row = rows[anchor_index + offset]
        if direction == "LONG":
            favorable_hit = float(row.high) >= favorable_level
            adverse_hit = float(row.low) <= adverse_level
            favorable_exc = (float(row.high) - anchor) / atr
            adverse_exc = (anchor - float(row.low)) / atr
        else:
            favorable_hit = float(row.low) <= favorable_level
            adverse_hit = float(row.high) >= adverse_level
            favorable_exc = (anchor - float(row.low)) / atr
            adverse_exc = (float(row.high) - anchor) / atr

        mfe = max(mfe, favorable_exc)
        mae = max(mae, adverse_exc)
        if favorable_bar is None and favorable_hit:
            favorable_bar = offset
        if adverse_bar is None and adverse_hit:
            adverse_bar = offset
        if favorable_bar is not None and adverse_bar is not None:
            break

    if favorable_bar is None and adverse_bar is None:
        first = "NEITHER"
    elif favorable_bar is not None and adverse_bar is not None and favorable_bar == adverse_bar:
        first = "AMBIGUOUS"
    elif adverse_bar is None or (
        favorable_bar is not None and favorable_bar < adverse_bar
    ):
        first = "FAVORABLE"
    else:
        first = "ADVERSE"

    returns = {}
    for offset in RETURN_OFFSETS:
        if anchor_index + offset >= len(rows):
            continue
        raw = (float(rows[anchor_index + offset].close) - anchor) / atr
        returns[f"{int(offset * 15 / 60)}h"] = float(sign * raw)

    return {
        "first": first,
        "favorable_bar": favorable_bar,
        "adverse_bar": adverse_bar,
        "mfe_atr": float(max(0.0, mfe)),
        "mae_atr": float(max(0.0, mae)),
        "directional_return_atr": returns,
    }


def _cohort_rows(
    rows: Sequence[Bar],
    scenarios: Sequence[Any],
    atr_values: Sequence[float | None],
    *,
    anchor_kind: str,
    barrier_atr: float,
) -> tuple[dict[str, Any], ...]:
    output = []
    for scenario in scenarios:
        if anchor_kind == "TOUCH":
            anchor_index = scenario.first_touch_index
        elif anchor_kind == "CONFIRM":
            anchor_index = scenario.confirm_index
        else:
            raise ValueError(f"V169_ANCHOR_KIND_INVALID:{anchor_kind}")
        if anchor_index is None:
            continue
        i = int(anchor_index)
        if i >= len(atr_values):
            continue
        atr = atr_values[i]
        if atr is None:
            continue
        outcome = _barrier_outcome(
            rows,
            anchor_index=i,
            direction=str(scenario.continuation_direction),
            atr=float(atr),
            barrier_atr=float(barrier_atr),
        )
        if outcome is None:
            continue
        output.append(
            {
                "map_at": ensure_utc(scenario.map_at),
                "direction": str(scenario.continuation_direction),
                "anchor_index": i,
                "atr": float(atr),
                **outcome,
            }
        )
    return tuple(output)


def _summarize_cohort(values: Sequence[dict[str, Any]]) -> dict[str, Any]:
    rows = tuple(values)
    counts = {
        name: sum(str(row["first"]) == name for row in rows)
        for name in ("FAVORABLE", "ADVERSE", "NEITHER", "AMBIGUOUS")
    }
    resolved = counts["FAVORABLE"] + counts["ADVERSE"]
    returns = {}
    for horizon in ("1h", "4h", "8h"):
        returns[horizon] = _quantiles(
            [
                float(row["directional_return_atr"][horizon])
                for row in rows
                if horizon in row["directional_return_atr"]
            ]
        )
    favorable_times = [
        int(row["favorable_bar"])
        for row in rows
        if row.get("favorable_bar") is not None
    ]
    adverse_times = [
        int(row["adverse_bar"])
        for row in rows
        if row.get("adverse_bar") is not None
    ]
    return {
        "n": len(rows),
        "first_hit_counts": counts,
        "favorable_first_rate": None
        if not rows
        else counts["FAVORABLE"] / len(rows),
        "adverse_first_rate": None
        if not rows
        else counts["ADVERSE"] / len(rows),
        "favorable_share_of_directionally_resolved": None
        if resolved == 0
        else counts["FAVORABLE"] / resolved,
        "mfe_atr": _quantiles([float(row["mfe_atr"]) for row in rows]),
        "mae_atr": _quantiles([float(row["mae_atr"]) for row in rows]),
        "directional_return_atr": returns,
        "favorable_first_time_bars": _quantiles(favorable_times),
        "adverse_first_time_bars": _quantiles(adverse_times),
    }


def _window(
    rows: Sequence[Bar],
    scenarios: Sequence[Any],
    atr_values: Sequence[float | None],
    *,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    start = ensure_utc(start)
    end = ensure_utc(end)
    ss = tuple(
        scenario
        for scenario in scenarios
        if start <= ensure_utc(scenario.map_at) < end
    )
    touched = tuple(s for s in ss if s.first_touch_index is not None)
    confirmed = tuple(s for s in ss if s.confirm_index is not None)

    barriers = {}
    for barrier in (PRIMARY_BARRIER_ATR, *SENSITIVITY_BARRIERS_ATR):
        touch_rows = _cohort_rows(
            rows,
            touched,
            atr_values,
            anchor_kind="TOUCH",
            barrier_atr=float(barrier),
        )
        confirm_rows = _cohort_rows(
            rows,
            confirmed,
            atr_values,
            anchor_kind="CONFIRM",
            barrier_atr=float(barrier),
        )
        touch_summary = _summarize_cohort(touch_rows)
        confirm_summary = _summarize_cohort(confirm_rows)
        lift = None
        if (
            touch_summary["favorable_first_rate"] is not None
            and confirm_summary["favorable_first_rate"] is not None
        ):
            lift = (
                confirm_summary["favorable_first_rate"]
                - touch_summary["favorable_first_rate"]
            )
        barriers[str(barrier)] = {
            "touch_baseline": touch_summary,
            "confirmed_forecast": confirm_summary,
            "confirmation_lift_favorable_first": lift,
        }

    primary = barriers[str(PRIMARY_BARRIER_ATR)]
    favorable_confirm_count = int(
        primary["confirmed_forecast"]["first_hit_counts"]["FAVORABLE"]
    )
    return {
        "scenarios": len(ss),
        "zone_touched": len(touched),
        "raw_confirmed": len(confirmed),
        "barriers_atr": barriers,
        "full_sequence_favorable_1atr_count": favorable_confirm_count,
        "full_sequence_favorable_1atr_rate": None
        if not ss
        else favorable_confirm_count / len(ss),
        "direction_counts": {
            "CONT_LONG": sum(s.continuation_direction == "LONG" for s in ss),
            "CONT_SHORT": sum(s.continuation_direction == "SHORT" for s in ss),
        },
    }


def evaluate_v169(
    rows: Sequence[Bar],
    *,
    evaluation_end: datetime,
) -> dict[str, Any]:
    bars = tuple(sorted(rows, key=lambda row: ensure_utc(row.timestamp)))
    end = ensure_utc(evaluation_end)
    indicators = _indicator_series(bars)
    atr_values = indicators["atr"]

    paths = {
        rule: build_independent_rule_path(
            bars,
            evaluation_end=end,
            rule=rule,
        )[0]
        for rule in RULES
    }

    full_start = datetime(2012, 1, 1, tzinfo=timezone.utc)
    full = {
        rule: _window(
            bars,
            paths[rule],
            atr_values,
            start=full_start,
            end=end,
        )
        for rule in RULES
    }

    windows = {}
    for label, start, stop in WINDOWS:
        bounded_stop = min(ensure_utc(stop), end)
        if ensure_utc(start) >= bounded_stop:
            continue
        windows[label] = {
            rule: _window(
                bars,
                paths[rule],
                atr_values,
                start=start,
                end=bounded_stop,
            )
            for rule in RULES
        }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "rules": list(RULES),
        "forecast_contract": {
            "selector": "V161_FROZEN_0P75_0P65",
            "path_builder": "V166_RULE_SPECIFIC_SELECTOR_FIRST_INDEPENDENT_CLOCKS",
            "primary_barrier_atr": PRIMARY_BARRIER_ATR,
            "sensitivity_barriers_atr": list(SENSITIVITY_BARRIERS_ATR),
            "horizon_m15": HORIZON_M15,
            "anchor": "COMPLETED_M15_CONFIRM_CLOSE",
            "favorable_definition": (
                "+barrier ATR in AFIC continuation direction before -barrier ATR adverse"
            ),
            "same_bar_double_hit": "AMBIGUOUS_NOT_FORCED_TO_WIN_OR_LOSS",
            "target_geometry_ignored": True,
            "structural_stop_ignored_for_forecast_scoring": True,
            "no_threshold_grid": True,
            "no_same_sample_promotion": True,
        },
        "full": full,
        "windows": windows,
        "note": (
            "V169 isolates AFIC path forecasting skill from fixed-dollar execution "
            "geometry. It is descriptive/diagnostic because the confirmation rules "
            "have already been observed historically; prospective validation remains required."
        ),
    }
