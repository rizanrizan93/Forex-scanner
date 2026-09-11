from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import dukascopy_python
from dukascopy_python import instruments

import adaptive_public_v1 as base

CONTRACT = "ADAPTIVE_PUBLIC_DUKASCOPY_V2"
DATA_START = datetime(2020, 1, 1)
OOS_START = pd.Timestamp("2023-01-01 00:00:00")
DATA_END = datetime(2026, 9, 1)
ROLLING_LOOKBACK_YEARS = 2
ROLLING_MIN_TRADES = 100
BASE_COST_PIPS = 1.2

PAIR_INSTRUMENTS = {
    "EURUSD": instruments.INSTRUMENT_FX_MAJORS_EUR_USD,
    "GBPUSD": instruments.INSTRUMENT_FX_MAJORS_GBP_USD,
    "USDJPY": instruments.INSTRUMENT_FX_MAJORS_USD_JPY,
    "USDCHF": instruments.INSTRUMENT_FX_MAJORS_USD_CHF,
    "AUDUSD": instruments.INSTRUMENT_FX_MAJORS_AUD_USD,
    "USDCAD": instruments.INSTRUMENT_FX_MAJORS_USD_CAD,
}

# Frozen from V1.1 before any 2023+ Dukascopy outcome is inspected.
FROZEN_V1_1_PAIR_REGIME = {
    ("GBPUSD", "RANGE_LOW_VOL"): "DONCHIAN20",
    ("USDCHF", "TREND_HIGH_VOL"): "DONCHIAN20",
    ("AUDUSD", "TREND_LOW_VOL"): "MOMENTUM24",
}


def fetch_pair(pair: str) -> pd.DataFrame:
    df = dukascopy_python.fetch(
        instrument=PAIR_INSTRUMENTS[pair],
        interval=dukascopy_python.INTERVAL_HOUR_1,
        offer_side=dukascopy_python.OFFER_SIDE_BID,
        start=DATA_START,
        end=DATA_END,
        max_retries=3,
    )
    if df is None or df.empty:
        raise RuntimeError(f"{pair}: Dukascopy returned no H1 data")
    x = df.copy().reset_index()
    cols = {str(c).lower(): c for c in x.columns}
    time_col = cols.get("timestamp") or cols.get("time") or x.columns[0]
    out = pd.DataFrame()
    out["time"] = pd.to_datetime(x[time_col], utc=True, errors="coerce").dt.tz_convert(None)
    for c in ("open", "high", "low", "close"):
        src = cols.get(c)
        if src is None:
            raise RuntimeError(f"{pair}: missing Dukascopy column {c}; columns={list(x.columns)}")
        out[c] = pd.to_numeric(x[src], errors="coerce")
    out = out.dropna().drop_duplicates("time").sort_values("time").reset_index(drop=True)
    if len(out) < 20_000:
        raise RuntimeError(f"{pair}: insufficient H1 rows {len(out)}")
    if out["time"].max() < pd.Timestamp("2026-08-25"):
        raise RuntimeError(f"{pair}: data unexpectedly stale through {out['time'].max()}")
    return out


def canonical_nonoverlap(trades: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for (_, _), group in trades.groupby(["pair", "strategy"]):
        parts.append(base.nonoverlap(group))
    if not parts:
        return trades.iloc[0:0].copy()
    return pd.concat(parts, ignore_index=True).sort_values(["entry_time", "pair", "strategy"])


def pf_and_expectancy(df: pd.DataFrame) -> tuple[int, float, float]:
    if df.empty:
        return 0, float("nan"), float("nan")
    y = df["net_r"].to_numpy(float)
    gp = float(y[y > 0].sum())
    gl = float(-y[y < 0].sum())
    pf = gp / gl if gl > 0 else float("inf")
    return len(y), float(y.mean()), pf


def apply_frozen_map(oos: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for (pair, regime), strategy in FROZEN_V1_1_PAIR_REGIME.items():
        parts.append(
            oos[
                (oos["pair"] == pair)
                & (oos["regime"] == regime)
                & (oos["strategy"] == strategy)
            ]
        )
    return base.nonoverlap(pd.concat(parts, ignore_index=True)) if parts else oos.iloc[0:0].copy()


def rolling_pair_router(trades: pd.DataFrame, canonical: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    final_end = pd.Timestamp(DATA_END)
    quarter_starts = pd.date_range(OOS_START, final_end + pd.offsets.QuarterBegin(startingMonth=1), freq="QS")
    if quarter_starts[-1] <= final_end:
        quarter_starts = quarter_starts.append(pd.DatetimeIndex([quarter_starts[-1] + pd.offsets.QuarterBegin()]))

    free_at = {pair: pd.Timestamp.min for pair in PAIR_INSTRUMENTS}
    chosen_rows: list[int] = []
    audit: list[dict] = []

    for q_start, q_end in zip(quarter_starts[:-1], quarter_starts[1:]):
        if q_start >= final_end:
            break
        q_end = min(q_end, final_end)
        lookback_start = q_start - pd.DateOffset(years=ROLLING_LOOKBACK_YEARS)
        for pair in PAIR_INSTRUMENTS:
            candidates = []
            evidence = {}
            for strategy in base.SPECS:
                hist = canonical[
                    (canonical["pair"] == pair)
                    & (canonical["strategy"] == strategy)
                    & (canonical["entry_time"] >= lookback_start)
                    & (canonical["exit_time"] < q_start)
                ]
                n, exp_r, pf = pf_and_expectancy(hist)
                evidence[strategy] = {
                    "n": n,
                    "expectancy_r": None if not np.isfinite(exp_r) else round(exp_r, 6),
                    "profit_factor": None if not np.isfinite(pf) else round(pf, 6),
                }
                if n >= ROLLING_MIN_TRADES and exp_r > 0 and pf > 1.0:
                    candidates.append((exp_r, strategy))
            selected = max(candidates)[1] if candidates else "NO_TRADE"
            audit.append(
                {
                    "quarter": str(q_start.date()),
                    "pair": pair,
                    "selected": selected,
                    "lookback_start": str(lookback_start.date()),
                    "evidence": evidence,
                }
            )
            if selected == "NO_TRADE":
                continue
            q = trades[
                (trades["pair"] == pair)
                & (trades["strategy"] == selected)
                & (trades["entry_time"] >= q_start)
                & (trades["entry_time"] < q_end)
            ].sort_values("entry_time")
            for idx, row in q.iterrows():
                if row["entry_time"] >= free_at[pair]:
                    chosen_rows.append(idx)
                    free_at[pair] = row["exit_time"]

    selected = trades.loc[chosen_rows].sort_values(["entry_time", "pair"]).copy() if chosen_rows else trades.iloc[0:0].copy()
    return selected, audit


def recost_metrics(df: pd.DataFrame, cost_pips: float) -> dict:
    if df.empty:
        return {"trades": 0, "net_r": 0.0, "expectancy_r": None, "profit_factor": None, "max_dd_r": None}
    y = df["gross_r"].to_numpy(float) - df["cost_r"].to_numpy(float) * (cost_pips / BASE_COST_PIPS)
    gp = float(y[y > 0].sum())
    gl = float(-y[y < 0].sum())
    eq = np.cumsum(y)
    peak = np.maximum.accumulate(np.r_[0.0, eq])
    dd = peak[1:] - eq
    return {
        "trades": int(len(y)),
        "net_r": round(float(y.sum()), 4),
        "expectancy_r": round(float(y.mean()), 5),
        "profit_factor": None if gl <= 0 else round(gp / gl, 4),
        "max_dd_r": round(float(dd.max()), 4),
    }


def annual(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    x = df.assign(year=pd.DatetimeIndex(df["entry_time"]).year).groupby("year")["net_r"].sum()
    return {str(int(k)): round(float(v), 3) for k, v in x.items()}


def full_metrics(df: pd.DataFrame) -> dict:
    result = base.metrics(df)
    result["annual_net_r"] = annual(df)
    return result


def main() -> None:
    # Keep the V1 cost contract frozen.
    base.BASE_COST_PIPS = BASE_COST_PIPS

    parts = []
    coverage = {}
    for pair in PAIR_INSTRUMENTS:
        raw = fetch_pair(pair)
        coverage[pair] = {
            "rows": int(len(raw)),
            "start": str(raw["time"].min()),
            "end": str(raw["time"].max()),
        }
        enriched = base.add_indicators(raw)
        for spec in base.SPECS.values():
            parts.append(base.simulate_strategy(pair, enriched, spec))

    trades = pd.concat(parts, ignore_index=True)
    trades = trades[trades["entry_time"] < pd.Timestamp(DATA_END)].copy()
    canonical = canonical_nonoverlap(trades)
    oos = trades[trades["entry_time"] >= OOS_START].copy()

    systems = {}
    static_sets = {}
    for strategy in ("DONCHIAN20", "MOMENTUM24", "EMA_PULLBACK", "MEAN_REVERT"):
        d = base.nonoverlap(oos[oos["strategy"] == strategy])
        static_sets[strategy] = d
        systems[f"STATIC_{strategy}"] = full_metrics(d)

    frozen = apply_frozen_map(oos)
    systems["FROZEN_V1_1_PAIR_REGIME"] = full_metrics(frozen)

    rolling, rolling_audit = rolling_pair_router(trades, canonical)
    systems["ROLLING_2Y_QUARTERLY_PAIR_ROUTER"] = full_metrics(rolling)

    stress = {}
    for name, d in {
        "STATIC_DONCHIAN20": static_sets["DONCHIAN20"],
        "STATIC_MOMENTUM24": static_sets["MOMENTUM24"],
        "FROZEN_V1_1_PAIR_REGIME": frozen,
        "ROLLING_2Y_QUARTERLY_PAIR_ROUTER": rolling,
    }.items():
        stress[name] = {str(c): recost_metrics(d, c) for c in (1.2, 1.5, 2.0, 2.5)}

    result = {
        "contract": CONTRACT,
        "execution_influence": False,
        "data_source": "Dukascopy Bank public historical feed via dukascopy-python",
        "offer_side": "BID",
        "timeframe": "H1",
        "data_start": str(DATA_START.date()),
        "oos_start": str(OOS_START.date()),
        "data_end_exclusive": str(DATA_END.date()),
        "base_roundtrip_cost_pips": BASE_COST_PIPS,
        "same_bar_policy": "STOP_FIRST",
        "strategy_parameters": {
            k: {"stop_atr": v.stop_atr, "target_atr": v.target_atr, "max_hold_h1": v.max_hold}
            for k, v in base.SPECS.items()
        },
        "rolling_router": {
            "cadence": "quarterly",
            "lookback_years": ROLLING_LOOKBACK_YEARS,
            "minimum_nonoverlap_trades": ROLLING_MIN_TRADES,
            "eligibility": "expectancy_r > 0 and profit_factor > 1.0 using only trades exited before quarter start",
            "ranking": "highest trailing expectancy_r per pair",
            "fallback": "NO_TRADE",
        },
        "frozen_v1_1_pair_regime": {f"{p}|{r}": s for (p, r), s in FROZEN_V1_1_PAIR_REGIME.items()},
        "coverage": coverage,
        "systems": systems,
        "cost_stress": stress,
        "rolling_selection_audit": rolling_audit,
    }

    out = Path("research_output_v2")
    out.mkdir(exist_ok=True)
    (out / "adaptive_public_v2_dukascopy.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    rows = []
    for name, m in systems.items():
        rows.append(
            {
                "system": name,
                "trades": m["trades"],
                "net_r": m["net_r"],
                "expectancy_r": m["expectancy_r"],
                "profit_factor": m["profit_factor"],
                "win_rate": m["win_rate"],
                "max_dd_r": m["max_dd_r"],
                "ci95_lo": m["ci95_lo"],
                "ci95_hi": m["ci95_hi"],
            }
        )
    table = pd.DataFrame(rows).sort_values("expectancy_r", ascending=False, na_position="last")
    table.to_csv(out / "adaptive_public_v2_summary.csv", index=False)
    pd.DataFrame(rolling_audit).assign(evidence=lambda x: x["evidence"].map(json.dumps)).to_csv(
        out / "adaptive_public_v2_rolling_audit.csv", index=False
    )

    print("# Adaptive Public Dukascopy V2")
    print(table.to_string(index=False))
    print("\nCost stress:")
    print(json.dumps(stress, indent=2))
    print("\nCoverage:")
    print(json.dumps(coverage, indent=2))


if __name__ == "__main__":
    main()
