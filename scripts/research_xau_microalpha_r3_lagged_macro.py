"""RIZAN MicroAlpha R3 historical lagged-macro-proxy ablation.

Uses public independently derived H1 FRED-lagged features as a market-regime
proxy, not a real-time US2Y/DXY feed. The dataset publisher states daily FRED
was lagged one day and USD broad index seven days to avoid publication leakage.
No LIVE broker data, orders or credentials.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

from fx_scanner.xau_microalpha_r3 import MicroSettings, build_features, replay
from research_xau_microalpha_r3_multiyear import (
    BEGIN, END_EXCLUSIVE, load_history, EXPECTED_SHA256,
)

H1_URL = (
    "https://huggingface.co/datasets/vichetkao/xauusd_dataset_2026/"
    "resolve/8ee2bd6/data/training/xauusd_H1_train.parquet"
)
H1_SHA256 = "c8bab69bcf2f4eae5ded177976187d6ddcbbb45ed92bffdf3cbfd76109b58a7b"
REQUIRED_MACRO = ("macro_DFII10_chg7d", "macro_DGS10_chg7d", "macro_DTWEXBGS_pct7d")


def load_lagged_macro() -> pd.DataFrame:
    request = Request(H1_URL, headers={"User-Agent": "RIZAN-Lagged-Macro-Research/1"})
    with urlopen(request, timeout=120) as response:
        payload = response.read(40_000_001)
    if len(payload) > 40_000_000 or hashlib.sha256(payload).hexdigest() != H1_SHA256:
        raise ValueError("UNPINNED_MACRO_DATASET_BYTES")
    raw = pd.read_parquet(io.BytesIO(payload))
    if "time_utc" not in raw or any(k not in raw for k in REQUIRED_MACRO):
        raise ValueError("LAGGED_MACRO_SCHEMA_MISSING")
    raw["asof"] = pd.to_datetime(raw["time_utc"], utc=True, errors="coerce")
    if raw["asof"].isna().any():
        raise ValueError("INVALID_MACRO_ASOF_TIMESTAMP")
    macro = raw[["asof", *REQUIRED_MACRO]].sort_values("asof").drop_duplicates("asof", keep="last")
    return macro.loc[macro["asof"].between(BEGIN - pd.Timedelta(days=15), END_EXCLUSIVE)].reset_index(drop=True)


def derive_macro_filters(features: pd.DataFrame, macro: pd.DataFrame) -> dict[str, pd.DataFrame]:
    # Publisher-lagged source data as-of H1 time; NO future FRED or USD proxy.
    m5 = pd.merge_asof(features.sort_values("closed_at"),
                       macro.sort_values("asof"), left_on="closed_at",
                       right_on="asof", direction="backward",
                       tolerance=pd.Timedelta(hours=2))
    real = pd.to_numeric(m5["macro_DFII10_chg7d"], errors="coerce")
    nominal = pd.to_numeric(m5["macro_DGS10_chg7d"], errors="coerce")
    broad = pd.to_numeric(m5["macro_DTWEXBGS_pct7d"], errors="coerce")
    # 7-day changes only; broad USD index is NOT licensed ICE DXY.
    long_strict = real.lt(0) & nominal.le(0) & broad.lt(0)
    short_strict = real.gt(0) & nominal.ge(0) & broad.gt(0)
    long_core = real.lt(0) & broad.lt(0)
    short_core = real.gt(0) & broad.gt(0)
    variants = {}
    for key, buy, sell in [
        ("R3_MACRO_STRICT_REAL_NOMINAL_USD", long_strict, short_strict),
        ("R3_MACRO_REAL_USD_CORE", long_core, short_core),
    ]:
        eligible = (m5["signal"].eq(1) & buy) | (m5["signal"].eq(-1) & sell)
        out = features.copy()
        out["signal"] = out["signal"].where(eligible.fillna(False), 0)
        variants[key] = out
    return variants


def run() -> dict:
    historical, integrity = load_history()
    technical = build_features(historical)
    macro = load_lagged_macro()
    variants = {"TECHNICAL_ONLY": technical}
    variants.update(derive_macro_filters(technical, macro))
    settings = MicroSettings()
    findings = {
        "contract": "RIZAN_XAU_MICROALPHA_R3_LAGGED_MACRO_ABLATION",
        "price_source_sha256": integrity["sha256"],
        "macro_source_sha256": H1_SHA256,
        "macro_source": H1_URL,
        "macro_semantics": (
            "Lagged FRED real yield and nominal yield 7d change, "
            "lagged H10 broad USD index (NOT ICE DXY). Daily +1d/USD +7d "
            "publisher backtest as-of policy; independent timestamp audit pending."
        ),
        "source_caveat": "PUBLIC_MID_OHLC_AND_LAGGED_DAILY_NOT_INTRADAY_NO_BROKER_TICKS",
        "initial_usd": 100, "leverage": 200,
        "price_rows": len(historical), "lagged_macro_rows": len(macro),
        "variants": {},
    }
    for name, frame in variants.items():
        summary, _ = replay(frame, settings, session="ASIA")
        year = {}
        for y in range(2019, 2027):
            sample = frame.loc[(frame["datetime"] >= pd.Timestamp(f"{y}-01-01T00:00:00Z"))
                               & (frame["datetime"] < pd.Timestamp(f"{y+1}-01-01T00:00:00Z"))]
            if len(sample) < 100:
                continue
            result, _ = replay(sample.reset_index(drop=True), settings, session="ASIA")
            year[str(y)] = {
                "equity_usd": result["ending_equity"],
                "return_pct": result["return_pct"],
                "trades": result["trades"],
                "profit_factor": result["profit_factor"],
                "closed_dd_pct": result["closed_dd_pct"],
            }
        findings["variants"][name] = {"continuous_compounding": summary,
                                      "separate_yearly_usd100_restarts": year}
        print(f"R3_MACRO_ABLATION {name} ending={summary['ending_equity']:.2f} "
              f"pf={summary['profit_factor']} DD={summary['closed_dd_pct']} "
              f"trades={summary['trades']}", flush=True)
    Path("microalpha_r3_macro_ablation.json").write_text(
        json.dumps(findings, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print("MACRO_ABLATION_COMPLETE microalpha_r3_macro_ablation.json", flush=True)
    return findings


if __name__ == "__main__":
    run()
