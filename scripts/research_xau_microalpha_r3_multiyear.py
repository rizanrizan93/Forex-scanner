"""Multiyear third-party historical M5 RESEARCH, no broker orders or secrets.

The study intentionally excludes macro uplift because no point-in-time intraday
DXY/rates history is provided. Pin source SHA256 and guard data integrity.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import replace
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

from fx_scanner.xau_microalpha_r3 import MicroSettings, build_features, replay

SOURCE = (
    "https://huggingface.co/datasets/vichetkao/xauusd_dataset_2026/"
    "resolve/8ee2bd6/data/bars_reference/xauusd_M5.parquet"
)
EXPECTED_SHA256 = "43c0bf9e15bc3c6b94b707112ebb7623571a7653cacfcbf4abb8cbd51247b3a5"
BEGIN = pd.Timestamp("2019-01-01T00:00:00Z")
END_EXCLUSIVE = pd.Timestamp("2026-09-25T00:00:00Z")


def load_history() -> tuple[pd.DataFrame, dict]:
    request = Request(SOURCE, headers={"User-Agent": "RIZAN-MicroAlpha-R3-Historical/1"})
    # Source is approx 24.4MB, refuse unexpectedly large or unpinned bytes.
    with urlopen(request, timeout=120) as response:
        raw = response.read(40_000_001)
    if len(raw) > 40_000_000:
        raise ValueError("MULTIYEAR_DATA_EXCEEDS_BOUND")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError("UNEXPECTED_DATASET_SHA256")
    frame = pd.read_parquet(io.BytesIO(raw))
    columns = {str(k).lower(): k for k in frame.columns}
    time_key = next((columns[k] for k in ("time_utc", "datetime", "timestamp", "time", "date")
                     if k in columns), None)
    if time_key is None:
        if isinstance(frame.index, pd.DatetimeIndex):
            frame = frame.reset_index()
            columns = {str(k).lower(): k for k in frame.columns}
            time_key = next((columns[k] for k in ("time_utc", "datetime", "timestamp", "time", "date", "index")
                             if k in columns), None)
    if time_key is None:
        raise ValueError("NO_TIME_COLUMN_IN_PUBLIC_DATA")
    timestamps = pd.to_datetime(frame[time_key], utc=True, errors="coerce")
    if timestamps.isna().any():
        raise ValueError("MISSING_SOURCE_TIMESTAMPS")
    frame = frame.loc[(timestamps >= BEGIN) & (timestamps < END_EXCLUSIVE)].copy()
    # Add canonical timezone-aware name without assuming source timezone conversion.
    frame["datetime"] = timestamps.loc[frame.index]
    frame.columns = [str(c).lower() for c in frame.columns]
    frame = frame[["datetime", "open", "high", "low", "close"]]
    frame = frame.sort_values("datetime").reset_index(drop=True)
    info = {
        "sha256": digest,
        "raw_bytes": len(raw),
        "first": str(frame["datetime"].iloc[0]),
        "last": str(frame["datetime"].iloc[-1]),
        "rows": len(frame),
        "max_abs_5min_close_pct": round(
            100 * (frame["close"].pct_change().abs().max()), 4),
        "duplicate_timestamps": int(frame["datetime"].duplicated().sum()),
        "impossible_bars": int((
            (frame["low"] > frame[["open", "close"]].min(axis=1))
            | (frame["high"] < frame[["open", "close"]].max(axis=1))
            | (frame["low"] <= 0)
        ).sum()),
    }
    if info["rows"] < 150_000 or info["duplicate_timestamps"] or info["impossible_bars"]:
        raise ValueError("HISTORICAL_PRICE_SERIES_FAILED_INTEGRITY")
    return frame, info


def run() -> dict:
    raw, integrity = load_history()
    features = build_features(raw)
    base = MicroSettings()
    configs = {
        "R3_ASIA_005LOT_CAP_RISK5_SL1": (base, "ASIA"),
        "R3_ASIA_005LOT_CAP_RISK5_SL05": (replace(base, stop_atr=.5), "ASIA"),
        "R3_ASIA_HYPOTHETICAL_MICROLOT001_RISK2_SL1": (
            replace(base, risk_fraction=.02, minimum_lot=.001, lot_step=.001),
            "ASIA",
        ),
        "R3_ALL_005LOT_CAP_RISK5_SL1": (base, "ALL"),
    }
    findings = {
        "contract": "RIZAN_R3_MULTYEAR_RESEARCH_ONLY",
        "dataset": "PUBLIC_MID_OHLC_NOT_FP_MARKETS_TICKS",
        "source": SOURCE, "integrity": integrity,
        "scope": f"{integrity['first']} through {integrity['last']} (actual available source range)",
        "historical_macro_join": "NOT_RUN_NO_POINT_IN_TIME_DXY_RATES",
        "leverage": 200, "starting_equity": 100,
        "simulated_fixed_roundtrip_friction_usd_per_oz": base.friction_roundtrip_usd_per_oz,
        "actual_fp_margin_commission_swap": "NOT_VERIFIED",
        "variants": {},
    }
    for name, (cfg, session) in configs.items():
        full, ledger = replay(features, cfg, session=session)
        year_metrics = {}
        for year in range(2019, 2027):
            sample = features.loc[
                (features["datetime"] >= pd.Timestamp(f"{year}-01-01T00:00:00Z"))
                & (features["datetime"] < pd.Timestamp(f"{year+1}-01-01T00:00:00Z"))
            ].reset_index(drop=True)
            if sample.empty:
                continue
            stats, _ = replay(sample, cfg, session=session)
            year_metrics[str(year)] = {
                "ending": stats["ending_equity"], "return_pct": stats["return_pct"],
                "trades": stats["trades"], "profit_factor": stats["profit_factor"],
                "closed_dd_pct": stats["closed_dd_pct"],
                "intrabar_dd_pct": stats["ohlc_intrabar_dd_estimate_pct"],
            }
        findings["variants"][name] = {"full_compounded": full, "annual_restarts_at_100": year_metrics}
        print(
            f"R3_MULTIYEAR_VARIANT {name} ending={full['ending_equity']:.2f} "
            f"return={full['return_pct']:+.2f}% pf={full['profit_factor']} "
            f"trades={full['trades']} dd={full['closed_dd_pct']:.2f} "
            f"float_ohlc_dd={full['ohlc_intrabar_dd_estimate_pct']:.2f}",
            flush=True,
        )
    output = Path(os.environ.get("RIZAN_MICROALPHA_MULTIYEAR_OUTPUT",
                                 "microalpha_r3_multiyear.json"))
    output.write_text(json.dumps(findings, indent=2, default=str) + "\n", encoding="utf-8")
    print("MULTIYEAR_RESEARCH_COMPLETE " + str(output), flush=True)
    return findings


if __name__ == "__main__":
    run()
