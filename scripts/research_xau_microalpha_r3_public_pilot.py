"""Public, reproducible M5 pilot. No broker credentials; no LIVE endpoints."""
from __future__ import annotations

import io
import json
from dataclasses import replace
from datetime import UTC, datetime
from urllib.request import Request, urlopen

import pandas as pd

from fx_scanner.xau_microalpha_r3 import MicroSettings, build_features, replay

SOURCE = (
    "https://raw.githubusercontent.com/Sai310421/xauusd-data/"
    "d27c59d23c023e0d02f5dc6fffd57850bac9d197/"
    "csv/XAUUSD/XAUUSD_M5_2026Q1Q2.csv"
)
CUTOFF = pd.Timestamp("2026-04-01T00:00:00Z")


def run() -> dict:
    req = Request(SOURCE, headers={"User-Agent": "RIZAN-MicroAlpha-R3-Reproducible/1"})
    with urlopen(req, timeout=25) as res:
        payload = res.read(2_000_001)
    if len(payload) > 2_000_000:
        raise ValueError("PUBLIC_CSV_TOO_LARGE")
    raw = pd.read_csv(io.BytesIO(payload))
    features = build_features(raw)
    first = features.iloc[0]["datetime"]
    last = features.iloc[-1]["datetime"]
    if not (len(features) == 17371 and first == pd.Timestamp("2026-02-25T00:00:00Z")
            and last == pd.Timestamp("2026-05-26T00:00:00Z")):
        raise ValueError("PUBLIC_DATASET_UNEXPECTED_VERSION_OR_PERIOD")
    base = MicroSettings()
    variants = {
        "R3_ASIA_RISK5_SL1ATR": (base, "ASIA"),
        "R3_ASIA_RISK5_SL05ATR": (replace(base, stop_atr=.5), "ASIA"),
        "R3_ASIA_RISK2_SL1ATR": (replace(base, risk_fraction=.02), "ASIA"),
        "R3_ALL_RISK5_SL1ATR": (base, "ALL"),
        "R3_ASIA_RISK2_001_MICROLOT_HYPOTHETICAL": (
            replace(base, risk_fraction=.02, minimum_lot=.001, lot_step=.001), "ASIA"),
    }
    report = {
        "contract": "RIZAN_XAU_MICROALPHA_R3_PUBLIC_PILOT_V1",
        "source": SOURCE, "rows": len(raw),
        "start_utc": first.isoformat(), "last_utc": last.isoformat(),
        "train_before": CUTOFF.isoformat(),
        "assumptions": {
            "account": "USD100 compounded equity, leverage 1:200",
            "min_lot_assumed": base.minimum_lot,
            "lot_oz_assumed": base.lot_size_oz,
            "lot_step_assumed": base.lot_step,
            "roundtrip_cost_per_oz_usd_assumed": base.friction_roundtrip_usd_per_oz,
            "trade_gate": "Risk <=5% equity AND initial margin <=50% equity",
            "quote_data": "PUBLIC_MID_OHLC_M5_NOT_BROKER_BID_ASK_TICK",
            "macro_data": "NOT_AVAILABLE_POINT_IN_TIME_NO_MACRO_BACKTEST",
        },
        "variants": {},
    }
    for name, (cfg, session) in variants.items():
        # Replays restart with USD100; train and holdout are comparisons,
        # not a stitched full-equity curve with carryover compounding.
        windows = {
            "development": features.loc[features["datetime"] < CUTOFF].reset_index(drop=True),
            "holdout": features.loc[features["datetime"] >= CUTOFF].reset_index(drop=True),
            "full": features,
        }
        report["variants"][name] = {}
        for label, panel in windows.items():
            out, ledger = replay(panel, cfg, session=session)
            report["variants"][name][label] = out
    print(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
