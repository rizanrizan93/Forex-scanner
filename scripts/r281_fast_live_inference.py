"""Fast, read-only R28.1 inference from a parity-verified frozen model cache.

Training, historical replay and archive downloads run ONLY when the cache is
missing. Each fast invocation loads the cached refit (trained through 2025),
constructs live closed-candle features from the verified historical archive +
fresh public cTrader M1, then writes a new SHADOW report for the atomic
publisher. Never place broker orders or represent 2025 replay as 2026 alpha.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json

import joblib
import numpy as np
import pandas as pd

from r14_multitimeframe_direction import load_tf
from r281_live_shadow_parity import (
    CONTRACT, MAX_BARS, OUTPUT, REPORTS, contemporary_signal,
    extended_ecb, record,
)

SOURCES = {"1h": "H1", "4h": "H4", "1D": "D1", "1W": "W1"}
MIN_PARITY = {"1h": 5633, "4h": 1422, "1D": 253, "1W": 51}


def cache_paths(tf):
    if tf not in REPORTS:
        raise ValueError("R281_UNSUPPORTED_TF")
    return (
        OUTPUT / f"r281-{tf}-reconstructed-model.joblib",
        OUTPUT / f"r281-{tf}-shadow.json",
    )


def validated_cache(tf):
    """Trust only a cached refit whose file hash, schema and 2025 proof match."""
    model_path, report_path = cache_paths(tf)
    proof = json.loads(report_path.read_text())
    raw = model_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    _, annual, family, policy = record(tf)
    parity = proof.get("historical_parity") or {}
    if (
        proof.get("contract") != CONTRACT or proof.get("tf") != SOURCES[tf]
        or proof.get("execution_authority") is not False
        or proof.get("execution_influence") is not False
        or proof.get("research_only") is not True
        or proof.get("model_r28_live") is not False
        or proof.get("model_sha256") != digest
        or parity.get("status") != "PASS"
        or parity.get("year") != 2025
        or parity.get("group") != family
        or parity.get("sample") != MIN_PARITY[tf]
        or parity.get("expected") != parity.get("recomputed")
        or proof.get("training_end") != "2025-12-31"
        or any(proof.get("refit_policy", {}).get(s) != policy[s + "_config"]
               for s in ("BUY", "SELL"))
    ):
        raise ValueError("R281_FROZEN_MODEL_CACHE_PROVENANCE_INVALID")
    # Hash and provenance are checked before loading our own joblib artifact.
    model = joblib.load(model_path)
    if (
        not isinstance(model, dict) or model.get("tf") != tf
        or model.get("training_end_exclusive") != "2026-01-01T00:00:00+00:00"
        or not isinstance(model.get("features"), list)
        or len(model["features"]) != proof.get("feature_count")
        or model.get("selected_policy") != proof["refit_policy"]
        or set(model.get("heads", {})) != {"BUY", "SELL"}
    ):
        raise ValueError("R281_MODEL_FEATURE_CACHE_CONTRACT_INVALID")
    return model, proof


def run(tf, now=None):
    now = pd.Timestamp(now or datetime.now(UTC))
    if now.tzinfo is None:
        raise ValueError("R281_FAST_NOW_REQUIRES_TIMEZONE")
    model, cached_report = validated_cache(tf)
    # This is only loading historical OHLC for feature continuity. It does
    # NOT refit nor rerun the 2025 parity models on every hourly forecast.
    d, *_ = load_tf(tf)
    if len(d) > MAX_BARS[tf]:
        raise ValueError("R281_FAST_SOURCE_SIZE_EXCEEDED")
    if tf in ("1h", "4h"):
        fx, fx_meta = None, {"status": "NOT_USED_PRICE_ONLY"}
    else:
        fx, fx_meta = extended_ecb()

    if fx_meta["status"] in ("ECB_2026_APPENDED", "NOT_USED_PRICE_ONLY"):
        signal, market = contemporary_signal(
            tf, d, fx, model["heads"], model["selected_policy"], now,
            model["features"])
    else:
        signal, market = (
            {"status": "WAIT_DATA", "direction": "WAIT",
             "reason": "ECB_2026_UNAVAILABLE", "source": "CTRADER_MARKET_DATA_READ_ONLY",
             "candle_closed_at": None, "target_close_at": None,
             "buy_head_score": None, "sell_head_score": None,
             "execution_authority": False},
            {"status": "UNAVAILABLE"},
        )

    result = {
        **cached_report,
        "generated_at": now.isoformat(),
        "ecb_source": fx_meta,
        "market_source": market,
        "signal": signal,
        "fast_inference": True,
        "inference_lineage": "UNCHANGED_2025_REFIT_2026_READONLY_MODEL",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / f"r281-{tf}-shadow.json").write_text(
        json.dumps(result, indent=2, allow_nan=False))
    print(json.dumps({"tf": tf, "fast_inference": True,
                      "model_sha256": result["model_sha256"],
                      "signal": signal, "source": market}), flush=True)
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", required=True, choices=list(REPORTS))
    args = ap.parse_args()
    run(args.tf)
