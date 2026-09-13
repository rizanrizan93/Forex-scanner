from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, time
from pathlib import Path
from random import Random
from statistics import mean, pstdev
from zoneinfo import ZoneInfo

import dukascopy_python
import numpy as np
import pandas as pd
from dukascopy_python import instruments

CONTRACT = "FX_PORTFOLIO_TSMOM_V1"
EXECUTION_INFLUENCE = False
SEED = 20260913
DATA_START = datetime(2012, 1, 1)
DATA_END = datetime(2026, 9, 1)
VALIDATION_START = pd.Timestamp("2021-01-01", tz="UTC")
OOS_START = pd.Timestamp("2025-01-01", tz="UTC")
NY = ZoneInfo("America/New_York")
REBALANCE_BARS = 21
VOL_LOOKBACK = 20
BASE_ROUND_TRIP_PIPS = 1.2
STRESS_ROUND_TRIP_PIPS = 2.0
STRESS_CARRY_PIPS_PER_DAY = 0.20

SYMBOLS = {
    "EURUSD": instruments.INSTRUMENT_FX_MAJORS_EUR_USD,
    "GBPUSD": instruments.INSTRUMENT_FX_MAJORS_GBP_USD,
    "AUDUSD": instruments.INSTRUMENT_FX_MAJORS_AUD_USD,
    "NZDUSD": instruments.INSTRUMENT_FX_MAJORS_NZD_USD,
    "USDJPY": instruments.INSTRUMENT_FX_MAJORS_USD_JPY,
    "USDCAD": instruments.INSTRUMENT_FX_MAJORS_USD_CAD,
    "USDCHF": instruments.INSTRUMENT_FX_MAJORS_USD_CHF,
}


@dataclass(frozen=True, slots=True)
class Candidate:
    name: str
    lookback_days: int
    skip_recent_days: int


FROZEN_CANDIDATES = (
    Candidate("TSMOM_126D_MONTHLY", 126, 0),
    Candidate("TSMOM_252D_MONTHLY", 252, 0),
    Candidate("TSMOM_252D_SKIP21_MONTHLY", 252, 21),
)


@dataclass(frozen=True, slots=True)
class PortfolioDay:
    day: pd.Timestamp
    base_return: float
    stress_return: float
    turnover: float
    gross_exposure: float
    active_symbols: int


def pip_size(symbol: str) -> float:
    return 0.01 if symbol.endswith("JPY") else 0.0001


def _normalize(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise RuntimeError(f"{symbol}: empty H1 history")
    frame = raw.copy().reset_index()
    columns = {str(column).lower(): column for column in frame.columns}
    time_column = columns.get("timestamp") or columns.get("time") or frame.columns[0]
    out = pd.DataFrame()
    out["time"] = pd.to_datetime(frame[time_column], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close"):
        source = columns.get(column)
        if source is None:
            raise RuntimeError(f"{symbol}: missing {column}")
        out[column] = pd.to_numeric(frame[source], errors="coerce")
    out = (
        out.dropna()
        .drop_duplicates("time")
        .sort_values("time")
        .reset_index(drop=True)
    )
    if len(out) < 50_000:
        raise RuntimeError(f"{symbol}: insufficient H1 history {len(out)}")
    return out


def fetch_h1(symbol: str) -> pd.DataFrame:
    raw = dukascopy_python.fetch(
        instrument=SYMBOLS[symbol],
        interval=dukascopy_python.INTERVAL_HOUR_1,
        offer_side=dukascopy_python.OFFER_SIDE_BID,
        start=DATA_START,
        end=DATA_END,
        max_retries=3,
    )
    return _normalize(raw, symbol)


def _session_start_utc(session_date) -> pd.Timestamp:
    local_start = datetime.combine(session_date, time(17, 0), tzinfo=NY)
    return pd.Timestamp(local_start).tz_convert("UTC")


def aggregate_ny17(h1: pd.DataFrame) -> pd.DataFrame:
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
                "close": float(day["close"].iloc[-1]),
            }
        )
    return pd.DataFrame(rows).sort_values("time").reset_index(drop=True)


def common_panel(daily_by_symbol: dict[str, pd.DataFrame]) -> pd.DataFrame:
    panel: pd.DataFrame | None = None
    for symbol, frame in daily_by_symbol.items():
        selected = frame[["time", "open", "close"]].rename(
            columns={
                "open": f"{symbol}_open",
                "close": f"{symbol}_close",
            }
        )
        panel = selected if panel is None else panel.merge(selected, on="time", how="inner")
    if panel is None or panel.empty:
        raise RuntimeError("common FX daily panel is empty")
    return panel.sort_values("time").reset_index(drop=True)


def _signal_return(
    closes: np.ndarray,
    signal_index: int,
    candidate: Candidate,
) -> float | None:
    end = signal_index - candidate.skip_recent_days
    start = end - candidate.lookback_days
    if start < 0 or end < 0:
        return None
    prior = float(closes[start])
    current = float(closes[end])
    if prior <= 0 or current <= 0:
        return None
    return current / prior - 1.0


def _volatility(closes: np.ndarray, signal_index: int) -> float | None:
    start = signal_index - VOL_LOOKBACK
    if start < 0:
        return None
    window = closes[start : signal_index + 1]
    returns = window[1:] / window[:-1] - 1.0
    if len(returns) < VOL_LOOKBACK:
        return None
    sigma = float(np.std(returns, ddof=0))
    return sigma if np.isfinite(sigma) and sigma > 0 else None


def _target_weights(panel: pd.DataFrame, signal_index: int, candidate: Candidate) -> dict[str, float]:
    raw: dict[str, float] = {}
    for symbol in SYMBOLS:
        closes = panel[f"{symbol}_close"].to_numpy(float)
        momentum = _signal_return(closes, signal_index, candidate)
        sigma = _volatility(closes, signal_index)
        if momentum is None or sigma is None or momentum == 0:
            continue
        raw[symbol] = (1.0 if momentum > 0 else -1.0) / sigma
    gross = sum(abs(value) for value in raw.values())
    if gross <= 0:
        return {}
    return {symbol: value / gross for symbol, value in raw.items()}


def _turnover(old: dict[str, float], new: dict[str, float]) -> float:
    return sum(
        abs(new.get(symbol, 0.0) - old.get(symbol, 0.0))
        for symbol in set(old) | set(new)
    )


def _transaction_cost_return(
    old: dict[str, float],
    new: dict[str, float],
    panel: pd.DataFrame,
    entry_index: int,
    round_trip_pips: float,
) -> float:
    total = 0.0
    for symbol in set(old) | set(new):
        change = abs(new.get(symbol, 0.0) - old.get(symbol, 0.0))
        if change <= 0:
            continue
        price = float(panel.loc[entry_index, f"{symbol}_open"])
        if price <= 0:
            continue
        one_way_cost = 0.5 * round_trip_pips * pip_size(symbol) / price
        total += change * one_way_cost
    return total


def _stress_carry_return(
    weights: dict[str, float],
    panel: pd.DataFrame,
    entry_index: int,
) -> float:
    total = 0.0
    for symbol, weight in weights.items():
        price = float(panel.loc[entry_index, f"{symbol}_open"])
        if price <= 0:
            continue
        total += (
            abs(weight)
            * STRESS_CARRY_PIPS_PER_DAY
            * pip_size(symbol)
            / price
        )
    return total


def simulate(panel: pd.DataFrame, candidate: Candidate) -> tuple[PortfolioDay, ...]:
    warmup = candidate.lookback_days + candidate.skip_recent_days + VOL_LOOKBACK + 2
    previous_weights: dict[str, float] = {}
    last_rebalance_index: int | None = None
    rows: list[PortfolioDay] = []

    for entry_index in range(warmup, len(panel) - 1):
        signal_index = entry_index - 1
        rebalance = (
            last_rebalance_index is None
            or entry_index - last_rebalance_index >= REBALANCE_BARS
        )
        if rebalance:
            weights = _target_weights(panel, signal_index, candidate)
            base_cost = _transaction_cost_return(
                previous_weights,
                weights,
                panel,
                entry_index,
                BASE_ROUND_TRIP_PIPS,
            )
            stress_cost = _transaction_cost_return(
                previous_weights,
                weights,
                panel,
                entry_index,
                STRESS_ROUND_TRIP_PIPS,
            )
            turnover = _turnover(previous_weights, weights)
            previous_weights = weights
            last_rebalance_index = entry_index
        else:
            weights = previous_weights
            base_cost = 0.0
            stress_cost = 0.0
            turnover = 0.0

        price_return = 0.0
        for symbol, weight in weights.items():
            entry = float(panel.loc[entry_index, f"{symbol}_open"])
            exit_price = float(panel.loc[entry_index + 1, f"{symbol}_open"])
            if entry > 0:
                price_return += weight * (exit_price / entry - 1.0)

        stress_carry = _stress_carry_return(weights, panel, entry_index)
        rows.append(
            PortfolioDay(
                day=pd.Timestamp(panel.loc[entry_index, "time"]),
                base_return=price_return - base_cost,
                stress_return=price_return - stress_cost - stress_carry,
                turnover=turnover,
                gross_exposure=sum(abs(value) for value in weights.values()),
                active_symbols=len(weights),
            )
        )
    return tuple(rows)


def _total_return(values: list[float]) -> float:
    equity = 1.0
    for value in values:
        equity *= max(0.0, 1.0 + value)
    return equity - 1.0


def _max_drawdown(values: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in values:
        equity *= max(0.0, 1.0 + value)
        peak = max(peak, equity)
        if peak > 0:
            worst = max(worst, (peak - equity) / peak)
    return worst


def _block_bootstrap_positive_fraction(
    values: list[float],
    *,
    trials: int = 500,
    block: int = 21,
) -> float:
    if not values:
        return 0.0
    rng = Random(SEED)
    n = len(values)
    positive = 0
    for _ in range(trials):
        sample: list[float] = []
        while len(sample) < n:
            start = rng.randrange(n)
            sample.extend(values[(start + offset) % n] for offset in range(block))
        if _total_return(sample[:n]) > 0:
            positive += 1
    return positive / trials


def summarize(rows: tuple[PortfolioDay, ...], *, field: str) -> dict[str, float | int]:
    values = [float(getattr(row, field)) for row in rows]
    if not values:
        return {
            "days": 0,
            "total_return": 0.0,
            "annualized_sharpe": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "avg_turnover": 0.0,
            "avg_gross_exposure": 0.0,
            "avg_active_symbols": 0.0,
            "bootstrap_positive_fraction_500": 0.0,
        }
    sigma = pstdev(values)
    sharpe = 0.0 if sigma == 0 else np.sqrt(252.0) * mean(values) / sigma
    return {
        "days": len(values),
        "total_return": _total_return(values),
        "annualized_sharpe": float(sharpe),
        "max_drawdown": _max_drawdown(values),
        "win_rate": sum(value > 0 for value in values) / len(values),
        "avg_turnover": mean(row.turnover for row in rows),
        "avg_gross_exposure": mean(row.gross_exposure for row in rows),
        "avg_active_symbols": mean(row.active_symbols for row in rows),
        "bootstrap_positive_fraction_500": _block_bootstrap_positive_fraction(values),
    }


def partition(rows: tuple[PortfolioDay, ...], label: str) -> tuple[PortfolioDay, ...]:
    if label == "development":
        return tuple(row for row in rows if row.day < VALIDATION_START)
    if label == "validation":
        return tuple(
            row for row in rows if VALIDATION_START <= row.day < OOS_START
        )
    if label == "oos":
        return tuple(row for row in rows if row.day >= OOS_START)
    raise ValueError(label)


def pass_gate(validation: dict[str, float | int], oos: dict[str, float | int]) -> bool:
    return bool(
        int(validation["days"]) >= 900
        and float(validation["total_return"]) > 0.0
        and float(validation["annualized_sharpe"]) >= 0.50
        and float(validation["max_drawdown"]) <= 0.20
        and float(validation["avg_gross_exposure"]) >= 0.95
        and float(validation["bootstrap_positive_fraction_500"]) >= 0.70
        and int(oos["days"]) >= 350
        and float(oos["total_return"]) > 0.0
        and float(oos["annualized_sharpe"]) >= 0.35
        and float(oos["max_drawdown"]) <= 0.20
        and float(oos["avg_gross_exposure"]) >= 0.95
        and float(oos["bootstrap_positive_fraction_500"]) >= 0.65
    )


def main() -> None:
    daily: dict[str, pd.DataFrame] = {}
    coverage: dict[str, object] = {}
    for symbol in SYMBOLS:
        print(f"FETCH {symbol} H1 2012-2026")
        h1 = fetch_h1(symbol)
        d1 = aggregate_ny17(h1)
        daily[symbol] = d1
        coverage[symbol] = {
            "h1_rows": int(len(h1)),
            "h1_start": str(h1["time"].min()),
            "h1_end": str(h1["time"].max()),
            "d1_rows": int(len(d1)),
        }

    panel = common_panel(daily)
    records = []
    for candidate in FROZEN_CANDIDATES:
        portfolio = simulate(panel, candidate)
        partitions = {
            label: partition(portfolio, label)
            for label in ("development", "validation", "oos")
        }
        base = {
            label: summarize(rows, field="base_return")
            for label, rows in partitions.items()
        }
        stress = {
            label: summarize(rows, field="stress_return")
            for label, rows in partitions.items()
        }
        records.append(
            {
                "candidate": candidate.name,
                "parameters": asdict(candidate),
                "base": base,
                "stress": stress,
                "historical_pass": pass_gate(stress["validation"], stress["oos"]),
            }
        )

    ranked = sorted(
        records,
        key=lambda row: (
            float(row["stress"]["validation"]["annualized_sharpe"]),
            float(row["stress"]["validation"]["total_return"]),
        ),
        reverse=True,
    )
    result = {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": False,
        "source": "DUKASCOPY_PUBLIC_BID_H1",
        "symbols": list(SYMBOLS),
        "boundary": "17:00 America/New_York DST-aware",
        "selection_partition": "validation_2021_2024",
        "oos_final_audit": "2025-01..2026-08",
        "oos_used_for_selection": False,
        "portfolio_contract": {
            "signal": "sign of trailing time-series return",
            "volatility_weighting": "inverse 20D realized volatility",
            "gross_exposure_target": 1.0,
            "rebalance_bars": REBALANCE_BARS,
            "entry_mark": "next D1 open after previous completed close signal",
            "return_mark": "next D1 open",
        },
        "cost_contract": {
            "base_round_trip_pips": BASE_ROUND_TRIP_PIPS,
            "stress_round_trip_pips": STRESS_ROUND_TRIP_PIPS,
            "stress_carry_pips_per_gross_per_day": STRESS_CARRY_PIPS_PER_DAY,
            "broker_swap_note": "exact historical broker swap remains a required confirmation gate",
        },
        "gate": {
            "validation_days_min": 900,
            "validation_stress_return_min": ">0",
            "validation_stress_sharpe_min": 0.50,
            "validation_stress_max_dd": 0.20,
            "validation_bootstrap_positive_min": 0.70,
            "oos_days_min": 350,
            "oos_stress_return_min": ">0",
            "oos_stress_sharpe_min": 0.35,
            "oos_stress_max_dd": 0.20,
            "oos_bootstrap_positive_min": 0.65,
            "purpose": "research/shadow eligibility only; no direct execution authority",
        },
        "coverage": coverage,
        "common_panel": {
            "rows": int(len(panel)),
            "start": str(panel["time"].min()),
            "end": str(panel["time"].max()),
        },
        "historical_pass": [
            row["candidate"] for row in ranked if row["historical_pass"]
        ],
        "validation_ranking": [row["candidate"] for row in ranked],
        "rows": ranked,
    }

    output = Path("research_output_fx_portfolio_tsmom_v1")
    output.mkdir(exist_ok=True)
    (output / "fx_portfolio_tsmom_v1.json").write_text(
        json.dumps(result, indent=2, default=str, allow_nan=False),
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True, default=str, allow_nan=False))


if __name__ == "__main__":
    main()
