"""Reproducible 2019–Jan 2026 R4 $100 liquidity sweep study.

Use immutable, SHA-checked public M5 OHLC from the R3 research loader and
publication-lagged daily USD/real-yield series for ablation. No trading access.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pandas as pd

from fx_scanner.xau_microalpha_r4 import (
    CONTRACT, R4Settings, apply_lagged_macro_filter, backtest,
    build_liquidity_signals,
)
from research_xau_microalpha_r3_multiyear import load_history
from research_xau_microalpha_r3_lagged_macro import load_lagged_macro

OUTPUT = Path("microalpha_r4_2019_2026_research.json")
WINDOWS = {
    "DEVELOPMENT_2019_2022": ("2019-01-01", "2023-01-01"),
    "VALIDATION_2023_2024": ("2023-01-01", "2025-01-01"),
    "RECENT_2025_JAN2026": ("2025-01-01", "2026-01-10"),
}

# Fixed structural hypotheses, not optimized against the full data.
TECHNICAL_MODELS = {
    "R4_PREASIA_OPEN_0608": ("ASIA_OPEN_06_08", "NONE"),
    "R4_PREASIA_OPEN_M15": ("ASIA_OPEN_06_08", "M15"),
    "R4_ROLL12_MSS": ("ROLL12", "NONE"),
    "R4_ROLL12_M15": ("ROLL12", "M15"),
    "R4_ROLL24_H1": ("ROLL24", "H1"),
}
MACRO_BASELINE = "R4_PREASIA_OPEN_0608"


def _metrics(data, cfg, *, begin=None, end=None):
    summary, ledger = backtest(
        data, cfg, session="ASIA", window_start=begin, window_end=end
    )
    return summary


def run():
    raw, integrity = load_history()
    assert integrity["sha256"] == "43c0bf9e15bc3c6b94b707112ebb7623571a7653cacfcbf4abb8cbd51247b3a5"
    cfg = R4Settings()
    print("R4_DATA " + json.dumps(integrity), flush=True)
    report = {
        "contract": CONTRACT, "model_status": "RESEARCH_NO_LIVE_AUTHORITY",
        "price_manifest": integrity,
        "macro": {
            "source": "HF publisher-lagged FRED real yield US10Y, nominal US10Y, H10 broad USD",
            "not_ICE_DXY": True,
            "intraday_yield_DXY_not_validated": True,
            "publication_timestamp_independently_verified": False,
        },
        "account": {
            "initial_usd": 100, "leverage": 200,
            "min_lot_assumed": .01, "contract_oz_assumed": 100,
            "lot_step_assumed": .01, "cost_usd_per_oz_roundtrip_assumed": .80,
            "risk_cap_pct": 5, "max_margin_pct": 50,
            "stop_first_if_ambiguous": True,
            "flat_after_13_wib": True,
            "broker_specs_checked": False, "bid_ask_tick_checked": False,
        },
        "chronological_splits": WINDOWS,
        "strategies": {},
        "annual": {},
        "cost_stress": {},
    }
    base_features = None
    for name, (pool, trend) in TECHNICAL_MODELS.items():
        print(f"R4_BUILD {name} pool={pool} trend={trend}", flush=True)
        f = build_liquidity_signals(raw, pool=pool, trend=trend)
        if name == MACRO_BASELINE:
            base_features = f
        out = {
            "full": _metrics(f, cfg),
            "periods": {w: _metrics(f, cfg, begin=a, end=b)
                        for w, (a, b) in WINDOWS.items()},
            "signal_count": int(f["r4_signal"].ne(0).sum()),
        }
        report["strategies"][name] = out
        for year in range(2019, 2027):
            if year == 2026:
                finish = "2026-01-10"
            else:
                finish = f"{year + 1}-01-01"
            report["annual"].setdefault(name, {})[str(year)] = _metrics(
                f, cfg, begin=f"{year}-01-01", end=finish
            )
        print(f"R4_BASE {name} ending={out['full']['ending_usd']:.2f} "
              f"pf={out['full']['profit_factor']} trades={out['full']['count']} "
              f"DD={out['full']['closed_dd_pct']:.2f} "
              f"skipped_risk={out['full']['blocked_risk']}", flush=True)

    assert base_features is not None
    macro = load_lagged_macro()
    report["macro"]["rows"] = len(macro)
    for mode in ("REAL_AND_USD", "REAL_NOMINAL_USD"):
        name = "R4_PREASIA_" + mode
        f = apply_lagged_macro_filter(base_features, macro, mode=mode)
        report["strategies"][name] = {
            "full": _metrics(f, cfg),
            "periods": {w: _metrics(f, cfg, begin=a, end=b)
                        for w, (a, b) in WINDOWS.items()},
            "signal_count": int(f["r4_signal"].ne(0).sum()),
        }
        print(f"R4_MACRO {name} ending={report['strategies'][name]['full']['ending_usd']:.2f} "
              f"pf={report['strategies'][name]['full']['profit_factor']} "
              f"trades={report['strategies'][name]['full']['count']}", flush=True)

    for fr in (.40, .80, 1.50, 3.0):
        cfg_stress = replace(cfg, roundtrip_cost_usd_per_oz=fr)
        report["cost_stress"][str(fr)] = _metrics(base_features, cfg_stress)
        print(f"R4_STRESS friction={fr} ending="
              f"{report['cost_stress'][str(fr)]['ending_usd']:.2f}", flush=True)

    OUTPUT.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print("R4_RESEARCH_COMPLETE", flush=True)
    return report


if __name__ == "__main__":
    run()
