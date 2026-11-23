"""Read-only R28.1 reconstructed inference snapshot, independent of cBot.

The R28.1 replay selected annual models were reconstructed and historically
parity-checked. This is a SHADOW feed, not a frozen production model, calibrated
win rate, execution advice, or evidence of independent 2026 forward precision.
"""
from __future__ import annotations

from datetime import UTC, datetime
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
MAX_TARGET_DAYS = {"H1": 1/24, "H4": 4/24, "D1": 4, "W1": 7}
PARITY_SAMPLES = {"H1": 5633, "H4": 1422, "D1": 253, "W1": 51}


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
        if row.get("state") != "R281_RECONSTRUCTED_SHADOW":
            continue
        if row.get("direction") not in ("BUY", "SELL"):
            continue
        issued, close, target, observed = (
            published, moment(row["closed_at"]), moment(row["target_close_at"]),
            moment(row["observed_at"])
        )
        # Source was fresh at publication; target cannot have already closed.
        if not (close <= observed <= issued <= now < target):
            continue
        if not (0 < (target-close).total_seconds() <= MAX_TARGET_DAYS[tf]*86400):
            continue
        if (issued-observed).total_seconds() > 300:
            continue
        prices = (row.get("last_close"), row.get("buy_head_score"), row.get("sell_head_score"))
        if any(type(x) not in (float,int) or not math.isfinite(x) for x in prices):
            continue
        if not (prices[0] > 0 and 0 <= prices[1] <= 1 and 0 <= prices[2] <= 1):
            continue
        result[tf] = {
            "state": "RECONSTRUCTED_SHADOW",
            "reason": "2025_PARITY_PASS_2026_FORWARD_UNPROVEN",
            "direction": row["direction"], "target": target.isoformat(),
            "issued": issued.isoformat(), "closed": close.isoformat(),
            "model": row["model_id"], "source": SOURCE,
            "buy_score": float(prices[1]), "sell_score": float(prices[2]),
            "execution_authority": False,
        }
    return result


def fetch(*, now=None, opener=urlopen):
    now = moment(now or datetime.now(UTC))
    req = Request(URL + "?minute=" + str(int(now.timestamp() // 60)),
                  headers={"Cache-Control": "no-cache",
                           "User-Agent": "RIZAN-R281-shadow-viewer/1"})
    with opener(req, timeout=6) as resp:
        raw = resp.read(256_001)
    if len(raw) > 256_000:
        raise ValueError("R281_SHADOW_TOO_LARGE")
    return validate(json.loads(raw), now=now)
