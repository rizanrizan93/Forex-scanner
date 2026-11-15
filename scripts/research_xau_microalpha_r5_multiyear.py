"""RIZAN R5 reproducible fixed-hypothesis trend/macro study (NO LIVE).

Uses SHA-pinned public M5 OHLC and explicitly labelled publisher-lagged FRED/H10.
This is NOT an FP Markets bid/ask replay and cannot confirm a real alpha.
We deliberately avoid parameter optimization; results are chronological diagnostics.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pandas as pd

from fx_scanner.xau_microalpha_r4 import R4Settings, backtest, apply_lagged_macro_filter
from fx_scanner.xau_microalpha_r5 import CONTRACT, CANDIDATES, build_signals, features
from research_xau_microalpha_r3_multiyear import load_history
from research_xau_microalpha_r3_lagged_macro import load_lagged_macro

OUTPUT = Path("rizan_xau_microalpha_r5_research.json")
PANELS = {
    "DEVELOPMENT_2019_2022": ("2019-01-01", "2023-01-01"),
    "VALIDATION_2023_2024": ("2023-01-01", "2025-01-01"),
    "DIAGNOSTIC_2025_TO_2026_01_09": ("2025-01-01", "2026-01-10"),
}
MACRO_BASELINE = "BREAKOUT_12_H1_M15"


def measure(frame: pd.DataFrame, cfg: R4Settings,
            *, begin: str | None = None, end: str | None = None) -> dict:
    x, _ = backtest(frame, cfg, session="ASIA", window_start=begin, window_end=end)
    return x


def run() -> dict:
    raw, integrity = load_history()
    f = features(raw)
    cfg = R4Settings(
        initial_usd=100, leverage=200, min_lot=.01, lot_step=.01,
        contract_oz_per_lot=100, max_lot=.50, risk_fraction=.05,
        max_margin_fraction=.50, roundtrip_cost_usd_per_oz=.80,
        reward_r=2., max_hold_bars=24,
    )
    report = {
        "contract": CONTRACT,
        "status": "RESEARCH_ONLY_NO_ORDER_AUTHORITY",
        "data_manifest": integrity,
        "period": f"{integrity['first']} — {integrity['last']} (verified actual)",
        "specs": {
            "starting_equity_usd": 100, "compounding": True,
            "leverage_reference": 200,
            "min_lot_ASSUMED": .01, "contract_oz_per_lot_ASSUMED": 100,
            "margin_approx_only": True, "maximum_initial_margin_fraction": .50,
            "maximum_risk_fraction": .05, "maximum_lots_ASSUMED": .50,
            "reference_cost_usd_per_oz_roundtrip": .80, "target_r": 2,
            "holding_limit_m5_bars": 24,
            "entry_time": "08:00-12:59 WIB; exit by 13:00 WIB",
            "no_overlapping_positions": True,
            "intrabar_same_candle_priority": "STOP_FIRST",
            "historical_price_bid_ask_tick_validated": False,
            "fp_ctrader_symbol_specs_validated": False,
            "macro_history_point_in_time_independently_audited": False,
        },
        "macro_proxy": {
            "provider": "Publisher-lagged FRED DFII10, DGS10 and H10 USD broad",
            "ICE_DXY": False, "intraday_2Y_or_DXY_predictions": False,
            "cadence": "LAGGED_H1_PUBLICATION_SIMULATION",
            "no_current_macro_snapshot_in_history": True,
        },
        "panels": PANELS,
        "strategies": {},
        "macro_ablation": {},
        "cost_stress": {},
    }
    selection = None
    for candidate in CANDIDATES:
        signals = build_signals(f, candidate=candidate)
        if candidate == MACRO_BASELINE:
            selection = signals
        full = measure(signals, cfg)
        panel = {name: measure(signals, cfg, begin=begin, end=end)
                 for name, (begin, end) in PANELS.items()}
        report["strategies"][candidate] = {
            "signals": int(signals["r4_signal"].ne(0).sum()),
            "full": full, "panels": panel,
        }
        print(
            f"R5_TREND {candidate} ending={full['ending_usd']} "
            f"PF={full['profit_factor']} DD={full['closed_dd_pct']} "
            f"trades={full['count']} blocked={full['blocked_risk']}",
            flush=True,
        )
        # Flush partial results to CI artifact for diagnosing data/runtime failure.
        OUTPUT.write_text(json.dumps(report, indent=2, default=str) + "\n")
    if selection is None:
        raise RuntimeError("NO_FIXED_BASELINE")
    macro = load_lagged_macro()
    report["macro_proxy"]["rows"] = len(macro)
    for mode in ("REAL_AND_USD", "REAL_NOMINAL_USD"):
        s = apply_lagged_macro_filter(selection, macro, mode=mode)
        full = measure(s, cfg)
        panel = {name: measure(s, cfg, begin=begin, end=end)
                 for name, (begin, end) in PANELS.items()}
        report["macro_ablation"][mode] = {
            "signals": int(s["r4_signal"].ne(0).sum()),
            "full": full, "panels": panel,
        }
        print(
            f"R5_MACRO {mode} ending={full['ending_usd']} "
            f"PF={full['profit_factor']} DD={full['closed_dd_pct']} "
            f"trades={full['count']}", flush=True,
        )
        OUTPUT.write_text(json.dumps(report, indent=2, default=str) + "\n")
    # Fixed-trade eligibility caveat: cost changes cause risk cap to reject
    # different trades; more costly models may lose less by trading less.
    for cost in (.4, .8, 1.6):
        stressed = replace(cfg, roundtrip_cost_usd_per_oz=cost)
        report["cost_stress"][str(cost)] = measure(selection, stressed)
        x = report["cost_stress"][str(cost)]
        print(f"R5_COST {cost} ending={x['ending_usd']} count={x['count']}", flush=True)
    OUTPUT.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print("R5_RESEARCH_COMPLETE", flush=True)
    return report


if __name__ == "__main__":
    run()
