from __future__ import annotations

import json
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import five_core_tournament_v1 as base

CONTRACT = "XAU_D1_BOUNDARY_SENSITIVITY_V1"
EXECUTION_INFLUENCE = False
SYMBOL = "XAUUSD"
NY = ZoneInfo("America/New_York")
OBSERVED_BROKER_BOUNDARY = "17:00 America/New_York (21:00/22:00 UTC with DST)"
ORIGINAL_RESEARCH_BOUNDARY = "00:00 UTC"

# Frozen from the already-tested D1_TSMOM_60_200 contract.
STOP_ATR = 2.0
TARGET_ATR = 4.0
MAX_HOLD_D1 = 30
XAU_COST_STRESS = {
    "base_0.17_usd": 0.17,
    "stress_0.25_usd": 0.25,
    "stress_0.35_usd": 0.35,
}

ERAS = (
    ("2012_2016", pd.Timestamp("2012-01-01", tz="UTC"), pd.Timestamp("2017-01-01", tz="UTC")),
    ("2017_2020", pd.Timestamp("2017-01-01", tz="UTC"), pd.Timestamp("2021-01-01", tz="UTC")),
    ("2021_2024", pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")),
    ("2025_2026", pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2026-09-01", tz="UTC")),
)
OOS_START = pd.Timestamp("2025-01-01", tz="UTC")


def aggregate_utc_midnight(h1: pd.DataFrame) -> pd.DataFrame:
    """Original tournament construction: UTC-midnight pandas D1 buckets."""
    return base.resample_ohlc(h1, "1D")


def _session_start_utc(session_date) -> pd.Timestamp:
    """Exact 17:00 New York wall-clock session label, DST-aware."""
    local_start = datetime.combine(session_date, time(17, 0), tzinfo=NY)
    return pd.Timestamp(local_start).tz_convert("UTC")


def aggregate_new_york_17(h1: pd.DataFrame) -> pd.DataFrame:
    """Construct broker-like D1 bars from 17:00 New York to 17:00 New York.

    The observed cTrader DEMO XAU D1 timestamps are 21:00/22:00 UTC, which map
    to 17:00 America/New_York across DST. Each H1 row is assigned to the most
    recent NY17 session. The output timestamp is the exact session boundary,
    not the first available H1 observation; this matters on Sunday/holiday
    partial sessions where market data can begin after the broker D1 boundary.
    No strategy parameter is changed.
    """
    x = h1.copy().sort_values("time").reset_index(drop=True)
    local = x["time"].dt.tz_convert(NY)
    x["session_date"] = (local - pd.Timedelta(hours=17)).dt.date
    rows: list[dict] = []
    for session_date, day in x.groupby("session_date", sort=True):
        if day.empty:
            continue
        rows.append(
            {
                "time": _session_start_utc(session_date),
                "open": float(day["open"].iloc[0]),
                "high": float(day["high"].max()),
                "low": float(day["low"].min()),
                "close": float(day["close"].iloc[-1]),
                "h1_rows": int(len(day)),
                "first_observation_at": day["time"].iloc[0],
                "last_observation_at": day["time"].iloc[-1],
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        raise RuntimeError("NY17 D1 aggregation produced no rows")
    # Actual market sessions only. Partial Sunday/holiday sessions remain valid
    # D1 bars; their timestamp still uses the broker's fixed NY17 boundary.
    return out.sort_values("time").reset_index(drop=True)


def simulate(d1: pd.DataFrame, label: str) -> pd.DataFrame:
    x = base.add_indicators(d1)
    long_sig = (x["close"] > x["ema200"]) & (x["ret60"] > 0)
    short_sig = (x["close"] < x["ema200"]) & (x["ret60"] < 0)
    direction = pd.Series(
        np.where(long_sig, 1, np.where(short_sig, -1, 0)),
        index=x.index,
    )
    return base.simulate_fixed_atr(
        SYMBOL,
        f"D1_TSMOM_60_200_{label}",
        x,
        direction,
        STOP_ATR,
        TARGET_ATR,
        MAX_HOLD_D1,
    )


def metric_blocks(trades: pd.DataFrame) -> dict:
    blocks: dict[str, dict] = {}
    for era, start, end in ERAS:
        blocks[era] = base.metrics(
            trades[(trades["entry_time"] >= start) & (trades["entry_time"] < end)]
        )
    blocks["OOS_2025_2026"] = base.metrics(trades[trades["entry_time"] >= OOS_START])
    blocks["FULL_2012_2026"] = base.metrics(trades)
    blocks["LONG_FULL"] = base.metrics(trades[trades["direction"] > 0])
    blocks["SHORT_FULL"] = base.metrics(trades[trades["direction"] < 0])
    return blocks


def _with_cost(trades: pd.DataFrame, cost_abs: float) -> pd.DataFrame:
    x = trades.copy()
    if x.empty:
        return x
    x["base_cost_abs"] = float(cost_abs)
    x["cost_r"] = float(cost_abs) / x["risk_price"]
    x["net_r"] = x["gross_r"] - x["cost_r"]
    return x


def cost_stress_blocks(trades: pd.DataFrame) -> dict:
    out: dict[str, dict] = {}
    for label, cost in XAU_COST_STRESS.items():
        stressed = _with_cost(trades, cost)
        out[label] = {
            "cost_abs_usd": cost,
            "FULL_2012_2026": base.metrics(stressed),
            "OOS_2025_2026": base.metrics(
                stressed[stressed["entry_time"] >= OOS_START]
            ),
        }
    return out


def annual_direction_summary(trades: pd.DataFrame) -> list[dict]:
    if trades.empty:
        return []
    x = trades.copy()
    x["year"] = pd.to_datetime(x["entry_time"], utc=True).dt.year
    rows = []
    for year, group in x.groupby("year", sort=True):
        rows.append(
            {
                "year": int(year),
                "trades": int(len(group)),
                "net_r": float(group["net_r"].sum()),
                "long_trades": int((group["direction"] > 0).sum()),
                "short_trades": int((group["direction"] < 0).sum()),
            }
        )
    return rows


def boundary_diagnostics(d1: pd.DataFrame) -> dict:
    ts = pd.to_datetime(d1["time"], utc=True)
    seconds = ts.dt.hour * 3600 + ts.dt.minute * 60 + ts.dt.second
    result = {
        "rows": int(len(d1)),
        "first": str(ts.min()),
        "last": str(ts.max()),
        "unique_open_seconds_utc": sorted(int(v) for v in seconds.unique()),
    }
    if "h1_rows" in d1:
        counts = d1["h1_rows"].value_counts().sort_index()
        result["h1_rows_per_bucket"] = {str(int(k)): int(v) for k, v in counts.items()}
        result["partial_sessions_lt_20h"] = int((d1["h1_rows"] < 20).sum())
    return result


def main() -> int:
    # Reuse the frozen public-data loader and cost model; only D1 aggregation differs.
    base.SYMBOLS = {SYMBOL: base.SYMBOLS[SYMBOL]}
    base.SLOW_START = datetime(2012, 1, 1)

    print("FETCH XAUUSD H1 2012-2026")
    h1 = base.fetch_h1(SYMBOL)
    utc_d1 = aggregate_utc_midnight(h1)
    ny17_d1 = aggregate_new_york_17(h1)

    print("SIM original UTC00 boundary")
    utc_trades = simulate(utc_d1, "UTC00")
    print("SIM observed broker NY17 boundary")
    ny17_trades = simulate(ny17_d1, "NY17")

    variants = {
        "UTC00_ORIGINAL": {
            "boundary": ORIGINAL_RESEARCH_BOUNDARY,
            "d1": utc_d1,
            "trades": utc_trades,
        },
        "NY17_BROKER_ALIGNED": {
            "boundary": OBSERVED_BROKER_BOUNDARY,
            "d1": ny17_d1,
            "trades": ny17_trades,
        },
    }

    scorecard = {}
    for name, item in variants.items():
        scorecard[name] = {
            "boundary": item["boundary"],
            "boundary_diagnostics": boundary_diagnostics(item["d1"]),
            "metrics": metric_blocks(item["trades"]),
            "cost_stress": cost_stress_blocks(item["trades"]),
            "annual": annual_direction_summary(item["trades"]),
        }

    result = {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "symbol": SYMBOL,
        "strategy": "D1_TSMOM_60_200",
        "data_source": "Dukascopy Bank public BID H1 via dukascopy-python",
        "data_start": str(h1["time"].min()),
        "data_end": str(h1["time"].max()),
        "same_bar_policy": base.SAME_BAR_POLICY,
        "frozen_parameters": {
            "trend": "close vs EMA200",
            "momentum": "60D return same sign",
            "entry": "next D1 open",
            "stop_atr": STOP_ATR,
            "target_atr": TARGET_ATR,
            "max_hold_d1": MAX_HOLD_D1,
            "cost_stress_abs_usd": XAU_COST_STRESS,
        },
        "observed_ctrader_d1_open_seconds_utc": [75600, 79200],
        "primary_comparison": ["UTC00_ORIGINAL", "NY17_BROKER_ALIGNED"],
        "scorecard": scorecard,
    }

    out = Path("research_output_xau_d1_boundary_v1")
    out.mkdir(exist_ok=True)
    (out / "xau_d1_boundary_sensitivity_v1.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    for name, item in variants.items():
        item["trades"].to_csv(out / f"trades_{name}.csv", index=False)
    rows = []
    for name, item in scorecard.items():
        for period, metrics in item["metrics"].items():
            rows.append(
                {
                    "variant": name,
                    "boundary": item["boundary"],
                    "period": period,
                    **{k: v for k, v in metrics.items() if k != "annual_net_r"},
                }
            )
    pd.DataFrame(rows).to_csv(out / "summary.csv", index=False)

    stress_rows = []
    for name, item in scorecard.items():
        for cost_label, block in item["cost_stress"].items():
            for period in ("FULL_2012_2026", "OOS_2025_2026"):
                metrics = block[period]
                stress_rows.append(
                    {
                        "variant": name,
                        "cost_label": cost_label,
                        "cost_abs_usd": block["cost_abs_usd"],
                        "period": period,
                        **{k: v for k, v in metrics.items() if k != "annual_net_r"},
                    }
                )
    pd.DataFrame(stress_rows).to_csv(out / "cost_stress.csv", index=False)

    print("\n# XAU D1 BOUNDARY SENSITIVITY V1")
    print(pd.DataFrame(rows).to_string(index=False))
    print("\n# COST STRESS")
    print(pd.DataFrame(stress_rows).to_string(index=False))
    print("\nBoundary diagnostics:")
    print(json.dumps({k: v["boundary_diagnostics"] for k, v in scorecard.items()}, indent=2))
    print("Research only: execution_influence=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
