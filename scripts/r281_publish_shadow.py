"""Publish a fail-closed, read-only R28.1 SHADOW market-direction packet.

Only aggregate four parity-passing historical reports; no model pickle is
loaded, no execution adapters imported, and no orders/credentials included.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re

import pandas as pd

TF_FILES = {
    "H1": "r281-1h-shadow.json",
    "H4": "r281-4h-shadow.json",
    "D1": "r281-1D-shadow.json",
    "W1": "r281-1W-shadow.json",
}
CONTRACT = "RIZAN_R281_DIRECTION_SHADOW_SNAPSHOT_V1"


def time(value):
    t = pd.Timestamp(value)
    if t.tzinfo is None:
        raise ValueError("SHADOW_TIME_WITHOUT_TZ")
    return t.tz_convert("UTC")


def compose(root, *, now=None):
    root = Path(root)
    now = time(now or datetime.now(UTC))
    rows = {}
    for tf, filename in TF_FILES.items():
        p = root / filename
        if p.stat().st_size > 150_000:
            raise ValueError("SHADOW_REPORT_TOO_LARGE")
        r = json.loads(p.read_text())
        proof = r.get("historical_parity") or {}
        if (r.get("contract") != "RIZAN_R281_SHADOW_PARITY_V1" or r.get("tf") != tf
                or r.get("execution_authority") is not False
                or r.get("execution_influence") is not False
                or r.get("model_r28_live") is not False or not r.get("research_only")
                or proof.get("status") != "PASS" or proof.get("year") != 2025
                or proof.get("expected") != proof.get("recomputed")
                or not isinstance(proof.get("sample"), int) or proof["sample"] < 30
                or not re.fullmatch("[a-f0-9]{64}", str(r.get("model_sha256") or ""))):
            raise ValueError("R281_PROVENANCE_OR_PARITY_MISMATCH:" + tf)
        issued = time(r["generated_at"])
        if not -5 <= (now-issued).total_seconds() <= 1800:
            raise ValueError("R281_MODEL_ARTIFACT_STALE:" + tf)
        s = r.get("signal") or {}
        origin = r.get("market_source") or {}
        direction = s.get("direction") if s.get("direction") in ("BUY", "SELL") else "WAIT"
        valid = False
        target = closed = None
        if s.get("status") == "SHADOW_ONLY" and direction in ("BUY", "SELL"):
            if (s.get("source") != "CTRADER_MARKET_DATA_READ_ONLY"
                    or s.get("execution_authority") is not False
                    or origin.get("source") != "CTRADER_MARKET_DATA_READ_ONLY"):
                raise ValueError("R281_BROKER_SOURCE_CONTRACT:" + tf)
            closed, target = time(s["candle_closed_at"]), time(s["target_close_at"])
            observed = time(origin["as_of"])
            valid = closed <= observed <= now < target and 0 <= (now-observed).total_seconds() <= 300
        if not valid:
            direction = "WAIT"
        rows[tf] = {
            "direction": direction,
            "state": "R281_RECONSTRUCTED_SHADOW" if valid else "WAIT_DATA",
            "reason": s.get("reason") if valid else "SOURCE_OR_TARGET_STALE",
            "closed_at": closed.isoformat() if valid else None,
            "target_close_at": target.isoformat() if valid else None,
            "observed_at": origin.get("as_of") if valid else None,
            "model_id": "R281_RECONSTRUCTED_2026_" + tf,
            "policy_group": proof["group"], "model_sha256": r["model_sha256"],
            "historical_2025_parity": proof["sample"],
            "buy_head_score": s.get("buy_head_score") if valid else None,
            "sell_head_score": s.get("sell_head_score") if valid else None,
            "last_close": s.get("last_close") if valid else None,
            "execution_authority": False, "execution_influence": False,
        }
    return {
        "contract": CONTRACT, "symbol": "XAUUSD", "source": "CTRADER_MARKET_DATA_READ_ONLY",
        "as_of": now.isoformat(), "model_lineage": "R28.1_RECONSTRUCTED_SHADOW_NOT_FROZEN_LIVE",
        "historical_parity": "PASS_ALL_FOUR_2025",
        "execution_authority": False, "execution_influence": False,
        "research_only": True, "rows": rows,
        "warning": "Directional hypothesis only. Not calibrated to new broker, not a trade order, no forward win-rate claim.",
    }


if __name__ == "__main__":
    output = Path("runtime/r281-shadow-direction.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    result = compose("artifacts/r281_inference")
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({tf: {"direction": row["direction"], "state": row["state"]}
                      for tf, row in result["rows"].items()}), flush=True)
