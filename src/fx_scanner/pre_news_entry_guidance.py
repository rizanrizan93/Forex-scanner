"""Read-only, explainable XAUUSD news entry guidance.

This is NOT a fitted win probability, price/stop engine, or execution
authority. Decisions are point-in-time, conditional on independent price
confirmation; no post-release actual is used before its scheduled time.
"""
from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any

MAX_PUBLISH_AGE_S = 660
MAX_MACRO_AGE_S = 660
MAX_DXY_AGE_S = 900
MAX_YIELD_AGE_S = 1200
MIN_EFFECTIVE_NEWS_SCORE = 35


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        date = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
        return date.astimezone(UTC) if date.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def _value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _age(value: Any, now: datetime) -> float | None:
    at = _dt(value)
    return None if at is None else (now - at).total_seconds()


def _current(value: Any, now: datetime, max_age: float) -> bool:
    age = _age(value, now)
    return age is not None and 0 <= age <= max_age


def _clip(value: float) -> float:
    return max(-100.0, min(100.0, value))


def _result(phase: str, why: str) -> dict[str, Any]:
    return {
        "phase": phase,
        "decision": "WAIT",
        "bias": "NEUTRAL",
        "macro_score_xau": None,
        "score_xau": None,
        "score_unit": "signed_heuristic_-100_100",
        "confidence": "INSUFFICIENT",
        "forecast_verified": False,
        "news_verified": False,
        "macro_confirmed": False,
        "trade_ready": False,
        "entry_timeframe": "M1/M5",
        "trigger": "Tunggu harga, spread, dan market structure shift setelah rilis.",
        "invalidated_by": "Feed tidak segar, news surprise berlawanan, atau M1/M5 tidak mengonfirmasi.",
        "reason": why,
        "evidence": [],
        "warnings": ["Bukan probabilitas kemenangan; tidak mengirim order."],
        "execution_authority": False,
        "execution_influence": False,
    }


def evaluate_entry_guidance(
    view: dict[str, Any], snapshot: dict[str, Any], *, now: datetime
) -> dict[str, Any]:
    """Compute directional *preparation* for one next/recent release.

    Sign convention: XAU bullish positive, XAU bearish negative.
    Keep forecast-vs-previous completely separate from actual surprise.
    """
    current = _dt(now)
    if current is None:
        raise ValueError("now must be timezone-aware")
    state = str(view.get("state") or "")
    post = state.startswith("POST_NEWS")
    out = _result(
        "POST" if post else "PRE",
        "Menunggu feed kalender, forecast dan makro yang dapat dipercaya.",
    )
    event = view.get("event") or {}
    if not event or state not in {"PRE_NEWS", "POST_NEWS", "POST_NEWS_PENDING"}:
        out["reason"] = "Tidak ada event USD siap dinilai atau data belum lengkap."
        return out
    event_at = _dt(event.get("scheduled_at"))
    if event_at is None:
        out["reason"] = "Jam rilis event tidak valid."
        return out
    if (not _current(snapshot.get("published_at"), current, MAX_PUBLISH_AGE_S)
            and "published_at" in snapshot):
        out["reason"] = "Snapshot publikasi terlambat; jangan gunakan sinyal lama."
        return out
    if snapshot.get("publication_fresh") is False:
        out["reason"] = "Snapshot terakhir hanya referensi; jangan entry."
        return out
    by_worker = {
        str(h.get("worker_name")): h for h in snapshot.get("heartbeats") or []
    }
    from .pre_news_expectation import EVENT_WORKER, MACRO_WORKER
    calendar_hb = by_worker.get(EVENT_WORKER) or {}
    macro_hb = by_worker.get(MACRO_WORKER) or {}
    if not calendar_hb.get("healthy") or not _current(
        calendar_hb.get("observed_at"), current, MAX_MACRO_AGE_S
    ):
        out["reason"] = "Kalender tidak sehat atau terlambat."
        return out
    if not macro_hb.get("healthy") or not _current(
        macro_hb.get("observed_at"), current, MAX_MACRO_AGE_S
    ):
        out["reason"] = "Makro tidak sehat atau terlambat."
        return out
    evaluation = (macro_hb.get("details") or {}).get("evaluation") or {}
    broader = _value(evaluation.get("macro_score"))
    dxy = evaluation.get("dxy_intraday") or {}
    yield_data = evaluation.get("intraday_yield_context") or {}
    dxy_age = _age(dxy.get("current_at"), current)
    yield_age = _age(yield_data.get("current_at"), current)
    dxy_pct = _value(dxy.get("net_pct"))
    yield_bps = _value(yield_data.get("net_bps"))
    dxy_ok = (
        dxy.get("freshness") == "FRESH"
        and _current(dxy.get("current_at"), current, MAX_DXY_AGE_S)
        and dxy_pct is not None
        and dxy.get("available") is True
    )
    yield_ok = (
        yield_data.get("freshness") == "FRESH"
        and _current(yield_data.get("current_at"), current, MAX_YIELD_AGE_S)
        and yield_bps is not None
        and yield_data.get("available") is True
        # Cash-yield only; do not mistake an inverse futures price for yield.
        and str(yield_data.get("state") or "").startswith("US10Y_CASH")
    )
    components: list[tuple[str, float, float, str]] = []
    if broader is not None and _clip(broader) == broader:
        components.append(("Broad macro regime", broader, .45, "DAILY_REGIME"))
    if dxy_ok:
        components.append((
            "DXY intraday", -_clip(dxy_pct / .25 * 100), .35,
            f"{dxy_pct:+.3f}% · {round(dxy_age or 0)}s",
        ))
    if yield_ok:
        components.append((
            "US10Y cash intraday", -_clip(yield_bps / 5.0 * 100), .20,
            f"{yield_bps:+.2f} bps · {round(yield_age or 0)}s",
        ))
    weight_sum = sum(weight for _, _, weight, _ in components)
    if weight_sum:
        score = _clip(sum(value * weight for _, value, weight, _ in components) / weight_sum)
        out["score_xau"] = round(score, 1)
        out["macro_score_xau"] = round(score, 1)
        out["evidence"].extend({
            "name": label, "xau_score": round(value, 1),
            "weight": weight, "source": detail,
        } for label, value, weight, detail in components)
    else:
        score = 0.0
    out["macro_confirmed"] = bool(dxy_ok and yield_ok and
        ((dxy_pct > .05 and yield_bps > 1.0) or
         (dxy_pct < -.05 and yield_bps < -1.0)))
    if not dxy_ok:
        out["warnings"].append("DXY intraday tidak cukup segar untuk konfirmasi berita.")
    if not yield_ok:
        out["warnings"].append("Yield US10Y intraday tidak cukup segar untuk konfirmasi berita.")
    cluster = list(view.get("event_cluster") or [])
    out["forecast_verified"] = bool(view.get("forecast_quorum_met"))
    if not post:
        if current >= event_at:
            out["reason"] = "Rilis telah dimulai; tunggu actual, jangan pakai prediksi pra-rilis."
            return out
        if str(event.get("category") or "") == "FOMC":
            out["reason"] = "FOMC memerlukan pernyataan dan repricing suku bunga; WAIT sebelum isi rilis."
            return out
        minutes = (event_at-current).total_seconds() / 60.0
        if abs(score) < MIN_EFFECTIVE_NEWS_SCORE:
            out["reason"] = "Tekanan makro tidak cukup dominan untuk panduan satu arah."
            return out
        side = "SELL" if score < 0 else "BUY"
        out["bias"] = side
        out["confidence"] = "MODERATE" if out["macro_confirmed"] else "LOW"
        out["decision"] = f"{side} BIAS — TUNGGU RILIS"
        out["reason"] = (
            f"Skor makro XAU {score:+.1f}/100; arah {side} lebih relevan sebagai "
            "skenario persiapan. Actual hot/cool BELUM diketahui."
        )
        if not out["forecast_verified"]:
            out["warnings"].append(
                "Quorum forecast numerik 3 sumber belum lengkap; panduan sementara."
            )
            out["confidence"] = "LOW"
        if minutes > 120:
            out["confidence"] = "LOW"
            out["warnings"].append("Event masih jauh; bias harus dihitung ulang mendekati rilis.")
        out["trigger"] = (
            f"Setelah angka aktual tersedia, tunggu {side} displacement M1, "
            "retetst/FVG yang valid, dan DXY serta yield mendukung. "
            "Jangan place limit/market sebelum konfirmasi."
        )
        out["invalidated_by"] = (
            "Actual berlawanan dengan skenario, DXY/yield berbalik, "
            "atau harga menembus struktur invalidasi M5."
        )
        return out

    if current < event_at:
        out["reason"] = "Data post-release tidak boleh terlihat sebelum waktu rilis."
        return out
    out["forecast_verified"] = False
    if state == "POST_NEWS_PENDING" or not cluster:
        out["reason"] = "Menunggu actual yang dapat divalidasi; NO TRADE."
        return out
    if any(row.get("hawkish_tilt") not in (-1, 0, 1) for row in cluster):
        out["reason"] = "Komponen actual tidak dapat diidentifikasi."
        return out
    signs = {row.get("hawkish_tilt") for row in cluster if row.get("hawkish_tilt")}
    status = str(view.get("news_conclusion_status") or "")
    verified = status in {"OFFICIAL_VERIFIED", "MULTI_SOURCE_CORROBORATED"}
    if status == "PARTIAL_ACTUAL":
        out["reason"] = "Actual parsial, belum dapat dipakai sebagai panduan entry."
        return out
    if signs != {1} and signs != {-1}:
        out["reason"] = "Actual campuran/inline terhadap forecast; NO TRADE."
        return out
    side = "SELL" if signs == {1} else "BUY"
    out["bias"] = side
    out["news_verified"] = verified
    out["confidence"] = "MODERATE" if verified else "LOW"
    out["evidence"].extend({
        "name": str(row.get("event_component") or row.get("title")),
        "actual": row.get("actual"), "forecast": row.get("forecast"),
        "surprise": row.get("surprise"), "source": row.get("source"),
    } for row in cluster)
    if (score < -MIN_EFFECTIVE_NEWS_SCORE and side == "BUY" or
            score > MIN_EFFECTIVE_NEWS_SCORE and side == "SELL"):
        out["reason"] = "Actual surprise berlawanan dengan konteks makro; risiko whipsaw."
        out["decision"] = "WAIT — NEWS vs MAKRO KONFLIK"
        return out
    # A 4-minute news publisher cannot certify spread or M1 price acceptance
    # in the first 60-120 seconds. Guide the direction, NEVER assert fill/entry.
    out["decision"] = f"{side} SETUP — KONFIRMASI M1/M5"
    out["reason"] = (
        f"Actual surprise mendukung {side} XAU; "
        + ("dua sumber/official mendukung" if verified else "actual masih satu sumber")
        + ". Validasi harga dan spread dibutuhkan sebelum order."
    )
    out["trigger"] = (
        f"Tunggu {side} displacement + retest FVG/order block M1/M5, "
        "spread normal, dan DXY/yield mempertahankan arah; "
        "jangan kejar wick pertama."
    )
    out["invalidated_by"] = (
        "Reclaim origin spike dan struktur M5 berlawanan; DXY/yield reversal; "
        "spread ekstrem atau quote tidak tersedia."
    )
    out["warnings"].append(
        "Feed dipublikasi sekitar tiap 4 menit: BUKAN sinyal 1–2 menit real-time."
    )
    if not verified:
        out["warnings"].append("Actual belum dikonfirmasi BLS/2 penyedia.")
    if out["macro_confirmed"] and (
        (side == "SELL" and dxy_pct > 0 and yield_bps > 0) or
        (side == "BUY" and dxy_pct < 0 and yield_bps < 0)
    ) and verified:
        out["confidence"] = "MODERATE"
    return out
