from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import dukascopy_python
import numpy as np
import pandas as pd
from dukascopy_python import instruments

CONTRACT = "XAU_D1_ADAPTIVE_REGIME_V1"
EXECUTION_INFLUENCE = False
SEED = 20260913
SYMBOL = "XAUUSD"
DATA_START = datetime(2012, 1, 1)
DATA_END = datetime(2026, 9, 1)
DATA_END_TS = pd.Timestamp("2026-09-01", tz="UTC")
VALIDATION_START = pd.Timestamp("2018-01-01", tz="UTC")
OOS_START = pd.Timestamp("2025-01-01", tz="UTC")
NY = ZoneInfo("America/New_York")
BASE_COST_USD = 0.17
STRESS_COST_USD = 0.35
STOP_ATR = 2.0
TARGET_ATR = 4.0
MAX_HOLD_D1 = 30
MIN_TRADES_3Y = 30
MIN_TRADES_5Y = 50


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
        "ADAPT_20_E000_PF105", "TRADES", 20, None, 20, 0.00, 1.05
    ),
    AdaptiveCandidate(
        "ADAPT_30_E000_PF105", "TRADES", 30, None, 30, 0.00, 1.05
    ),
    AdaptiveCandidate(
        "ADAPT_40_E000_PF110", "TRADES", 40, None, 40, 0.00, 1.10
    ),
    AdaptiveCandidate(
        "ADAPT_3Y_E000_PF105", "DAYS", None, 1095, 30, 0.00, 1.05
    ),
)

ROLLING_GATE = {
    "base": {
        "min_positive_ratio_3y": 0.70,
        "min_positive_ratio_5y": 0.80,
        "min_latest_expectancy_3y": 0.0,
        "min_latest_expectancy_5y": 0.0,
        "min_worst_expectancy_5y": -0.05,
    },
    "stress": {
        "min_positive_ratio_3y": 0.60,
        "min_positive_ratio_5y": 0.70,
        "min_latest_expectancy_3y": 0.0,
        "min_latest_expectancy_5y": 0.0,
        "min_worst_expectancy_5y": -0.075,
    },
    "min_eligible_window_ratio": 0.90,
}


def _normalize(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise RuntimeError("XAUUSD: empty Dukascopy H1 history")
    frame = raw.copy().reset_index()
    columns = {str(column).lower(): column for column in frame.columns}
    time_column = columns.get("timestamp") or columns.get("time") or frame.columns[0]
    out = pd.DataFrame()
    out["time"] = pd.to_datetime(frame[time_column], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close"):
        source = columns.get(column)
        if source is None:
            raise RuntimeError(f"XAUUSD missing {column}; columns={list(frame.columns)}")
        out[column] = pd.to_numeric(frame[source], errors="coerce")
    out = (
        out.dropna()
        .drop_duplicates("time")
        .sort_values("time")
        .reset_index(drop=True)
    )
    if len(out) < 50_000:
        raise RuntimeError(f"XAUUSD insufficient H1 history: {len(out)}")
    return out


def fetch_h1() -> pd.DataFrame:
    raw = dukascopy_python.fetch(
        instrument=instruments.INSTRUMENT_FX_METALS_XAU_USD,
        interval=dukascopy_python.INTERVAL_HOUR_1,
        offer_side=dukascopy_python.OFFER_SIDE_BID,
        start=DATA_START,
        end=DATA_END,
        max_retries=3,
    )
    return _normalize(raw)


def _session_start_utc(session_date) -> pd.Timestamp:
    local_start = datetime.combine(session_date, time(17, 0), tzinfo=NY)
    return pd.Timestamp(local_start).tz_convert("UTC")


def aggregate_new_york_17(h1: pd.DataFrame) -> pd.DataFrame:
    frame = h1.copy().sort_values("time").reset_index(drop=True)
    local = frame["time"].dt.tz_convert(NY)
    frame["session_date"] = (local - pd.Timedelta(hours=17)).dt.date
    rows: list[dict[str, object]] = []
    for session_date, day in frame.groupby("session_date", sort=True):
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
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        raise RuntimeError("NY17 D1 aggregation produced no rows")
    return out.sort_values("time").reset_index(drop=True)


def add_indicators(d1: pd.DataFrame) -> pd.DataFrame:
    frame = d1.copy().reset_index(drop=True)
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            (frame["high"] - frame["low"]).abs(),
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr14"] = true_range.ewm(
        alpha=1 / 14, adjust=False, min_periods=14
    ).mean()
    frame["ema200"] = frame["close"].ewm(
        span=200, adjust=False, min_periods=200
    ).mean()
    frame["ret60"] = frame["close"] / frame["close"].shift(60) - 1.0
    return frame


def generate_shadow_trades(d1: pd.DataFrame) -> pd.DataFrame:
    frame = add_indicators(d1)
    long_signal = (frame["close"] > frame["ema200"]) & (frame["ret60"] > 0)
    short_signal = (frame["close"] < frame["ema200"]) & (frame["ret60"] < 0)
    direction = np.where(long_signal, 1, np.where(short_signal, -1, 0))

    rows: list[dict[str, object]] = []
    index = 0
    while index < len(frame) - 1:
        side = int(direction[index])
        if side == 0:
            index += 1
            continue
        atr = float(frame.loc[index, "atr14"])
        if not np.isfinite(atr) or atr <= 0:
            index += 1
            continue

        entry_index = index + 1
        entry = float(frame.loc[entry_index, "open"])
        risk = STOP_ATR * atr
        stop = entry - side * risk
        target = entry + side * TARGET_ATR * atr
        final_index = min(len(frame) - 1, entry_index + MAX_HOLD_D1 - 1)
        exit_index = final_index
        gross_r: float | None = None
        exit_reason = "TIME"

        for probe in range(entry_index, final_index + 1):
            high = float(frame.loc[probe, "high"])
            low = float(frame.loc[probe, "low"])
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
                gross_r = TARGET_ATR / STOP_ATR
                exit_index = probe
                exit_reason = "TARGET"
                break

        if gross_r is None:
            exit_price = float(frame.loc[exit_index, "close"])
            gross_r = side * (exit_price - entry) / risk

        rows.append(
            {
                "signal_time": frame.loc[index, "time"],
                "entry_time": frame.loc[entry_index, "time"],
                "exit_time": frame.loc[exit_index, "time"],
                "direction": side,
                "entry": entry,
                "risk_price": risk,
                "gross_r": gross_r,
                "base_net_r": gross_r - BASE_COST_USD / risk,
                "stress_net_r": gross_r - STRESS_COST_USD / risk,
                "exit_reason": exit_reason,
            }
        )
        index = exit_index + 1

    trades = pd.DataFrame(rows)
    if trades.empty:
        raise RuntimeError("XAU D1 TSMOM generated no shadow trades")
    return trades.sort_values("entry_time").reset_index(drop=True)


def _profit_factor(values: np.ndarray) -> float:
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    if losses <= 0:
        return 999.0 if gains > 0 else 0.0
    return gains / losses


def _cost_values(frame: pd.DataFrame, cost_abs: float) -> np.ndarray:
    if frame.empty:
        return np.array([], dtype=float)
    return (
        frame["gross_r"].to_numpy(float)
        - float(cost_abs) / frame["risk_price"].to_numpy(float)
    )


def metrics(frame: pd.DataFrame, *, cost_abs: float) -> dict[str, object]:
    values = _cost_values(frame, cost_abs)
    if len(values) == 0:
        return {
            "trades": 0,
            "net_r": 0.0,
            "expectancy_r": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "max_dd_r": 0.0,
            "bootstrap_positive_fraction_500": 0.0,
        }
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
    raise ValueError(candidate.mode)


def apply_adaptive_router(
    shadow: pd.DataFrame,
    candidate: AdaptiveCandidate,
) -> pd.DataFrame:
    selected: list[dict[str, object]] = []
    for index, row in shadow.iterrows():
        history = _eligible_history(shadow.iloc[:index], row["entry_time"], candidate)
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


def _partition(frame: pd.DataFrame, label: str) -> pd.DataFrame:
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


def _annual_windows(years: int, first_start: int, last_complete_start: int):
    rows = []
    for year in range(first_start, last_complete_start + 1):
        start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        end = pd.Timestamp(f"{year + years}-01-01", tz="UTC")
        rows.append((f"{year}_{year + years - 1}", start, end, False))
    latest_start = DATA_END_TS - pd.DateOffset(years=years)
    rows.append(
        (
            f"LATEST_TRAILING_{years}Y",
            pd.Timestamp(latest_start),
            DATA_END_TS,
            True,
        )
    )
    return rows


WINDOWS = {
    "3Y": _annual_windows(3, 2012, 2022),
    "5Y": _annual_windows(5, 2012, 2020),
}


def rolling_rows(
    trades: pd.DataFrame,
    *,
    cost_abs: float,
    window_type: str,
) -> list[dict[str, object]]:
    minimum = MIN_TRADES_3Y if window_type == "3Y" else MIN_TRADES_5Y
    output: list[dict[str, object]] = []
    for label, start, end, latest in WINDOWS[window_type]:
        subset = trades[
            (trades["entry_time"] >= start) & (trades["entry_time"] < end)
        ]
        block = metrics(subset, cost_abs=cost_abs)
        output.append(
            {
                "window": label,
                "start": str(start),
                "end_exclusive": str(end),
                "latest": latest,
                "eligible": int(block["trades"]) >= minimum,
                **block,
            }
        )
    return output


def summarize_rolling(rows: list[dict[str, object]]) -> dict[str, object]:
    eligible = [row for row in rows if bool(row["eligible"])]
    positive = [row for row in eligible if float(row["expectancy_r"]) > 0]
    latest = next((row for row in rows if bool(row["latest"])), None)
    worst = min(
        (float(row["expectancy_r"]) for row in eligible),
        default=None,
    )
    return {
        "windows": len(rows),
        "eligible_windows": len(eligible),
        "eligible_ratio": len(eligible) / len(rows) if rows else 0.0,
        "positive_eligible_windows": len(positive),
        "positive_ratio": len(positive) / len(eligible) if eligible else 0.0,
        "worst_expectancy_r": worst,
        "latest": latest,
    }


def rolling_gate(
    cost_kind: str,
    summary_3y: dict[str, object],
    summary_5y: dict[str, object],
) -> dict[str, object]:
    thresholds = ROLLING_GATE[cost_kind]
    latest3 = summary_3y["latest"] or {}
    latest5 = summary_5y["latest"] or {}
    checks = {
        "eligible_ratio_3y": float(summary_3y["eligible_ratio"])
        >= ROLLING_GATE["min_eligible_window_ratio"],
        "eligible_ratio_5y": float(summary_5y["eligible_ratio"])
        >= ROLLING_GATE["min_eligible_window_ratio"],
        "positive_ratio_3y": float(summary_3y["positive_ratio"])
        >= thresholds["min_positive_ratio_3y"],
        "positive_ratio_5y": float(summary_5y["positive_ratio"])
        >= thresholds["min_positive_ratio_5y"],
        "latest_expectancy_3y": bool(latest3.get("eligible"))
        and float(latest3.get("expectancy_r", 0.0))
        > thresholds["min_latest_expectancy_3y"],
        "latest_expectancy_5y": bool(latest5.get("eligible"))
        and float(latest5.get("expectancy_r", 0.0))
        > thresholds["min_latest_expectancy_5y"],
        "worst_expectancy_5y": summary_5y["worst_expectancy_r"] is not None
        and float(summary_5y["worst_expectancy_r"])
        >= thresholds["min_worst_expectancy_5y"],
    }
    return {"checks": checks, "passed": all(checks.values())}


def rolling_evaluation(trades: pd.DataFrame) -> dict[str, object]:
    output: dict[str, object] = {}
    for cost_kind, cost_abs in (
        ("base", BASE_COST_USD),
        ("stress", STRESS_COST_USD),
    ):
        rows3 = rolling_rows(trades, cost_abs=cost_abs, window_type="3Y")
        rows5 = rolling_rows(trades, cost_abs=cost_abs, window_type="5Y")
        summary3 = summarize_rolling(rows3)
        summary5 = summarize_rolling(rows5)
        output[cost_kind] = {
            "cost_abs_usd": cost_abs,
            "summary_3y": summary3,
            "summary_5y": summary5,
            "gate": rolling_gate(cost_kind, summary3, summary5),
        }
    output["passed"] = bool(
        output["base"]["gate"]["passed"]
        and output["stress"]["gate"]["passed"]
    )
    return output


def candidate_pass(
    *,
    validation: dict[str, object],
    oos: dict[str, object],
    validation_active_ratio: float,
    oos_active_ratio: float,
    rolling: dict[str, object],
) -> bool:
    return bool(
        int(validation["trades"]) >= 30
        and float(validation["expectancy_r"]) >= 0.05
        and float(validation["profit_factor"]) >= 1.10
        and float(validation["bootstrap_positive_fraction_500"]) >= 0.70
        and validation_active_ratio >= 0.25
        and int(oos["trades"]) >= 15
        and float(oos["expectancy_r"]) > 0.0
        and float(oos["profit_factor"]) >= 1.05
        and float(oos["bootstrap_positive_fraction_500"]) >= 0.65
        and oos_active_ratio >= 0.25
        and bool(rolling["passed"])
    )


def main() -> None:
    print("FETCH XAUUSD H1 2012-2026")
    h1 = fetch_h1()
    d1 = aggregate_new_york_17(h1)
    shadow = generate_shadow_trades(d1)

    shadow_rolling = rolling_evaluation(shadow)
    shadow_partitions = {
        label: metrics(_partition(shadow, label), cost_abs=STRESS_COST_USD)
        for label in ("development", "validation", "oos")
    }

    rows: list[dict[str, object]] = []
    for candidate in FROZEN_CANDIDATES:
        selected = apply_adaptive_router(shadow, candidate)
        validation = metrics(
            _partition(selected, "validation"), cost_abs=STRESS_COST_USD
        )
        oos = metrics(_partition(selected, "oos"), cost_abs=STRESS_COST_USD)
        validation_shadow_n = len(_partition(shadow, "validation"))
        oos_shadow_n = len(_partition(shadow, "oos"))
        validation_ratio = (
            len(_partition(selected, "validation")) / validation_shadow_n
            if validation_shadow_n
            else 0.0
        )
        oos_ratio = (
            len(_partition(selected, "oos")) / oos_shadow_n
            if oos_shadow_n
            else 0.0
        )
        rolling = rolling_evaluation(selected)
        passed = candidate_pass(
            validation=validation,
            oos=oos,
            validation_active_ratio=validation_ratio,
            oos_active_ratio=oos_ratio,
            rolling=rolling,
        )
        rows.append(
            {
                "candidate": candidate.name,
                "parameters": asdict(candidate),
                "development": metrics(
                    _partition(selected, "development"), cost_abs=STRESS_COST_USD
                ),
                "validation": validation,
                "oos": oos,
                "validation_active_ratio": validation_ratio,
                "oos_active_ratio": oos_ratio,
                "rolling": rolling,
                "historical_pass": passed,
            }
        )

    ranked = sorted(
        rows,
        key=lambda row: (
            bool(row["rolling"]["passed"]),
            float(row["validation"]["expectancy_r"]),
            float(row["validation"]["profit_factor"]),
        ),
        reverse=True,
    )
    result = {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": False,
        "symbol": SYMBOL,
        "source": "DUKASCOPY_PUBLIC_BID_H1",
        "boundary": "17:00 America/New_York DST-aware",
        "shadow_strategy": "D1_TSMOM_60_200",
        "shadow_geometry": {
            "trend": "close vs EMA200",
            "momentum": "60D return same sign",
            "entry": "next D1 open",
            "stop_atr": STOP_ATR,
            "target_atr": TARGET_ATR,
            "reward_r": TARGET_ATR / STOP_ATR,
            "max_hold_d1": MAX_HOLD_D1,
            "same_bar_policy": "STOP_FIRST",
        },
        "router_evidence": (
            "prior completed shadow outcomes at stress $0.35 cost only; disabled "
            "periods keep generating shadow outcomes for causal reactivation"
        ),
        "partitions": {
            "development": "2012-01..2017-12",
            "validation": "2018-01..2024-12",
            "oos_final_audit": "2025-01..2026-08",
            "oos_used_for_selection": False,
        },
        "rolling_contract": {
            "minimum_trades_3y": MIN_TRADES_3Y,
            "minimum_trades_5y": MIN_TRADES_5Y,
            "gate": ROLLING_GATE,
            "same_thresholds_as_prior_XAU_D1_ROLLING_STABILITY_V1": True,
        },
        "candidate_gate": {
            "validation_trades_min": 30,
            "validation_stress_expectancy_min_r": 0.05,
            "validation_stress_pf_min": 1.10,
            "validation_bootstrap_positive_min": 0.70,
            "validation_active_ratio_min": 0.25,
            "oos_trades_min": 15,
            "oos_stress_expectancy_min_r": ">0",
            "oos_stress_pf_min": 1.05,
            "oos_bootstrap_positive_min": 0.65,
            "oos_active_ratio_min": 0.25,
            "rolling_base_and_stress_gate_required": True,
            "purpose": "research/shadow eligibility only; no automatic re-promotion",
        },
        "coverage": {
            "h1_rows": int(len(h1)),
            "h1_start": str(h1["time"].min()),
            "h1_end": str(h1["time"].max()),
            "d1_rows": int(len(d1)),
            "shadow_trades": int(len(shadow)),
        },
        "shadow_baseline_stress": shadow_partitions,
        "shadow_baseline_rolling": shadow_rolling,
        "validation_ranking": [row["candidate"] for row in ranked],
        "historical_pass": [
            row["candidate"] for row in ranked if row["historical_pass"]
        ],
        "rows": ranked,
    }

    output = Path("research_output_xau_d1_adaptive_v1")
    output.mkdir(exist_ok=True)
    (output / "xau_d1_adaptive_regime_v1.json").write_text(
        json.dumps(result, indent=2, default=str, allow_nan=False),
        encoding="utf-8",
    )
    shadow.to_csv(output / "xau_d1_shadow_trades_v1.csv", index=False)
    print(json.dumps(result, sort_keys=True, default=str, allow_nan=False))


if __name__ == "__main__":
    main()
