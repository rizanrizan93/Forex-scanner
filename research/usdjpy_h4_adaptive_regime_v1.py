from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import dukascopy_python
import numpy as np
import pandas as pd
from dukascopy_python import instruments

CONTRACT = "USDJPY_H4_ADAPTIVE_REGIME_V1"
EXECUTION_INFLUENCE = False
SEED = 20260913
DATA_START = datetime(2012, 1, 1)
DATA_END = datetime(2026, 9, 1)
VALIDATION_START = pd.Timestamp("2021-01-01", tz="UTC")
OOS_START = pd.Timestamp("2025-01-01", tz="UTC")
PIP_SIZE = 0.01
BASE_COST_ABS = 1.2 * PIP_SIZE
STRESS_COST_ABS = 1.5 * PIP_SIZE
SAME_BAR_POLICY = "STOP_FIRST"


@dataclass(frozen=True, slots=True)
class AdaptiveCandidate:
    name: str
    mode: str
    lookback_trades: int | None
    lookback_days: int | None
    min_count: int
    min_expectancy_r: float
    min_profit_factor: float


FROZEN_CANDIDATES = (
    AdaptiveCandidate(
        "ADAPT_24_E005_PF105",
        "TRADES",
        24,
        None,
        24,
        0.05,
        1.05,
    ),
    AdaptiveCandidate(
        "ADAPT_40_E000_PF105",
        "TRADES",
        40,
        None,
        40,
        0.00,
        1.05,
    ),
    AdaptiveCandidate(
        "ADAPT_60_E000_PF110",
        "TRADES",
        60,
        None,
        60,
        0.00,
        1.10,
    ),
    AdaptiveCandidate(
        "ADAPT_18M_E000_PF105",
        "DAYS",
        None,
        548,
        20,
        0.00,
        1.05,
    ),
)


def _normalize(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise RuntimeError("USDJPY: empty Dukascopy H1 history")
    x = raw.copy().reset_index()
    cols = {str(column).lower(): column for column in x.columns}
    time_col = cols.get("timestamp") or cols.get("time") or x.columns[0]
    out = pd.DataFrame()
    out["time"] = pd.to_datetime(x[time_col], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close"):
        source = cols.get(column)
        if source is None:
            raise RuntimeError(f"USDJPY missing {column}; columns={list(x.columns)}")
        out[column] = pd.to_numeric(x[source], errors="coerce")
    out = (
        out.dropna()
        .drop_duplicates("time")
        .sort_values("time")
        .reset_index(drop=True)
    )
    if len(out) < 50_000:
        raise RuntimeError(f"USDJPY insufficient H1 history: {len(out)}")
    return out


def fetch_h1() -> pd.DataFrame:
    raw = dukascopy_python.fetch(
        instrument=instruments.INSTRUMENT_FX_MAJORS_USD_JPY,
        interval=dukascopy_python.INTERVAL_HOUR_1,
        offer_side=dukascopy_python.OFFER_SIDE_BID,
        start=DATA_START,
        end=DATA_END,
        max_retries=3,
    )
    return _normalize(raw)


def resample_h4(h1: pd.DataFrame) -> pd.DataFrame:
    source = h1.set_index("time").sort_index()
    rows = source.resample("4h", label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )
    return rows.dropna().reset_index()


def add_indicators(h4: pd.DataFrame) -> pd.DataFrame:
    x = h4.copy().reset_index(drop=True)
    previous_close = x["close"].shift(1)
    true_range = pd.concat(
        [
            (x["high"] - x["low"]).abs(),
            (x["high"] - previous_close).abs(),
            (x["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    x["atr14"] = true_range.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14,
    ).mean()
    x["ema50"] = x["close"].ewm(
        span=50,
        adjust=False,
        min_periods=50,
    ).mean()
    x["ema200"] = x["close"].ewm(
        span=200,
        adjust=False,
        min_periods=200,
    ).mean()
    x["prior_high20"] = x["high"].rolling(20).max().shift(1)
    x["prior_low20"] = x["low"].rolling(20).min().shift(1)
    x["atr_pct"] = x["atr14"] / x["close"]
    x["atr_q35_prior"] = (
        x["atr_pct"].shift(1).rolling(100).quantile(0.35)
    )
    return x


def generate_shadow_trades(h4: pd.DataFrame) -> pd.DataFrame:
    x = add_indicators(h4)
    compressed = x["atr_pct"].shift(1) < x["atr_q35_prior"]
    long_signal = (
        compressed
        & (x["ema50"] > x["ema200"])
        & (x["close"] > x["prior_high20"])
    )
    short_signal = (
        compressed
        & (x["ema50"] < x["ema200"])
        & (x["close"] < x["prior_low20"])
    )
    direction = np.where(long_signal, 1, np.where(short_signal, -1, 0))

    rows: list[dict[str, object]] = []
    index = 0
    while index < len(x) - 1:
        side = int(direction[index])
        if side == 0:
            index += 1
            continue
        atr = float(x.loc[index, "atr14"])
        if not np.isfinite(atr) or atr <= 0:
            index += 1
            continue

        entry_index = index + 1
        entry = float(x.loc[entry_index, "open"])
        risk = 1.5 * atr
        stop = entry - side * risk
        target = entry + side * 3.0 * atr
        final_index = min(len(x) - 1, entry_index + 23)
        exit_index = final_index
        gross_r: float | None = None
        exit_reason = "TIME"

        for probe in range(entry_index, final_index + 1):
            high = float(x.loc[probe, "high"])
            low = float(x.loc[probe, "low"])
            if side > 0:
                stop_hit = low <= stop
                target_hit = high >= target
            else:
                stop_hit = high >= stop
                target_hit = low <= target
            if stop_hit:
                gross_r = -1.0
                exit_index = probe
                exit_reason = "STOP"
                break
            if target_hit:
                gross_r = 2.0
                exit_index = probe
                exit_reason = "TARGET"
                break

        if gross_r is None:
            exit_price = float(x.loc[exit_index, "close"])
            gross_r = side * (exit_price - entry) / risk

        rows.append(
            {
                "signal_time": x.loc[index, "time"],
                "entry_time": x.loc[entry_index, "time"],
                "exit_time": x.loc[exit_index, "time"],
                "direction": side,
                "entry": entry,
                "risk_price": risk,
                "gross_r": gross_r,
                "base_net_r": gross_r - BASE_COST_ABS / risk,
                "stress_net_r": gross_r - STRESS_COST_ABS / risk,
                "exit_reason": exit_reason,
            }
        )
        # Preserve frozen standalone strategy semantics: one shadow position at a time.
        index = exit_index + 1

    trades = pd.DataFrame(rows)
    if trades.empty:
        raise RuntimeError("USDJPY H4 compression generated no shadow trades")
    return trades.sort_values("entry_time").reset_index(drop=True)


def _profit_factor(values: np.ndarray) -> float:
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    if losses <= 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def _eligible_history(
    completed: pd.DataFrame,
    entry_time: pd.Timestamp,
    candidate: AdaptiveCandidate,
) -> pd.DataFrame:
    history = completed[completed["exit_time"] < entry_time]
    if candidate.mode == "TRADES":
        assert candidate.lookback_trades is not None
        return history.tail(candidate.lookback_trades)
    if candidate.mode == "DAYS":
        assert candidate.lookback_days is not None
        cutoff = entry_time - pd.Timedelta(days=candidate.lookback_days)
        return history[history["exit_time"] >= cutoff]
    raise ValueError(f"unknown adaptive mode {candidate.mode}")


def apply_adaptive_router(
    shadow: pd.DataFrame,
    candidate: AdaptiveCandidate,
) -> pd.DataFrame:
    selected: list[dict[str, object]] = []
    for idx, row in shadow.iterrows():
        history = _eligible_history(shadow.iloc[:idx], row["entry_time"], candidate)
        if len(history) < candidate.min_count:
            continue
        values = history["stress_net_r"].to_numpy(float)
        expectancy = float(values.mean())
        profit_factor = _profit_factor(values)
        if expectancy < candidate.min_expectancy_r:
            continue
        if profit_factor < candidate.min_profit_factor:
            continue
        record = dict(row)
        record["router_history_n"] = int(len(history))
        record["router_expectancy_r"] = expectancy
        record["router_profit_factor"] = profit_factor
        selected.append(record)
    if not selected:
        return pd.DataFrame(columns=[*shadow.columns, "router_history_n"])
    return pd.DataFrame(selected).reset_index(drop=True)


def _split(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    if label == "development":
        return frame[frame["entry_time"] < VALIDATION_START]
    if label == "validation":
        return frame[
            (frame["entry_time"] >= VALIDATION_START)
            & (frame["entry_time"] < OOS_START)
        ]
    if label == "oos":
        return frame[frame["entry_time"] >= OOS_START]
    raise ValueError(label)


def metrics(frame: pd.DataFrame, *, column: str = "stress_net_r") -> dict[str, object]:
    if frame.empty:
        return {
            "trades": 0,
            "net_r": 0.0,
            "expectancy_r": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "max_dd_r": 0.0,
            "bootstrap_positive_fraction_500": 0.0,
        }
    values = frame[column].to_numpy(float)
    equity = np.cumsum(values)
    peak = np.maximum.accumulate(np.r_[0.0, equity])
    drawdown = peak[1:] - equity
    rng = np.random.default_rng(SEED)
    positive = 0
    for _ in range(500):
        sample = rng.choice(values, size=len(values), replace=True)
        if float(sample.mean()) > 0:
            positive += 1
    return {
        "trades": int(len(values)),
        "net_r": float(values.sum()),
        "expectancy_r": float(values.mean()),
        "profit_factor": float(_profit_factor(values)),
        "win_rate": float((values > 0).mean()),
        "max_dd_r": float(drawdown.max() if len(drawdown) else 0.0),
        "bootstrap_positive_fraction_500": positive / 500.0,
    }


def _active_ratio(selected: pd.DataFrame, shadow: pd.DataFrame, split: str) -> float:
    denominator = len(_split(shadow, split))
    if denominator == 0:
        return 0.0
    return len(_split(selected, split)) / denominator


def pass_gate(
    validation: dict[str, object],
    oos: dict[str, object],
    *,
    validation_active_ratio: float,
    oos_active_ratio: float,
) -> bool:
    return bool(
        int(validation["trades"]) >= 40
        and float(validation["expectancy_r"]) >= 0.05
        and float(validation["profit_factor"]) >= 1.10
        and float(validation["max_dd_r"]) <= 12.0
        and float(validation["bootstrap_positive_fraction_500"]) >= 0.70
        and validation_active_ratio >= 0.25
        and int(oos["trades"]) >= 15
        and float(oos["expectancy_r"]) >= 0.03
        and float(oos["profit_factor"]) >= 1.05
        and float(oos["max_dd_r"]) <= 8.0
        and float(oos["bootstrap_positive_fraction_500"]) >= 0.65
        and oos_active_ratio >= 0.25
    )


def main() -> None:
    print("FETCH USDJPY H1 2012-2026")
    h1 = fetch_h1()
    h4 = resample_h4(h1)
    shadow = generate_shadow_trades(h4)

    shadow_metrics = {
        split: metrics(_split(shadow, split))
        for split in ("development", "validation", "oos")
    }
    rows: list[dict[str, object]] = []
    for candidate in FROZEN_CANDIDATES:
        selected = apply_adaptive_router(shadow, candidate)
        by_split = {
            split: metrics(_split(selected, split))
            for split in ("development", "validation", "oos")
        }
        validation_ratio = _active_ratio(selected, shadow, "validation")
        oos_ratio = _active_ratio(selected, shadow, "oos")
        passed = pass_gate(
            by_split["validation"],
            by_split["oos"],
            validation_active_ratio=validation_ratio,
            oos_active_ratio=oos_ratio,
        )
        rows.append(
            {
                "candidate": candidate.name,
                "parameters": asdict(candidate),
                "development": by_split["development"],
                "validation": by_split["validation"],
                "oos": by_split["oos"],
                "validation_active_ratio": validation_ratio,
                "oos_active_ratio": oos_ratio,
                "historical_pass": passed,
            }
        )

    ranked = sorted(
        rows,
        key=lambda row: (
            float(row["validation"]["expectancy_r"]),
            float(row["validation"]["profit_factor"]),
            -float(row["validation"]["max_dd_r"]),
        ),
        reverse=True,
    )
    result = {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": False,
        "source": "DUKASCOPY_PUBLIC_BID_H1",
        "symbol": "USDJPY",
        "shadow_strategy": "H4_COMPRESSION_BREAKOUT",
        "shadow_geometry": {
            "stop_atr": 1.5,
            "target_atr": 3.0,
            "reward_r": 2.0,
            "max_hold_h4": 24,
            "same_bar_policy": SAME_BAR_POLICY,
        },
        "router_evidence": (
            "prior completed shadow trades only; disabled periods still generate "
            "shadow outcomes so the router can causally reactivate"
        ),
        "cost_contract": {
            "base_round_trip_pips": 1.2,
            "router_and_gate_stress_round_trip_pips": 1.5,
        },
        "partitions": {
            "development": "2012-01..2020-12",
            "validation": "2021-01..2024-12",
            "oos_final_audit": "2025-01..2026-08",
            "oos_used_for_selection": False,
        },
        "gate": {
            "validation_trades_min": 40,
            "validation_expectancy_min_r": 0.05,
            "validation_pf_min": 1.10,
            "validation_max_dd_r": 12.0,
            "validation_bootstrap_positive_min": 0.70,
            "validation_active_ratio_min": 0.25,
            "oos_trades_min": 15,
            "oos_expectancy_min_r": 0.03,
            "oos_pf_min": 1.05,
            "oos_max_dd_r": 8.0,
            "oos_bootstrap_positive_min": 0.65,
            "oos_active_ratio_min": 0.25,
            "purpose": "research/shadow eligibility only; never direct execution authority",
        },
        "coverage": {
            "h1_rows": int(len(h1)),
            "h1_start": str(h1["time"].min()),
            "h1_end": str(h1["time"].max()),
            "h4_rows": int(len(h4)),
            "shadow_trades": int(len(shadow)),
        },
        "shadow_baseline_stress": shadow_metrics,
        "validation_ranking": [row["candidate"] for row in ranked],
        "historical_pass": [
            row["candidate"] for row in ranked if row["historical_pass"]
        ],
        "rows": ranked,
    }

    output = Path("research_output_usdjpy_h4_adaptive_v1")
    output.mkdir(exist_ok=True)
    (output / "usdjpy_h4_adaptive_regime_v1.json").write_text(
        json.dumps(result, indent=2, default=str, allow_nan=False),
        encoding="utf-8",
    )
    shadow.to_csv(output / "usdjpy_h4_shadow_trades_v1.csv", index=False)
    print(json.dumps(result, sort_keys=True, default=str, allow_nan=False))


if __name__ == "__main__":
    main()
