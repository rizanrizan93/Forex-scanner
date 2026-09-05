from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Mapping, Sequence

from .demo_technical_strategy import _demo_directional_structure_score
from .models import Bar, ensure_utc
from .sessions import session_label
from .technical import atr


def _enumish(value: Any) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", value)
    text = str(raw).strip().upper()
    return text or None


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _aligned(value: Any, direction: str) -> bool:
    wanted = "BULLISH" if str(direction).upper() == "LONG" else "BEARISH"
    return _enumish(value) == wanted


def _opposite(value: Any, direction: str) -> bool:
    wanted = "BEARISH" if str(direction).upper() == "LONG" else "BULLISH"
    return _enumish(value) == wanted


def _transition_evidence(snapshot: Any, direction: str) -> bool:
    displacement = getattr(snapshot, "displacement", None)
    return bool(
        _aligned(getattr(snapshot, "mss", None), direction)
        or (
            _aligned(getattr(snapshot, "bos", None), direction)
            and displacement is not None
            and bool(getattr(displacement, "valid", False))
            and _aligned(getattr(displacement, "direction", None), direction)
        )
    )


def classify_regime_v2(analysis: Any) -> str:
    """Direction-aware structural regime for calibration attribution only.

    The classifier is intentionally deterministic and has no execution effect.
    It separates persistent trend, range, transition, and reversal contexts so
    cohort calibration can learn setup/regime interactions without mutating the
    strategy that created the observation.
    """
    direction = str(analysis.direction).upper()
    h1 = analysis.h1
    m15 = analysis.m15
    m5 = analysis.m5
    h1_score = _demo_directional_structure_score(h1, direction)
    m15_score = _demo_directional_structure_score(m15, direction)
    m5_score = _demo_directional_structure_score(m5, direction)

    lower_transition = _transition_evidence(m15, direction) or _transition_evidence(m5, direction)
    if _opposite(getattr(h1, "trend", None), direction) and lower_transition:
        return "REVERSAL"
    if lower_transition and not _aligned(getattr(h1, "trend", None), direction):
        return "TRANSITION"

    h1_trend = _enumish(getattr(h1, "trend", None))
    m15_trend = _enumish(getattr(m15, "trend", None))
    if "RANGE" in {h1_trend, m15_trend} and not lower_transition:
        return "RANGE"

    aligned_h1 = _aligned(getattr(h1, "trend", None), direction)
    aligned_m15 = _aligned(getattr(m15, "trend", None), direction)
    aligned_m5 = _aligned(getattr(m5, "trend", None), direction)
    m5_disp = getattr(m5, "displacement", None)
    displacement_ok = bool(
        m5_disp is not None
        and bool(getattr(m5_disp, "valid", False))
        and _aligned(getattr(m5_disp, "direction", None), direction)
    )
    if (
        aligned_h1
        and aligned_m15
        and (h1_score or 0.0) >= 65.0
        and (m15_score or 0.0) >= 60.0
        and (m5_score or 0.0) >= 55.0
        and (aligned_m5 or displacement_ok)
    ):
        return "TREND_STRONG"
    if (
        (aligned_h1 or aligned_m15)
        and not _opposite(getattr(h1, "trend", None), direction)
        and not _opposite(getattr(m15, "trend", None), direction)
        and max(h1_score or 0.0, m15_score or 0.0, m5_score or 0.0) >= 50.0
    ):
        return "TREND_WEAK"
    if any(value not in {None, "UNKNOWN"} for value in (h1_trend, m15_trend)):
        return "MIXED"
    return "UNKNOWN"


def _atr_features(bars_by_timeframe: Mapping[str, Sequence[Bar]], atr_period: int) -> dict[str, float | str | None]:
    output: dict[str, float | str | None] = {}
    for tf in ("H1", "M15", "M5"):
        bars = tuple(bars_by_timeframe.get(tf, ()))
        if len(bars) < 2:
            output[f"atr_{tf.lower()}"] = None
            output[f"atr_pct_{tf.lower()}"] = None
            continue
        try:
            value = float(atr(list(bars), atr_period))
        except Exception:
            value = 0.0
        close = float(bars[-1].close)
        output[f"atr_{tf.lower()}"] = value if value > 0 else None
        output[f"atr_pct_{tf.lower()}"] = (
            100.0 * value / close if value > 0 and close > 0 else None
        )

    m5 = tuple(bars_by_timeframe.get("M5", ()))
    m5_atr = _finite(output.get("atr_m5"))
    if m5 and m5_atr and m5_atr > 0:
        last_range = float(m5[-1].high) - float(m5[-1].low)
        ratio = max(0.0, last_range / m5_atr)
        output["m5_range_atr_ratio"] = ratio
        if ratio >= 1.80:
            output["volatility_regime"] = "HIGH_VOLATILITY"
        elif ratio <= 0.60:
            output["volatility_regime"] = "LOW_VOLATILITY"
        else:
            output["volatility_regime"] = "NORMAL_VOLATILITY"
    else:
        output["m5_range_atr_ratio"] = None
        output["volatility_regime"] = "UNKNOWN_VOLATILITY"
    return output


def _structure_snapshot(snapshot: Any, direction: str) -> dict[str, Any]:
    displacement = getattr(snapshot, "displacement", None)
    fvg = getattr(snapshot, "fvg", None)
    sweep = getattr(snapshot, "sweep", None)
    return {
        "trend": _enumish(getattr(snapshot, "trend", None)),
        "directional_score": _demo_directional_structure_score(snapshot, direction),
        "bos": _enumish(getattr(snapshot, "bos", None)),
        "mss": _enumish(getattr(snapshot, "mss", None)),
        "last_swing_high": _finite(getattr(snapshot, "last_swing_high", None)),
        "last_swing_low": _finite(getattr(snapshot, "last_swing_low", None)),
        "displacement_direction": _enumish(getattr(displacement, "direction", None)),
        "displacement_valid": bool(getattr(displacement, "valid", False)) if displacement is not None else False,
        "displacement_range_atr_ratio": _finite(getattr(displacement, "range_atr_ratio", None)),
        "displacement_body_ratio": _finite(getattr(displacement, "body_ratio", None)),
        "fvg_direction": _enumish(getattr(fvg, "direction", None)),
        "fvg_valid": bool(getattr(fvg, "valid", False)) if fvg is not None else False,
        "fvg_size_atr": _finite(getattr(fvg, "size_atr", None)),
        "sweep_direction": _enumish(getattr(sweep, "direction", None)),
        "sweep_valid": bool(getattr(sweep, "valid", False)) if sweep is not None else False,
        "sweep_penetration_atr": _finite(getattr(sweep, "penetration_atr", None)),
    }


def build_signal_feature_snapshot_v2(
    *,
    analysis: Any,
    bars_by_timeframe: Mapping[str, Sequence[Bar]],
    signal_row: Mapping[str, Any],
    geometry_payload: Mapping[str, Any],
    session_config: Mapping[str, Any],
    atr_period: int,
) -> dict[str, Any]:
    observed_raw = signal_row.get("observed_at")
    if isinstance(observed_raw, datetime):
        observed_at = ensure_utc(observed_raw)
    else:
        parsed = datetime.fromisoformat(str(observed_raw).replace("Z", "+00:00"))
        observed_at = ensure_utc(parsed)

    evidence_scores = {
        str(key): _finite(value)
        for key, value in dict(getattr(analysis, "conviction_components", {}) or {}).items()
    }
    guards = {
        str(key): bool(value)
        for key, value in dict(getattr(analysis, "computed_guards", {}) or {}).items()
    }
    snapshot: dict[str, Any] = {
        "snapshot_version": 2,
        "snapshot_type": "IMMUTABLE_SIGNAL_FEATURES",
        "signal_id": str(signal_row.get("id") or ""),
        "run_id": signal_row.get("run_id"),
        "observed_at": observed_at.isoformat(),
        "symbol": str(signal_row.get("symbol") or analysis.symbol).upper(),
        "direction": str(signal_row.get("direction") or analysis.direction).upper(),
        "setup_type": _enumish(signal_row.get("setup_type") or analysis.setup_type),
        "final_score": _finite(signal_row.get("final_score")),
        "regime": classify_regime_v2(analysis),
        "regime_classifier": "STRUCTURE_V2_DIRECTION_AWARE",
        "session": session_label(observed_at, dict(session_config)),
        "trigger_confirmed": bool(getattr(analysis, "trigger_confirmed", False)),
        "stale_timeframes": list(getattr(analysis, "stale_timeframes", ()) or ()),
        "structure_h1": _structure_snapshot(analysis.h1, analysis.direction),
        "structure_m15": _structure_snapshot(analysis.m15, analysis.direction),
        "structure_m5": _structure_snapshot(analysis.m5, analysis.direction),
        "evidence_scores": evidence_scores,
        "computed_guards": guards,
        "entry_mode": geometry_payload.get("entry_mode"),
        "confirmation": geometry_payload.get("confirmation"),
        "pullback_atr": _finite(geometry_payload.get("pullback_atr")),
        "zone_distance_atr": _finite(geometry_payload.get("zone_distance_atr")),
        "fvg_status": geometry_payload.get("fvg_status"),
        "fvg_age_minutes": _finite(geometry_payload.get("fvg_age_minutes")),
        "entry_low": _finite(signal_row.get("entry_low")),
        "entry_high": _finite(signal_row.get("entry_high")),
        "planned_sl": _finite(signal_row.get("sl")),
        "planned_tp1": _finite(signal_row.get("tp1")),
        "planned_tp2": _finite(signal_row.get("tp2")),
        "rr1": _finite(signal_row.get("rr1")),
        "rr2": _finite(signal_row.get("rr2")),
        "active_guards": list(signal_row.get("active_guards") or ()),
        "data_coverage": _finite(signal_row.get("data_coverage")),
        "spread_pips_at_entry": None,
        "live_entry_drift_r": None,
        "entry_execution_snapshot_required": True,
        "source": "DEMO_WAVE_AWARE_PRODUCER",
        "policy_effect": "OBSERVATION_ONLY",
    }
    snapshot.update(_atr_features(bars_by_timeframe, int(atr_period)))
    snapshot["snapshot_complete_for_regime"] = all(
        snapshot.get(key) not in (None, "")
        for key in ("symbol", "direction", "setup_type", "regime", "entry_mode", "confirmation", "atr_m5")
    )
    return snapshot
