from __future__ import annotations

import json
from functools import lru_cache
from math import floor, sqrt
from pathlib import Path
from typing import Any


CONTRACT = "XAU_V281_COMPETING_RISK_DASHBOARD_V285_1"
CALIBRATION_RELATIVE_PATH = Path(
    "calibration/xau_v281_competing_risk_dashboard_counts.json"
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=2)
def load_v281_dashboard_prior(root: str | None = None) -> dict[str, Any]:
    base = Path(root) if root else _repo_root()
    payload = json.loads((base / CALIBRATION_RELATIVE_PATH).read_text(encoding="utf-8"))
    if str(payload.get("contract") or "") != "XAU_V281_DASHBOARD_COUNTS_1":
        raise ValueError("unexpected V281 dashboard prior contract")
    if bool(payload.get("execution_authority")) or bool(payload.get("execution_influence")):
        raise ValueError("V281 dashboard prior must remain research-only")
    return payload


def wilson_interval(successes: int, n: int, *, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 0.0
    p = float(successes) / float(n)
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    half = (
        z
        * sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)
        / denom
    )
    return max(0.0, center - half), min(1.0, center + half)


def depth_band_label(depth: float | None) -> str | None:
    if depth is None:
        return None
    value = max(0.0, min(0.999999999, float(depth)))
    index = min(9, max(0, int(floor(value * 10.0))))
    return f"{10 * index:02d}-{10 * (index + 1):02d}%"


def _decode_row(raw: list[Any]) -> dict[str, Any]:
    band, at_risk, reversal, break_invalid, stall = raw
    n = int(at_risk)
    rev = int(reversal)
    brk = int(break_invalid)
    stl = int(stall)
    rev_ci = wilson_interval(rev, n)
    brk_ci = wilson_interval(brk, n)
    return {
        "band": str(band),
        "at_risk": n,
        "reversal_050": rev,
        "break_invalid": brk,
        "stall_unresolved": stl,
        "p_reversal": (rev / n if n else None),
        "p_break": (brk / n if n else None),
        "p_stall": (stl / n if n else None),
        "reversal_wilson_95": list(rev_ci),
        "break_wilson_95": list(brk_ci),
        "dominance": (
            "REVERSAL_DOMINANT"
            if rev > brk
            else "BREAK_DOMINANT"
            if brk > rev
            else "BALANCED"
        ),
    }


def _row_for_band(rows: list[list[Any]], band: str) -> dict[str, Any] | None:
    for raw in rows:
        if raw and str(raw[0]) == band:
            return _decode_row(raw)
    return None


def evaluate_v281_competing_risk_prior(
    *,
    timeframe: str,
    direction: str,
    depth: float | None,
    first_touch_calibrated: bool,
    root: str | None = None,
) -> dict[str, Any]:
    payload = load_v281_dashboard_prior(root)
    band = depth_band_label(depth)
    base = {
        "contract": CONTRACT,
        "available": False,
        "label": "RISET/FORECAST",
        "band": band,
        "timeframe": str(timeframe or "").upper(),
        "direction": str(direction or "").upper(),
        "touch_scope": payload.get("touch_scope"),
        "episode_count": payload.get("episode_count"),
        "execution_authority": False,
        "execution_influence": False,
        "calibrated_current_probability": False,
        "oos": dict(payload.get("oos") or {}),
        "promotion_gate": dict(payload.get("promotion_gate") or {}),
    }
    if not first_touch_calibrated:
        return {
            **base,
            "reason": "RETEST_NOT_MEASURED_BY_V281",
            "interpretation": (
                "V281 is first-touch only. On reused zones these counts are context only "
                "and must not be displayed as calibrated live probabilities."
            ),
        }
    if band is None:
        return {**base, "reason": "DEPTH_UNAVAILABLE"}

    tf = base["timeframe"]
    side = base["direction"]
    tf_payload = dict(dict(payload.get("tf_dir") or {}).get(tf) or {})
    rows = list(tf_payload.get(side) or [])
    decoded_rows = [_decode_row(raw) for raw in rows]
    selected = _row_for_band(rows, band)
    overall = _row_for_band(list(payload.get("ALL") or []), band)
    if not selected:
        return {
            **base,
            "reason": "TF_DIRECTION_CELL_UNAVAILABLE",
            "overall": overall,
        }

    first_break_dominant = None
    for raw in rows:
        decoded = _decode_row(raw)
        if decoded["dominance"] == "BREAK_DOMINANT":
            first_break_dominant = decoded["band"]
            break

    return {
        **base,
        "available": True,
        "reason": "FIRST_TOUCH_RESEARCH_PRIOR_AVAILABLE",
        "selected": selected,
        "overall": overall,
        "all_bands": decoded_rows,
        "first_break_dominant_band": first_break_dominant,
        "source_run_id": payload.get("source_run_id"),
        "source_artifact_id": payload.get("source_artifact_id"),
        "interpretation": (
            "Conditional historical frequency among first-touch episodes that actually "
            "reached this depth band. This is not a calibrated probability for the "
            "current live setup and cannot authorize execution."
        ),
    }
