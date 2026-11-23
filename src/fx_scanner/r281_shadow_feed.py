"""Read-only R28.1 reconstructed inference snapshot, independent of cBot.

The R28.1 replay selected annual models were reconstructed and historically
parity-checked. This is a SHADOW feed, not a frozen production model, calibrated
win rate, execution advice, or evidence of independent 2026 forward precision.
"""
from __future__ import annotations

from datetime import UTC, datetime
import base64
import binascii
import json
import math
import re
from urllib.request import Request, urlopen

import pandas as pd

CONTRACT = "RIZAN_R281_DIRECTION_SHADOW_SNAPSHOT_V1"
SOURCE = "CTRADER_MARKET_DATA_READ_ONLY"
LINEAGE = "R28.1_RECONSTRUCTED_SHADOW_NOT_FROZEN_LIVE"
URL = ("https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/"
       "research/r281-direction-inference-parity-20261123/"
       "runtime/r281-shadow-direction.json")
API_URL = ("https://api.github.com/repos/rizanrizan93/Forex-scanner/contents/"
           "runtime/r281-shadow-direction.json"
           "?ref=research%2Fr281-direction-inference-parity-20261123")
MAX_TARGET_DAYS = {"H1": 1/24, "H4": 4/24, "D1": 4, "W1": 7}
PARITY_SAMPLES = {"H1": 5633, "H4": 1422, "D1": 253, "W1": 51}

REASONS = {
    "2025_PARITY_PASS_2026_FORWARD_UNPROVEN": "Prediksi model R28.1 tersedia.",
    "RESEARCH_SIGNAL": "Prediksi model R28.1 tersedia.",
    "BELOW_THRESHOLD": "Skor BUY dan SELL belum memenuhi ambang riset.",
    "HEAD_CONFLICT": "Skor BUY dan SELL sama-sama memenuhi ambang; model menahan arah.",
    "TARGET_CANDLE_EXPIRED": "Target close prediksi sudah berakhir; menunggu hasil model terbaru.",
    "SOURCE_OR_TARGET_STALE": "Sumber atau target prediksi kedaluwarsa; menunggu pembaruan model.",
    "SOURCE_STALE": "Data sumber kedaluwarsa saat model diterbitkan.",
    "MODEL_SNAPSHOT_UNAVAILABLE": "Feed GitHub model gagal diakses atau snapshot tidak lolos validasi (raw dan API).",
    "CONTEMPORARY_PRICE_NOT_AVAILABLE": "Input harga broker saat ini belum tersedia.",
    "H1_CONTEXT_UNAVAILABLE": "Konteks H1 broker belum lengkap untuk model ini.",
    "LIVE_FEATURE_SCHEMA_MISMATCH": "Fitur model live tidak identik dengan replay.",

    "LATEST_COMPLETE_BROKER_BAR_UNAVAILABLE": "Candle broker tertutup belum lengkap untuk model.",
    "LIVE_HISTORY_GAP_OR_PRICE_SCALE": "Riwayat broker belum tersambung dengan data model.",
    "ECB_2026_UNAVAILABLE": "Input kurs ECB tahun berjalan belum tersedia.",
    "INVALID_SIGNAL_TIME": "Waktu sumber dan target model tidak sesuai.",
    "INVALID_TARGET_HORIZON": "Horizon target model tidak sesuai timeframe.",
    "INVALID_MODEL_SCORES": "Skor model atau harga sumber tidak valid.",
}


def reason_text(reason):
    return REASONS.get(reason, "Menunggu model/data R28.1: " + str(reason))


def moment(value):
    t = pd.Timestamp(value)
    if t.tzinfo is None:
        raise ValueError("R281_NAIVE_TIME")
    return t.tz_convert("UTC")


def blank(reason="WAIT_DATA"):
    return {
        "state": "WAIT_DATA", "reason": reason, "direction": "WAIT",
        "target": None, "issued": None, "closed": None, "model": None,
        "source": None, "buy_score": None, "sell_score": None,
        "expired_at": None, "previous_direction": None,
        "execution_authority": False,
    }


def validate(payload, *, now):
    now = moment(now)
    if (not isinstance(payload, dict) or payload.get("contract") != CONTRACT
            or payload.get("symbol") != "XAUUSD" or payload.get("source") != SOURCE
            or payload.get("model_lineage") != LINEAGE
            or payload.get("research_only") is not True
            or payload.get("execution_authority") is not False
            or payload.get("execution_influence") is not False
            or payload.get("historical_parity") != "PASS_ALL_FOUR_2025"):
        raise ValueError("R281_SHADOW_PACKET_CONTRACT_INVALID")
    published = moment(payload["as_of"])
    if not 0 <= (now - published).total_seconds() <= 8 * 86400:
        raise ValueError("R281_SNAPSHOT_INVALID_PUBLICATION_TIME")
    rows = payload.get("rows")
    if not isinstance(rows, dict) or set(rows) != set(MAX_TARGET_DAYS):
        raise ValueError("R281_SHADOW_TF_SCHEMA_MISMATCH")
    result = {tf: blank() for tf in MAX_TARGET_DAYS}
    for tf, row in rows.items():
        if (not isinstance(row, dict)
                or row.get("execution_authority") is not False
                or row.get("execution_influence") is not False
                or row.get("model_id") != "R281_RECONSTRUCTED_2026_" + tf
                or not re.fullmatch("[0-9a-f]{64}", str(row.get("model_sha256") or ""))
                or row.get("historical_2025_parity") != PARITY_SAMPLES[tf]):
            raise ValueError("R281_MODEL_LINEAGE_NOT_VERIFIED:" + tf)
        result[tf] = {**blank(str(row.get("reason") or "WAIT_DATA")),
                      "issued": published.isoformat(), "model": row["model_id"]}
        if row.get("state") not in ("R281_RECONSTRUCTED_SHADOW", "R281_MODEL_ABSTAIN"):
            continue
        abstain = row.get("state") == "R281_MODEL_ABSTAIN"
        if (abstain and (row.get("direction") != "WAIT"
                         or row.get("reason") not in ("BELOW_THRESHOLD", "HEAD_CONFLICT"))
                or not abstain and row.get("direction") not in ("BUY", "SELL")):
            continue
        issued, close, target, observed = (
            published, moment(row["closed_at"]), moment(row["target_close_at"]),
            moment(row["observed_at"])
        )
        # Source was fresh at publication; target cannot have already closed.
        if now >= target:
            result[tf]["reason"] = "TARGET_CANDLE_EXPIRED"
            # Display-only audit. Never restore an expired model as an active
            # BUY/SELL; downstream entry engines use direction == WAIT.
            result[tf]["expired_at"] = target.isoformat()
            result[tf]["previous_direction"] = row["direction"] if not abstain else None
            continue
        if not (close <= observed <= issued <= now < target):
            result[tf]["reason"] = "INVALID_SIGNAL_TIME"
            continue
        if not (0 < (target-close).total_seconds() <= MAX_TARGET_DAYS[tf]*86400):
            result[tf]["reason"] = "INVALID_TARGET_HORIZON"
            continue
        if (issued-observed).total_seconds() > 300:
            result[tf]["reason"] = "SOURCE_STALE"
            continue
        prices = (row.get("last_close"), row.get("buy_head_score"), row.get("sell_head_score"))
        if any(type(x) not in (float,int) or not math.isfinite(x) for x in prices):
            result[tf]["reason"] = "INVALID_MODEL_SCORES"
            continue
        if not (prices[0] > 0 and 0 <= prices[1] <= 1 and 0 <= prices[2] <= 1):
            result[tf]["reason"] = "INVALID_MODEL_SCORES"
            continue
        result[tf] = {
            "state": "MODEL_ABSTAIN" if abstain else "RECONSTRUCTED_SHADOW",
            "reason": row["reason"] if abstain else "2025_PARITY_PASS_2026_FORWARD_UNPROVEN",
            "direction": row["direction"], "target": target.isoformat(),
            "issued": issued.isoformat(), "closed": close.isoformat(),
            "model": row["model_id"], "source": SOURCE,
            "buy_score": float(prices[1]), "sell_score": float(prices[2]),
            "execution_authority": False,
        }
    return result


def _read_snapshot(request, *, opener, api=False):
    with opener(request, timeout=6) as resp:
        raw = resp.read(256_001)
    if len(raw) > 256_000:
        raise ValueError("R281_SHADOW_TOO_LARGE")
    doc = json.loads(raw)
    if api:
        # GitHub Contents API is a redundant transport for the same exact
        # immutable branch/path; never substitute a different model/source.
        if (not isinstance(doc, dict) or doc.get("encoding") != "base64"
                or not isinstance(doc.get("content"), str)):
            raise ValueError("R281_GITHUB_API_CONTENT_INVALID")
        try:
            raw = base64.b64decode(doc["content"], validate=False)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("R281_GITHUB_API_BASE64_INVALID") from exc
        if len(raw) > 256_000:
            raise ValueError("R281_SHADOW_TOO_LARGE")
        doc = json.loads(raw)
    return doc


def fetch(*, now=None, opener=urlopen):
    now = moment(now or datetime.now(UTC))
    headers={"Cache-Control": "no-cache", "User-Agent": "RIZAN-R281-shadow-viewer/1"}
    raw_req=Request(URL + "?minute=" + str(int(now.timestamp() // 60)),headers=headers)
    try:
        return validate(_read_snapshot(raw_req, opener=opener), now=now)
    except (OSError, TimeoutError, ValueError, TypeError, KeyError):
        # A raw CDN/network error must not turn an otherwise valid H4/W1
        # model into four misleading WAIT rows. Fall back to GitHub REST.
        # The contract, provenance, and candle expiry are ALWAYS enforced.
        api_req=Request(API_URL, headers={**headers,"Accept":"application/vnd.github+json"})
        return validate(_read_snapshot(api_req, opener=opener, api=True), now=now)
