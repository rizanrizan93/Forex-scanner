from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import five_core_tournament_v1 as base

CONTRACT = "XAU_D1_STAGGERED_V14"
EXECUTION_INFLUENCE = False
SYMBOL = "XAUUSD"
STOP_ATR = 2.0
MAX_HOLD_DAYS = 30
MAX_ACTIVE_TRANCHES = 10
CADENCES = (1, 2, 3, 5)
TARGET_RS = (1.0, 1.25, 1.5, 2.0)
BASE_COST_USD = 0.17
STRESS_COST_USD = 0.35

DEV_START = pd.Timestamp("2012-01-01", tz="UTC")
VALIDATION_START = pd.Timestamp("2021-01-01", tz="UTC")
OOS_START = pd.Timestamp("2025-01-01", tz="UTC")
END_EXCLUSIVE = pd.Timestamp("2026-09-01", tz="UTC")

DEV_GATE = {
    "trades_min": 150,
    "expectancy_r_min": 0.05,
    "profit_factor_min": 1.10,
}
VALIDATION_GATE = {
    "trades_min": 100,
    "expectancy_r_min": 0.05,
    "profit_factor_min": 1.10,
}
OOS_GATE = {
    "trades_min": 100,
    "win_rate_min": 0.55,
    "expectancy_r_min": 0.15,
    "profit_factor_min": 1.30,
}


@dataclass(frozen=True, slots=True)
class Variant:
    cadence_days: int
    target_r: float
    max_active: int = MAX_ACTIVE_TRANCHES

    @property
    def variant_id(self) -> str:
        r = int(round(self.target_r * 100))
        return f"XAU_D1_TSMOM_STAGGER_C{self.cadence_days}_R{r:03d}_MAX{self.max_active}_V14"


VARIANTS = tuple(
    Variant(cadence_days=cadence, target_r=target_r)
    for cadence in CADENCES
    for target_r in TARGET_RS
)


def _daily_frame(h1: pd.DataFrame) -> pd.DataFrame:
    d1 = base.add_indicators(base.resample_ohlc(h1, "1D"))
    long_sig = (d1["close"] > d1["ema200"]) & (d1["ret60"] > 0)
    short_sig = (d1["close"] < d1["ema200"]) & (d1["ret60"] < 0)
    d1["direction"] = np.where(long_sig, 1, np.where(short_sig, -1, 0)).astype(int)
    return d1.reset_index(drop=True)


def _simulate_one(
    d1: pd.DataFrame,
    *,
    signal_i: int,
    variant: Variant,
) -> dict | None:
    if signal_i >= len(d1) - 1:
        return None
    direction = int(d1.loc[signal_i, "direction"])
    atr = float(d1.loc[signal_i, "atr14"])
    if direction == 0 or not np.isfinite(atr) or atr <= 0:
        return None

    entry_i = signal_i + 1
    entry = float(d1.loc[entry_i, "open"])
    risk = STOP_ATR * atr
    stop = entry - direction * risk
    target = entry + direction * variant.target_r * risk
    last_i = min(len(d1) - 1, entry_i + MAX_HOLD_DAYS - 1)

    gross_r = None
    exit_i = last_i
    exit_reason = "TIME"
    mfe_r = 0.0
    mae_r = 0.0
    for j in range(entry_i, last_i + 1):
        hi = float(d1.loc[j, "high"])
        lo = float(d1.loc[j, "low"])
        if direction > 0:
            mfe_r = max(mfe_r, (hi - entry) / risk)
            mae_r = min(mae_r, (lo - entry) / risk)
            stop_hit = lo <= stop
            target_hit = hi >= target
        else:
            mfe_r = max(mfe_r, (entry - lo) / risk)
            mae_r = min(mae_r, (entry - hi) / risk)
            stop_hit = hi >= stop
            target_hit = lo <= target

        # Frozen conservative ambiguity contract.
        if stop_hit:
            gross_r = -1.0
            exit_i = j
            exit_reason = "STOP_FIRST_AMBIGUOUS" if target_hit else "STOP"
            break
        if target_hit:
            gross_r = float(variant.target_r)
            exit_i = j
            exit_reason = "TARGET"
            break

    if gross_r is None:
        exit_price = float(d1.loc[exit_i, "close"])
        gross_r = direction * (exit_price - entry) / risk

    return {
        "variant_id": variant.variant_id,
        "signal_i": signal_i,
        "entry_i": entry_i,
        "exit_i": exit_i,
        "signal_time": d1.loc[signal_i, "time"],
        "entry_time": d1.loc[entry_i, "time"],
        "exit_time": d1.loc[exit_i, "time"],
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk_price": risk,
        "gross_r": float(gross_r),
        "mfe_r": float(mfe_r),
        "mae_r": float(mae_r),
        "exit_reason": exit_reason,
    }


def simulate_staggered(d1: pd.DataFrame, *, variant: Variant) -> pd.DataFrame:
    rows: list[dict] = []
    active_exit_indices: list[int] = []
    last_signal_i: int | None = None

    for signal_i in range(len(d1) - 1):
        direction = int(d1.loc[signal_i, "direction"])
        if direction == 0:
            continue

        entry_i = signal_i + 1
        active_exit_indices = [idx for idx in active_exit_indices if idx >= entry_i]
        if len(active_exit_indices) >= variant.max_active:
            continue
        if last_signal_i is not None and signal_i - last_signal_i < variant.cadence_days:
            continue

        trade = _simulate_one(d1, signal_i=signal_i, variant=variant)
        if trade is None:
            continue
        rows.append(trade)
        active_exit_indices.append(int(trade["exit_i"]))
        last_signal_i = signal_i

    return pd.DataFrame(rows)


def _repriced(df: pd.DataFrame, *, cost_abs: float) -> pd.DataFrame:
    out = df.copy()
    if out.empty:
        out["net_r"] = pd.Series(dtype=float)
        return out
    out["net_r"] = out["gross_r"].astype(float) - float(cost_abs) / out["risk_price"].astype(float)
    return out


def _metrics(df: pd.DataFrame, *, cost_abs: float) -> dict:
    if df.empty:
        return {
            "trades": 0,
            "win_rate": None,
            "expectancy_r": None,
            "profit_factor": None,
            "net_r": 0.0,
            "max_realized_drawdown_r": None,
            "max_losing_streak": 0,
        }

    x = _repriced(df, cost_abs=cost_abs).sort_values(["exit_time", "entry_time"]).reset_index(drop=True)
    values = x["net_r"].to_numpy(float)
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    equity = np.cumsum(values)
    peak = np.maximum.accumulate(np.r_[0.0, equity])
    dd = peak[1:] - equity

    streak = 0
    max_streak = 0
    for value in values:
        if value < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    return {
        "trades": int(len(values)),
        "win_rate": float((values > 0).mean()),
        "expectancy_r": float(values.mean()),
        "profit_factor": None if losses <= 0 else gains / losses,
        "net_r": float(values.sum()),
        "max_realized_drawdown_r": float(dd.max() if len(dd) else 0.0),
        "max_losing_streak": int(max_streak),
    }


def _concurrency(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"max_active": 0, "mean_active_on_entry": 0.0, "p95_active_on_entry": 0.0}
    rows = df.sort_values("entry_time")
    counts = []
    for _, trade in rows.iterrows():
        entry = trade["entry_time"]
        active = rows[(rows["entry_time"] <= entry) & (rows["exit_time"] >= entry)]
        counts.append(int(len(active)))
    return {
        "max_active": int(max(counts)),
        "mean_active_on_entry": float(np.mean(counts)),
        "p95_active_on_entry": float(np.quantile(counts, 0.95)),
    }


def _period(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    return df[(df["entry_time"] >= start) & (df["entry_time"] < end)].copy()


def _gate(metrics: dict, gate: dict) -> bool:
    return bool(
        metrics["trades"] >= int(gate["trades_min"])
        and metrics["expectancy_r"] is not None
        and metrics["expectancy_r"] >= float(gate["expectancy_r_min"])
        and metrics["profit_factor"] is not None
        and metrics["profit_factor"] >= float(gate["profit_factor_min"])
    )


def _oos_gate(metrics: dict) -> bool:
    return bool(
        metrics["trades"] >= int(OOS_GATE["trades_min"])
        and metrics["win_rate"] is not None
        and metrics["win_rate"] >= float(OOS_GATE["win_rate_min"])
        and metrics["expectancy_r"] is not None
        and metrics["expectancy_r"] >= float(OOS_GATE["expectancy_r_min"])
        and metrics["profit_factor"] is not None
        and metrics["profit_factor"] >= float(OOS_GATE["profit_factor_min"])
    )


def build_report(h1: pd.DataFrame) -> dict:
    d1 = _daily_frame(h1)
    dev_rows = []
    candidate_trades: dict[str, pd.DataFrame] = {}

    # Selection sees DEV + VALIDATION only. OOS is intentionally not calculated here.
    for variant in VARIANTS:
        trades = simulate_staggered(d1, variant=variant)
        candidate_trades[variant.variant_id] = trades
        dev = _period(trades, DEV_START, VALIDATION_START)
        validation = _period(trades, VALIDATION_START, OOS_START)
        dev_base = _metrics(dev, cost_abs=BASE_COST_USD)
        dev_stress = _metrics(dev, cost_abs=STRESS_COST_USD)
        val_base = _metrics(validation, cost_abs=BASE_COST_USD)
        val_stress = _metrics(validation, cost_abs=STRESS_COST_USD)
        passed = bool(_gate(dev_stress, DEV_GATE) and _gate(val_stress, VALIDATION_GATE))
        dev_rows.append({
            "variant": asdict(variant),
            "variant_id": variant.variant_id,
            "dev_base": dev_base,
            "dev_stress": dev_stress,
            "validation_base": val_base,
            "validation_stress": val_stress,
            "dev_concurrency": _concurrency(dev),
            "validation_concurrency": _concurrency(validation),
            "development_passed": passed,
        })

    eligible = [row for row in dev_rows if row["development_passed"]]
    eligible.sort(
        key=lambda row: (
            float(row["validation_stress"]["expectancy_r"] or -999.0),
            float(row["validation_stress"]["profit_factor"] or -999.0),
            float(row["validation_stress"]["win_rate"] or -999.0),
            -float(row["validation_stress"]["max_realized_drawdown_r"] or 999.0),
        ),
        reverse=True,
    )
    selected = eligible[0] if eligible else None

    oos = None
    promotion_eligible = False
    if selected is not None:
        variant_id = selected["variant_id"]
        selected_trades = candidate_trades[variant_id]
        locked = _period(selected_trades, OOS_START, END_EXCLUSIVE)
        base_metrics = _metrics(locked, cost_abs=BASE_COST_USD)
        stress_metrics = _metrics(locked, cost_abs=STRESS_COST_USD)
        promotion_eligible = _oos_gate(stress_metrics)
        oos = {
            "variant_id": variant_id,
            "base": base_metrics,
            "stressed": stress_metrics,
            "concurrency": _concurrency(locked),
            "passed": promotion_eligible,
            "gate": OOS_GATE,
        }

    regime_days = d1[d1["direction"] != 0]
    total_days = d1[(d1["time"] >= DEV_START) & (d1["time"] < END_EXCLUSIVE)]
    return {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": False,
        "symbol": SYMBOL,
        "data_source": "Dukascopy Bank public BID H1 via dukascopy-python",
        "history": {
            "h1_rows": int(len(h1)),
            "h1_start": str(h1["time"].min()),
            "h1_end": str(h1["time"].max()),
            "d1_rows": int(len(d1)),
            "regime_signal_days": int(len(regime_days)),
            "calendar_trading_days": int(len(total_days)),
        },
        "frozen_rule": {
            "regime": "D1 close > EMA200 and 60D return > 0 for LONG; inverse for SHORT",
            "entry": "next D1 open on cadence while regime is active and active tranche cap is available",
            "stop": f"{STOP_ATR} ATR14",
            "targets_r": list(TARGET_RS),
            "max_hold_days": MAX_HOLD_DAYS,
            "cadences_days": list(CADENCES),
            "max_active_tranches": MAX_ACTIVE_TRANCHES,
            "same_bar_policy": "STOP_FIRST",
        },
        "costs_usd_round_trip": {
            "base": BASE_COST_USD,
            "stress": STRESS_COST_USD,
        },
        "split_contract": {
            "development": "2012-01-01..2020-12-31",
            "validation": "2021-01-01..2024-12-31",
            "locked_oos": "2025-01-01..2026-08-31",
            "oos_used_for_selection": False,
        },
        "development_gate": DEV_GATE,
        "validation_gate": VALIDATION_GATE,
        "variants": dev_rows,
        "selected_variant": None if selected is None else selected["variant_id"],
        "locked_oos": oos,
        "promotion_eligible": promotion_eligible,
        "risk_note": (
            "Per-tranche R is not a recommended account risk size. Overlapping tranches are correlated; "
            "production sizing must enforce the existing account-wide exposure and per-trade risk guards."
        ),
    }


def main() -> None:
    base.SYMBOLS = {SYMBOL: base.SYMBOLS[SYMBOL]}
    base.SLOW_START = pd.Timestamp("2012-01-01").to_pydatetime()
    print("FETCH XAUUSD H1 2012-2026")
    h1 = base.fetch_h1(SYMBOL)
    report = build_report(h1)

    out = Path("research_output_xau_d1_staggered_v14")
    out.mkdir(exist_ok=True)
    path = out / "xau_d1_staggered_v14.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(
        "XAU_D1_STAGGERED_V14 "
        f"h1_rows={report['history']['h1_rows']} "
        f"selected={report['selected_variant']} "
        f"holdout_opened={int(report['locked_oos'] is not None)} "
        f"promotion_eligible={int(bool(report['promotion_eligible']))}"
    )
    if report["locked_oos"] is not None:
        print("LOCKED_OOS", json.dumps(report["locked_oos"], sort_keys=True))
    print("Research only: execution_influence=false")


if __name__ == "__main__":
    main()
