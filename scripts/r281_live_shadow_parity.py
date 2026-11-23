"""Rebuild the R28.1 selected 2025 directional policies; prove replay parity.

Research-only, market-data only. This script NEVER writes orders or alters cBots.
The originally selected policies were tuned on REUSED historical folds; replay
parity is an implementation requirement, not evidence of forward profitability.

2026 outputs, when present, are shadow forecasts from the ORIGINAL historical
source archive (not a verified contemporary broker feed). Never treat as live.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import io
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from r14_multitimeframe_direction import load_tf
from r16_direction_complexity import features
from r281_ecb_usd_context import CURRENCIES, cross, XML

REPORTS = {
    "1h": "14733416718/r281-1h-fx.json",
    "4h": "14733207916/r281-4h-fx.json",
    "1D": "14733406717/r281-1D-fx.json",
    "1W": "14732913472/r281-1W-fx.json",
}
SIZES = {"1h": "1h", "4h": "4h", "1D": "1D", "1W": "7D"}
MAX_BARS = {"1h": 90000, "4h": 25000, "1D": 10000, "1W": 3000}
ROOT = Path("research/archive/xau_r281/44970328847")
OUTPUT = Path("artifacts/r281_inference")
OUTPUT.mkdir(parents=True, exist_ok=True)
CONTRACT = "RIZAN_R281_SHADOW_PARITY_V1"


def record(tf):
    path = ROOT / REPORTS[tf]
    data = json.loads(path.read_text())
    year = next((a for a in data["annual"] if a["year"] == 2025), None)
    if not year or year["status"] != "EVALUATED":
        raise ValueError("R281_FROZEN_ANNUAL_CONFIG_MISSING")
    family = {"1h": "price", "4h": "price", "1D": "price_fx", "1W": "fx"}[tf]
    policy = year["policies"][family]
    for side in ("BUY", "SELL"):
        if policy[side + "_config"] is None:
            raise ValueError("R281_SELECTED_SIDE_NOT_AVAILABLE:" + tf + ":" + side)
    return data, year, family, policy


def extended_ecb():
    """Preserve the immutable 2018-25 ECB artifact; append ONLY 2026 rows.

    No latest revision may silently rewrite the historical replay inputs.
    ECB rates are a daily proxy with next-day availability, NOT real-time DXY.
    """
    from r281_ecb_usd_context import loadfx
    fixed = loadfx()
    if not fixed.index.is_monotonic_increasing or fixed.index.has_duplicates:
        raise ValueError("R281_ECB_ARCHIVE_UNSORTED")
    if fixed.index.max().year != 2025:
        raise ValueError("R281_ECB_ARCHIVE_UNEXPECTED_END")
    try:
        req = Request(XML, headers={"User-Agent": "RIZAN-R281-research-readonly/1"})
        with urlopen(req, timeout=35) as resp:
            raw = resp.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError("ECB_RESPONSE_OVERSIZED")
        rows = []
        for element in ET.fromstring(raw).iter():
            date = element.attrib.get("time")
            if not date or not date.startswith("2026-"):
                continue
            row = {"date": date}
            for child in element:
                name = child.attrib.get("currency")
                if name in CURRENCIES:
                    row[name] = float(child.attrib["rate"])
            if set(CURRENCIES).issubset(row):
                rows.append(row)
        if not rows:
            raise ValueError("ECB_2026_DATA_NOT_AVAILABLE")
        current = pd.DataFrame(rows).set_index("date")
        current.index = pd.to_datetime(current.index, utc=True)
        current = current.sort_index()[CURRENCIES].astype(float)
        if current.index.has_duplicates or not np.isfinite(current.to_numpy()).all():
            raise ValueError("ECB_2026_INVALID")
        fx = pd.concat([fixed, current])
        if fx.index.has_duplicates or not fx.index.is_monotonic_increasing:
            raise ValueError("ECB_HISTORY_COLLISION")
        return fx, {"status": "ECB_2026_APPENDED", "last": current.index.max().isoformat(),
                    "rows_2026": len(current), "sha256": hashlib.sha256(raw).hexdigest()}
    except (OSError, ValueError, ET.ParseError, TimeoutError) as exc:
        # A stale 2018-25 source can prove replay parity but can NEVER score 2026.
        return fixed, {"status": "ECB_2026_UNAVAILABLE", "reason": type(exc).__name__}


def classifier(C):
    return make_pipeline(StandardScaler(), LogisticRegression(C=float(C), max_iter=500))


def resolved(y, B, S):
    B, S = B & ~S, S & ~B
    return {
        "BUY": {"n": int(B.sum()), "correct": int((y[B] == 1).sum())},
        "SELL": {"n": int(S.sum()), "correct": int((y[S] == 0).sum())},
    }


def enforce_replay_parity(tf, family, d, y, valid, times, x, policy, annual):
    """Exactly reproduce the historical 2025 test split, fits and outcomes."""
    start = pd.Timestamp("2025-01-01", tz="UTC")
    validation = pd.Timestamp("2024-01-01", tz="UTC")
    end = pd.Timestamp("2026-01-01", tz="UTC")
    mature = pd.Series(times, index=d.index).shift(-1)
    train = valid & (times < validation) & (mature < validation).to_numpy()
    test = valid & (times >= start) & (times < end) & (mature < end).to_numpy()
    if test.sum() != annual["matched"] or train.sum() < 120:
        raise AssertionError(f"R281_MATCHED_SAMPLE_MISMATCH tf={tf} test={test.sum()} archived={annual['matched']} train={train.sum()}")
    arr = x.to_numpy(float)
    heads = {}
    mask = {}
    for side, label in (("BUY", 1), ("SELL", 0)):
        config = policy[side + "_config"]
        model = classifier(config["C"])
        model.fit(arr[train], (y[train] == label).astype(int))
        p = model.predict_proba(arr[test])[:, 1]
        mask[side] = p >= config["threshold"]
        heads[side] = {"C": config["C"], "threshold": config["threshold"]}
    got = resolved(y[test], mask["BUY"], mask["SELL"])
    expected = {side: {"n": policy[side]["n"], "correct": policy[side]["correct"]}
                for side in ("BUY", "SELL")}
    if got != expected:
        raise AssertionError(f"R281_2025_PARITY_MISMATCH tf={tf} got={got} expected={expected}")
    return {"status": "PASS", "year": 2025, "sample": int(test.sum()),
            "group": family, "expected": expected, "recomputed": got,
            "selected_configs": heads}


def run(tf, now=None):
    now = pd.Timestamp(now or datetime.now(UTC))
    if now.tzinfo is None:
        raise ValueError("NOW_TZ_REQUIRED")
    data, annual, family, policy = record(tf)
    d, z, _, y, eligible, times = load_tf(tf)
    if len(d) > MAX_BARS[tf]:
        raise ValueError("PRICE_SOURCE_SIZE_EXCEEDED")
    fx, fx_meta = extended_ecb()
    p = features(z)
    q = cross(fx, d, times, tf)
    if len(q) != len(p) or not q.index.equals(p.index):
        raise AssertionError("R281_FEATURE_INDEX_PARITY")
    # Replicate the original R28.1 common-sample policy: ALL price/fx columns
    # must be finite even for the price-only group.
    x = pd.concat([p, q], axis=1) if family == "price_fx" else q if family == "fx" else p
    eligible = eligible & (times.year >= 2019) & (times.year <= 2025)
    clean = np.isfinite(p.to_numpy(float)).all(axis=1) & np.isfinite(q.to_numpy(float)).all(axis=1)
    valid = eligible & clean
    proof = enforce_replay_parity(tf, family, d, y, valid, times, x, policy, annual)

    # Refit on label-mature, eligible 2019-2025 data. This is a NEW 2026
    # reconstruction using frozen 2025 configs, not the original 2025 model.
    end = pd.Timestamp("2026-01-01", tz="UTC")
    mature = pd.Series(times, index=d.index).shift(-1)
    tr = valid & (mature < end).to_numpy()
    if tr.sum() < 120:
        raise AssertionError("R281_REFIT_TRAIN_TOO_SMALL")
    X = x.to_numpy(float)
    fitted, saved = {}, {}
    for side, label in (("BUY", 1), ("SELL", 0)):
        cfg = policy[side + "_config"]
        model = classifier(cfg["C"])
        model.fit(X[tr], (y[tr] == label).astype(int))
        fitted[side] = model
        saved[side] = cfg

    buffer = io.BytesIO()
    joblib.dump({"heads": fitted, "selected_policy": saved, "features": list(x.columns),
                 "training_end_exclusive": end.isoformat(), "tf": tf}, buffer)
    model_bytes = buffer.getvalue()
    sha = hashlib.sha256(model_bytes).hexdigest()
    (OUTPUT / f"r281-{tf}-reconstructed-model.joblib").write_bytes(model_bytes)

    signal = {"status": "WAIT_DATA", "direction": "WAIT", "reason": "CURRENT_DATA_NOT_ADMISSIBLE",
              "candle_closed_at": None, "target_close_at": None,
              "buy_head_score": None, "sell_head_score": None}
    full = np.isfinite(x.to_numpy(float)).all(axis=1)
    latest = np.flatnonzero((times.year >= 2026) & (times <= now) & full)
    if fx_meta["status"] != "ECB_2026_APPENDED":
        signal["reason"] = "ECB_2026_UNAVAILABLE"
    elif len(latest):
        k = int(latest[-1])
        closed = pd.Timestamp(times[k])
        target = closed + pd.Timedelta(SIZES[tf])
        if now < target and 0 <= (now - closed).total_seconds():
            point = X[k:k+1]
            b = float(fitted["BUY"].predict_proba(point)[0,1])
            s = float(fitted["SELL"].predict_proba(point)[0,1])
            B = b >= float(saved["BUY"]["threshold"])
            S = s >= float(saved["SELL"]["threshold"])
            direction = "BUY" if B and not S else "SELL" if S and not B else "WAIT"
            signal.update(status="SHADOW_ONLY", direction=direction,
                          reason="HEAD_CONFLICT" if B and S else "BELOW_THRESHOLD" if not B and not S else "RESEARCH_SIGNAL",
                          candle_closed_at=closed.isoformat(), target_close_at=target.isoformat(),
                          buy_head_score=b, sell_head_score=s,
                          last_close=float(d.c.iloc[k]), source="HISTORICAL_SOURCE_ARCHIVE_2026_NOT_BROKER")
        else:
            signal["reason"] = "TARGET_CANDLE_EXPIRED"
    else:
        signal["reason"] = "HISTORICAL_2026_PRICE_NOT_FRESH"
    result = {
        "contract": CONTRACT, "tf": {"1h": "H1", "4h": "H4", "1D": "D1", "1W": "W1"}[tf],
        "origin": "R28.1 RECONSTRUCTED 2026 SHADOW", "research_only": True,
        "model_r28_live": False, "execution_authority": False, "execution_influence": False,
        "model_sha256": sha, "feature_count": len(x.columns),
        "training_rows": int(tr.sum()), "training_end": "2025-12-31",
        "refit_policy": saved, "historical_parity": proof,
        "archived_2025": policy["BUY"], "archived_2025_sell": policy["SELL"],
        "ecb_source": fx_meta, "generated_at": now.isoformat(), "signal": signal,
        "limitations": ["2025 performance is historical reused-fold evaluation; not forward evidence",
                        "R28.1 replay source FX/ECB proxies not point-in-time audited",
                        "2026 price input is archived, not live cTrader; no manual order authority",
                        "Model refit through 2025 is distinct from original 2025 fitted instance"],
    }
    (OUTPUT / f"r281-{tf}-shadow.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    print(json.dumps({"tf": tf, "parity": proof["status"], "sample": proof["sample"],
                      "model_sha256": sha, "signal": signal, "ecb": fx_meta["status"]}), flush=True)
    return result


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--tf", choices=list(REPORTS), required=True)
    args = a.parse_args()
    run(args.tf)
