"""Read-only XAU manual time-frame map with strict research provenance.

This module NEVER promotes archived R11-R28.1 benchmarks into live model output.
Historical locked accuracy != a portable trained model.  Time-frame zones are
research WATCH references; they are not validated entries or trade orders.
"""
from __future__ import annotations

from datetime import datetime
from math import isfinite

import pandas as pd

from .frozen_direction_context import TFS, next_candle_prediction, watch_zone

PARENT = {"H1": "H4", "H4": "D1", "D1": "W1", "W1": None}
TIMING = {
    "H1": "M15 untuk rejection/reclaim, M5 untuk break struktur (BOS)",
    "H4": "H1 untuk konteks, M15/M5 untuk konfirmasi entry",
    "D1": "H4/H1 untuk pullback; konfirmasi M15/M5 sebelum entry",
    "W1": "D1/H4 untuk swing; H1/M15 untuk penentuan waktu",
}
MODEL_STATE = "WAIT MODEL"


def historical_benchmarks(lock):
    """Verbatim exploratory high-water marks, never a combined policy."""
    rows = {}
    for entry in lock.get("entries", []):
        tf, side = entry.get("tf"), entry.get("side")
        if tf not in TFS or side not in ("BUY", "SELL"):
            continue
        value = entry.get("accuracy")
        n = entry.get("n")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if not isfinite(value) or not 0 <= value <= 1 or type(n) is not int or n <= 0:
            continue
        rows[(tf, side)] = {
            "tf": tf, "side": side, "accuracy": float(value),
            "n": n, "version": str(entry.get("version") or "—"),
        }
    return rows


def _v05_zone(tf, side, paths):
    """Use only validated, fresh WATCH geometry already published by V05.

    WATCH confirms that geometry and staleness gates passed; it does NOT mean
    a direction model or entry setup passed independent forward validation.
    """
    if not isinstance(paths, dict) or paths.get("state") != "WATCH":
        return None
    candidates = []
    for row in paths.get("limit") or []:
        source = row.get("source") or {}
        if (
            row.get("state") == "WATCH"
            and row.get("first_touch_verified") is True
            and row.get("side") == side
            and source.get("timeframe") == tf
            and row.get("entry_allowed") is False
        ):
            low, high = source.get("low"), source.get("high")
            price = row.get("price_at_evaluation")
            if all(type(v) in (float, int) and isfinite(v) for v in (low, high, price)) and 0 < low < high:
                candidates.append((max(low - price, price - high, 0), row))
    if not candidates:
        return None
    distance, row = min(candidates, key=lambda pair: pair[0])
    source = row["source"]
    lo, hi = float(source["low"]), float(source["high"])
    side = row["side"]
    price = float(row["price_at_evaluation"])
    return {
        "tf": tf, "side": side, "low": lo, "high": hi,
        "invalidation": lo if side == "BUY" else hi,
        "distance": distance, "reference_close": price,
        "label": "Demand · BUY" if side == "BUY" else "Supply · SELL",
        "source": "V05 A→B · published watch, first-touch audited",
        "status": "WATCH_RESEARCH", "tested_entry": False,
        "position": "DI ZONA" if lo <= price <= hi else "DI ATAS ZONA" if price > hi else "DI BAWAH ZONA",
        "target_validated": row.get("target") is not None,
        "confirmation": TIMING[tf],
    }


def timeframe_guidance(tf, report, bars, reports, *, now, v05_paths=None):
    """Independent, frozen-candle-only zone and technical *hypothesis*."""
    if tf not in TFS:
        raise ValueError("UNSUPPORTED_TIMEFRAME")
    technical = next_candle_prediction(report, tf, now=now)
    out = {
        "tf": tf, "model": MODEL_STATE, "model_status": "NO_PORTABLE_R28_MODEL",
        "technical": technical["headline"], "technical_kind": technical["kind"],
        "target_at": technical["target_at"],
        "watch_area": None, "state": "WAIT_DATA", "confirmation": TIMING[tf],
        "execution_authority": False, "execution_influence": False,
        "historically_validated_zone": False,
    }
    if technical["kind"] != "TECHNICAL_RESEARCH" or technical["headline"] not in ("BUY", "SELL"):
        out["state"] = "WAIT_TECHNICAL_OR_DATA"
        return out

    side = technical["headline"]
    zone = _v05_zone(tf, side, v05_paths) if tf in ("H1", "H4") else None
    if zone is None:
        raw = watch_zone(bars, report)
        if raw is not None and raw.get("active") and raw.get("side") == side:
            zone = {
                "tf": tf, "side": side, "low": float(raw["low"]), "high": float(raw["high"]),
                "invalidation": float(raw["invalidation"]),
                "distance": float(raw["distance"]), "reference_close": float(raw["reference_close"]),
                "label": raw["label"], "source": "Kuartil rentang 20 candle · BELUM backtest",
                "status": "OBSERVATION_ONLY", "tested_entry": False,
                "position": raw["position"], "target_validated": False,
                "confirmation": TIMING[tf],
            }
    if zone is None:
        out["state"] = "WAIT_ZONE"
        return out
    out["watch_area"] = zone

    parent = PARENT[tf]
    higher = reports.get(parent, {}) if parent else {}
    if higher.get("fresh") and higher.get("forecast") in ("BUY", "SELL") and higher["forecast"] != side:
        out["state"] = "WAIT_OPPOSING_HIGHER_TF"
    else:
        out["state"] = "WATCH_ONLY"
    # Always a non-executable research area, even with agreement and M5 confirmation.
    return out


def r2_tactical(snapshot, *, now):
    """Only serialized, separately tested R2 SELL trigger; not H1 close forecast."""
    out = {"state": "WAIT", "side": None, "reference": None, "level": None,
           "expires": None, "model": "R2_RULE_670", "execution_authority": False}
    try:
        from .entry_direction_r2.runtime_contract import validate_snapshot
        p = validate_snapshot(snapshot, now=now)
        if p.get("status") != "TRIGGER_SELL" or p.get("direction") != "SELL":
            return out
        if p.get("policy") != "SELL_ONLY":
            return out
        s = p.get("signal") or {}
        if s.get("side") != "SELL":
            return out
        reference, level = s.get("reference"), s.get("level")
        if any(type(v) not in (int, float) or not isfinite(v) or v <= 0 for v in (reference, level)):
            return out
        return {**out, "state": "TRIGGER_SELL", "side": "SELL",
                "reference": float(reference), "level": float(level),
                "expires": str(s["valid_until"])}
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
        return out



def direction_board_rows(guides):
    """Display actual current technical forecasts, never invented R28 model results.

    Every BUY/SELL is produced from a fresh completed candle; missing or neutral
    evidence stays WAIT. Do not render benchmark hit rates as confidence.
    """
    result = []
    for tf in TFS:
        row = guides.get(tf) or {}
        value = row.get("technical", "WAIT DATA")
        if value not in ("BUY", "SELL", "WAIT · NETRAL", "WAIT DATA"):
            value = "WAIT DATA"
        active = value in ("BUY", "SELL") and row.get("technical_kind") == "TECHNICAL_RESEARCH"
        if not active and value in ("BUY", "SELL"):
            value = "WAIT DATA"
        target = row.get("target_at") if active else None
        if target is not None:
            try:
                t = pd.Timestamp(target)
                if t.tzinfo is None:
                    raise ValueError("Naive timestamp")
                target = t.tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M WIB")
            except (TypeError, ValueError, OverflowError):
                value, target, active = "WAIT DATA", None, False
        result.append({
            "TF": tf,
            "Arah": value,
            "Target close (WIB)": target or "—",
            "Sumber": "5 bukti teknikal · indikatif" if active else "WAIT · belum ada prediksi aktif",
            "model_r28_live": False,
            "execution_authority": False,
        })
    return result
