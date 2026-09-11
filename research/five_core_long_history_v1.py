from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

import five_core_tournament_v1 as base

CONTRACT = "FIVE_CORE_LONG_HISTORY_V1"
EXECUTION_INFLUENCE = False
LONG_START = datetime(2012, 1, 1)
ERAS = (
    ("2012_2016", pd.Timestamp("2012-01-01", tz="UTC"), pd.Timestamp("2017-01-01", tz="UTC")),
    ("2017_2020", pd.Timestamp("2017-01-01", tz="UTC"), pd.Timestamp("2021-01-01", tz="UTC")),
    ("2021_2024", pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")),
    ("2025_2026", pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2026-09-01", tz="UTC")),
)

symbol = os.environ.get("CORE_SYMBOL", "").strip().upper()
if symbol not in base.SYMBOLS:
    raise SystemExit(f"CORE_SYMBOL must be one of {list(base.SYMBOLS)}; got {symbol!r}")

# Same strategy parameters and cost mechanics as FIVE_CORE_TOURNAMENT_V1.
base.SYMBOLS = {symbol: base.SYMBOLS[symbol]}
base.SLOW_START = LONG_START

print(f"FETCH {symbol} H1 LONG 2012-2026")
h1 = base.fetch_h1(symbol)
print(f"SIM {symbol} D1_TSMOM_60_200")
d1 = base.d1_tsmom(symbol, h1)
print(f"SIM {symbol} H4_TREND_PULLBACK")
pb = base.h4_pullback(symbol, h1)
print(f"SIM {symbol} H4_COMPRESSION_BREAKOUT")
cb = base.h4_compression_breakout(symbol, h1)

frames = {
    "D1_TSMOM_60_200": d1,
    "H4_TREND_PULLBACK": pb,
    "H4_COMPRESSION_BREAKOUT": cb,
}

scorecard = {}
rows = []
for strategy, trades in frames.items():
    scorecard[strategy] = {}
    for era, start, end in ERAS:
        subset = trades[(trades["entry_time"] >= start) & (trades["entry_time"] < end)]
        m = base.metrics(subset)
        scorecard[strategy][era] = m
        rows.append({"symbol": symbol, "strategy": strategy, "era": era, **{k: v for k, v in m.items() if k != "annual_net_r"}})
    m = base.metrics(trades)
    scorecard[strategy]["FULL_2012_2026"] = m
    rows.append({"symbol": symbol, "strategy": strategy, "era": "FULL_2012_2026", **{k: v for k, v in m.items() if k != "annual_net_r"}})

result = {
    "contract": CONTRACT,
    "execution_influence": EXECUTION_INFLUENCE,
    "symbol": symbol,
    "data_source": "Dukascopy Bank public BID H1 via dukascopy-python",
    "data_start": str(LONG_START.date()),
    "data_end_exclusive": str(base.DATA_END.date()),
    "same_bar_policy": base.SAME_BAR_POLICY,
    "strategy_parameters_unchanged_from": "FIVE_CORE_TOURNAMENT_V1",
    "coverage": {
        "h1_rows": int(len(h1)),
        "h1_start": str(h1["time"].min()),
        "h1_end": str(h1["time"].max()),
    },
    "scorecard": scorecard,
}

out = Path("research_output_five_core_long_v1")
out.mkdir(exist_ok=True)
(out / f"five_core_long_history_{symbol}.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
pd.concat([x.assign(strategy=k) for k, x in frames.items()], ignore_index=True).to_csv(out / f"five_core_long_history_{symbol}_trades.csv", index=False)
pd.DataFrame(rows).to_csv(out / f"five_core_long_history_{symbol}_summary.csv", index=False)

print("\n# FIVE CORE LONG HISTORY V1")
print(pd.DataFrame(rows).to_string(index=False))
print("\nCoverage:", json.dumps(result["coverage"], indent=2))
print("Research only: execution_influence=false")
