"""Frozen V1-first XAU consensus audit, without execution or order authority.

Both engines use their own validated read-only feeds and independent rules.
The consensus is shown ONLY when H1/M5 candle CLOSE timestamps align and
prices are comparable. V1 never loses its native decision authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Mapping

from .cbot_v1_evidence import current, stamp
from .frozen_v1_directional_score import _rows as frozen_rows
from .xau_decision_checklist_v1 import closed_bars

MARKET_CONTRACT = "RIZAN_BOOTSTRAP125_MARKET_READONLY_V1"
RESEARCH_CONTRACT = "RIZAN_XAU_CLOSED_CANDLES_READONLY_V1"
ACCOUNT_SUFFIX = "7903"
COMPARED_FRAMES = ("H1", "M5")
SECONDS = {"H1": 3600, "M5": 300}
MIN_BARS = {"H1": 11, "M5": 7}
RESEARCH_STATES = {"WATCH_SHADOW", "ARMED_SHADOW", "CONFIRMED_SHADOW"}
MAX_REL_CLOSE_DRIFT = .0008  # conservative sanity check, NOT a trading threshold
MAX_ABS_CLOSE_DRIFT = .50


def _obj(value):
    return dict(value) if isinstance(value, Mapping) else {}


def _frozen_direction(v1):
    x = _obj(_obj(v1).get("symbols")).get("XAUUSD")
    x = _obj(x)
    if x.get("market_valid") is not True or x.get("phase") != "GROWTH":
        return None
    if x.get("bias") == "BUY LEBIH KUAT":
        return "BUY"
    if x.get("bias") == "SELL LEBIH KUAT":
        return "SELL"
    return None


def _research_direction(research):
    report = _obj(research)
    preferred = report.get("preferred")
    row = _obj(report.get(preferred))
    if (report.get("execution_authority") is not False
            or report.get("order_enabled") is not False):
        return None
    if preferred in ("BUY", "SELL") and row.get("state") in RESEARCH_STATES:
        return preferred
    return None


def _frozen_session(family: str | None, closed_at):
    if not family or closed_at is None:
        return "UNKNOWN"
    # Only original Frozen V1 XAU growth windows. NOT a native execution gate.
    if closed_at.weekday() >= 5:
        return "CLOSED"
    if family == "XAU displacement H1":
        return "OPEN" if 5 <= closed_at.hour < 17 else "CLOSED"
    if family == "XAU compression M5":
        return "OPEN" if 12 <= closed_at.hour < 17 else "CLOSED"
    return "UNKNOWN"


def _compare_candles(v1_market, research_candles, now):
    details = {}
    if not current(v1_market, MARKET_CONTRACT, now, age=180):
        return "WAIT_V1_MARKET", details
    if not isinstance(research_candles, Mapping) or any([
        research_candles.get("contract") != RESEARCH_CONTRACT,
        research_candles.get("symbol") != "XAUUSD",
        research_candles.get("account_suffix") != ACCOUNT_SUFFIX,
        research_candles.get("execution_authority") is not False,
        research_candles.get("execution_influence") is not False,
    ]):
        return "WAIT_RESEARCH_MARKET", details
    for tf in COMPARED_FRAMES:
        v1 = frozen_rows(v1_market, "XAUUSD", tf, now, MIN_BARS[tf])
        research, error = closed_bars(research_candles, tf, now)
        if not v1 or error or not research:
            details[tf] = {"status": "UNKNOWN", "reason": error or "Sumber candle tidak lengkap"}
            return "WAIT_CANDLE", details
        v1_last = v1[-1]
        original_close = v1_last["at"] + timedelta(seconds=SECONDS[tf])
        research_close = research[-1]["at"]
        a, b = float(v1_last["c"]), float(research[-1]["c"])
        drift = abs(a - b)
        allowed = max(MAX_ABS_CLOSE_DRIFT, min(a, b) * MAX_REL_CLOSE_DRIFT)
        details[tf] = {
            "v1_closed_at": original_close.isoformat(),
            "research_closed_at": research_close.isoformat(),
            "v1_close": a,
            "research_close": b,
            "price_gap": round(drift, 5),
            "allowed_gap": round(allowed, 5),
            "status": "COMPARABLE" if original_close == research_close and drift <= allowed else "MISMATCH",
        }
        if original_close != research_close:
            return "WAIT_TIMESTAMP_MISMATCH", details
        if not (isfinite(a) and isfinite(b)) or drift > allowed:
            return "WAIT_PRICE_MISMATCH", details
    return "ALIGNED", details


def evaluate_consensus(*, v1_report, research_report, v1_market,
                       research_candles, phase, now: datetime, bridge_ready=False):
    """Never infer executable V1 signal, override native trade, or claim a miss."""
    if now.tzinfo is None:
        raise ValueError("NOW_MUST_BE_TIMEZONE_AWARE")
    now = now.astimezone(timezone.utc)
    v1 = _obj(_obj(_obj(v1_report).get("symbols")).get("XAUUSD"))
    research = _obj(research_report)
    alignment, comparisons = _compare_candles(v1_market, research_candles, now)
    vside = _frozen_direction(v1_report)
    rside = _research_direction(research)
    family = _obj(v1.get(vside)).get("family") if vside else None
    last_tf = "H1" if family == "XAU displacement H1" else "M5"
    last_row = _obj(comparisons.get(last_tf))
    closed_at = stamp(last_row.get("v1_closed_at"))
    session = _frozen_session(family, closed_at)

    if phase != "GROWTH":
        state = "V1_PHASE_NOT_GROWTH" if phase == "SEED" else "WAIT_PHASE"
        explanation = "V1 SEED hanya EURUSD BUY; XAU belum aktif." if phase == "SEED" else "Fase native V1 belum terverifikasi."
    elif alignment != "ALIGNED":
        state = "WAIT_ALIGNMENT"
        explanation = "Tidak boleh menyimpulkan arah bersama karena sumber berbeda waktu, harga, atau belum valid."
    elif session == "CLOSED" and vside:
        state = "V1_OUTSIDE_SESSION"
        explanation = "Skor pola V1 tersedia tetapi keluarga terbaik di luar jendela entry frozen; bukan sinyal siap."
    elif vside and rside:
        state = "SELARAS_" + vside if vside == rside else "KONFLIK"
        explanation = ("Kedua alat riset memilih " + vside + "." if vside == rside else
                       "Frozen V1 condong " + vside + ", Analisis Terpadu condong " + rside +
                       "; periksa perbedaan H1/M5 dan USD/yield. V1 tidak diubah.")
    elif vside:
        state = "V1_BIAS_ONLY"
        explanation = "Pola V1 condong " + vside + ", Analisis Terpadu belum memberi arah valid. Tidak dianggap konflik."
    elif rside:
        state = "RESEARCH_ONLY"
        explanation = "Analisis Terpadu condong " + rside + " tetapi pola Frozen V1 belum cukup; jangan menganggap ini entry V1."
    else:
        state = "NETRAL"
        explanation = "Belum ada pilihan arah yang memenuhi definisi bias kedua panel."

    return {
        "contract": "RIZAN_XAU_CONSENSUS_V1_PRIMARY_READONLY",
        "as_of_utc": now.isoformat(),
        "state": state, "explanation": explanation,
        "primary_strategy": "RIZAN_BOOTSTRAP125_V1_FROZEN_20261114",
        "v1_direction": vside or "WAIT",
        "research_direction": rside or "WAIT",
        "v1_family": family, "v1_session": session,
        "v1_pattern_scores": {
            side: _obj(v1.get(side)).get("score") for side in ("BUY", "SELL")
        },
        "research_scores": {
            side: _obj(research.get(side)).get("score") for side in ("BUY", "SELL")
        },
        "v1_bridge_connected": bridge_ready is True,
        "alignment": alignment, "candle_comparison": comparisons,
        "native_entry_readiness": "UNKNOWN",
        "native_signal": "NOT_EVALUATED",
        "native_order_intent": "NOT_EVALUATED",
        "missed_order_verdict": "NOT_EVALUATED",
        "execution_authority": False, "execution_influence": False,
        "order_enabled": False,
        "scores_comparable": False,
        "confidence_calibrated": False,
    }
