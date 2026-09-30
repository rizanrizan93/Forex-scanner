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
CONTEXT_CALIBRATION_RELATIVE_PATH = Path(
    "calibration/xau_v281_competing_risk_context_counts.json"
)
CONTEXT_CONTRACT = "XAU_V281_CONTEXT_DASHBOARD_V286_1"


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


@lru_cache(maxsize=2)
def load_v281_context_prior(root: str | None = None) -> dict[str, Any]:
    base = Path(root) if root else _repo_root()
    payload = json.loads(
        (base / CONTEXT_CALIBRATION_RELATIVE_PATH).read_text(encoding="utf-8")
    )
    if str(payload.get("contract") or "") != "XAU_V281_CONTEXT_DASHBOARD_COUNTS_1":
        raise ValueError("unexpected V281 contextual prior contract")
    if (
        bool(payload.get("execution_authority"))
        or bool(payload.get("execution_influence"))
        or bool(payload.get("calibrated_current_probability"))
    ):
        raise ValueError("V281 contextual prior must remain research-only")
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


def volatility_bucket_from_atr(
    *,
    timeframe: str,
    atr_points: float | None,
    root: str | None = None,
) -> str:
    payload = load_v281_context_prior(root)
    tf = str(timeframe or "").upper()
    cuts = dict(dict(payload.get("volatility_thresholds") or {}).get(tf) or {})
    if atr_points is None or not cuts:
        return "UNKNOWN"
    try:
        atr = float(atr_points)
        low = float(cuts["low_cut"])
        high = float(cuts["high_cut"])
    except (TypeError, ValueError, KeyError):
        return "UNKNOWN"
    if atr <= low:
        return "LOW"
    if atr >= high:
        return "HIGH"
    return "MID"


def historical_pressure_proxy_bucket(live_pressure_state: str | None) -> dict[str, Any]:
    state = str(live_pressure_state or "UNAVAILABLE").upper()
    mapping = {
        "OPPOSING_FADING_EARLY": "FADE",
        "OPPOSING_FADING": "FADE",
        "BALANCED_ABSORPTION": "BALANCE_OR_CONTROL_FLIP",
        "CONTROL_FLIP": "BALANCE_OR_CONTROL_FLIP",
        "OPPOSING_REACCELERATION": "REACCELERATION",
        "OPPOSING_STILL_ACTIVE": "STABLE",
    }
    bucket = mapping.get(state, "UNAVAILABLE")
    return {
        "live_dom_state": state,
        "historical_proxy_bucket": bucket,
        "bridge": "SEMANTIC_ONLY_NOT_CALIBRATED",
        "historical_source": "CAUSAL_M1_OHLC_TRANSITION_PROXY_NOT_DOM",
        "live_source": "CTRADER_LEVEL_II_DOM_SEPARATE_RUNTIME_SIGNAL",
    }


def era_bucket(year: int | None) -> str:
    value = int(year or 0)
    if value <= 2018:
        return "2012_2018"
    if value <= 2024:
        return "2019_2024"
    return "2025_2026"


def _context_cell(
    payload: dict[str, Any],
    *,
    dimension: str,
    key: str,
    band: str,
) -> dict[str, Any]:
    rows = list(dict(payload.get(dimension) or {}).get(key) or [])
    selected = _row_for_band(rows, band)
    return {
        "dimension": dimension,
        "key": key,
        "available": selected is not None,
        "selected": selected,
    }


def evaluate_v281_contextual_competing_risk(
    *,
    timeframe: str,
    depth: float | None,
    session: str,
    atr_points: float | None,
    live_pressure_state: str | None,
    first_touch_calibrated: bool,
    year: int | None = None,
    root: str | None = None,
) -> dict[str, Any]:
    payload = load_v281_context_prior(root)
    band = depth_band_label(depth)
    tf = str(timeframe or "").upper()
    base = {
        "contract": CONTEXT_CONTRACT,
        "available": False,
        "label": "RISET/FORECAST",
        "band": band,
        "timeframe": tf,
        "touch_scope": payload.get("touch_scope"),
        "retest_status": payload.get("retest_status"),
        "source_run_id": payload.get("source_run_id"),
        "source_artifact_id": payload.get("source_artifact_id"),
        "execution_authority": False,
        "execution_influence": False,
        "calibrated_current_probability": False,
        "historical_pressure_source": payload.get("historical_pressure_source"),
        "live_pressure_source": payload.get("live_pressure_source"),
        "volatility_thresholds_fit_on": payload.get("volatility_thresholds_fit_on"),
        "oos": dict(payload.get("oos") or {}),
    }
    if not first_touch_calibrated:
        return {
            **base,
            "reason": "RETEST_NOT_MEASURED_BY_V281",
            "interpretation": (
                "Context splits are first-touch research only. Reused zones do not inherit "
                "these frequencies as live probabilities."
            ),
        }
    if band is None:
        return {**base, "reason": "DEPTH_UNAVAILABLE"}

    session_key = str(session or "OFF_SESSION").upper()
    session_rows = dict(payload.get("session") or {})
    if session_key not in session_rows:
        session_key = "OFF_SESSION"

    volatility_key = volatility_bucket_from_atr(
        timeframe=tf,
        atr_points=atr_points,
        root=root,
    )
    pressure_bridge = historical_pressure_proxy_bucket(live_pressure_state)
    pressure_key = str(pressure_bridge["historical_proxy_bucket"])
    era_key = era_bucket(year)

    cells = {
        "session": _context_cell(
            payload, dimension="session", key=session_key, band=band
        ),
        "volatility": _context_cell(
            payload, dimension="volatility", key=volatility_key, band=band
        ),
        "historical_pressure_proxy": _context_cell(
            payload, dimension="pressure", key=pressure_key, band=band
        ),
        "era": _context_cell(
            payload, dimension="era", key=era_key, band=band
        ),
    }
    available = any(bool(cell.get("available")) for cell in cells.values())
    return {
        **base,
        "available": available,
        "reason": (
            "FIRST_TOUCH_CONTEXT_RESEARCH_AVAILABLE"
            if available
            else "CONTEXT_CELL_UNAVAILABLE"
        ),
        "session": session_key,
        "volatility_bucket": volatility_key,
        "pressure_bridge": pressure_bridge,
        "era": era_key,
        "cells": cells,
        "interpretation": (
            "Marginal historical first-touch context at the active depth band. Session, "
            "volatility and pressure-proxy splits are research context, not an exact joint "
            "live probability. Historical pressure uses causal M1 OHLC proxy; live pressure "
            "remains cTrader Level-II DOM and is evaluated separately."
        ),
    }


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
