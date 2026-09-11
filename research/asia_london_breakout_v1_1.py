from __future__ import annotations

import numpy as np
import pandas as pd

import asia_london_breakout_v1 as base

CONTRACT = "ASIA_LONDON_BREAKOUT_V1_1_INDEX_FIX"


def simulate_day_fixed(pair: str, day: pd.DataFrame) -> dict | None:
    asia = day[
        (day["local_minute"] >= base.ASIA_RANGE_START_MINUTE)
        & (day["local_minute"] <= base.ASIA_RANGE_END_MINUTE)
    ]
    window = day[
        (day["local_minute"] >= base.BREAKOUT_START_MINUTE)
        & (day["local_minute"] <= base.BREAKOUT_END_MINUTE)
    ]
    if len(asia) < base.MIN_ASIA_BARS or window.empty:
        return None

    asia_high = float(asia["high"].max())
    asia_low = float(asia["low"].min())
    if not np.isfinite(asia_high) or not np.isfinite(asia_low) or asia_high <= asia_low:
        return None

    trigger_idx = None
    direction = 0
    signal_atr = None
    for idx, row in window.iterrows():
        atr = float(row["atr14"])
        if not np.isfinite(atr) or atr <= 0:
            continue
        if float(row["close"]) > asia_high + base.BREAK_BUFFER_ATR * atr:
            trigger_idx, direction, signal_atr = idx, 1, atr
            break
        if float(row["close"]) < asia_low - base.BREAK_BUFFER_ATR * atr:
            trigger_idx, direction, signal_atr = idx, -1, atr
            break

    if trigger_idx is None:
        return None

    # Methodology correction only: trigger_idx is a GLOBAL dataframe index.
    # Resolve the next candle by position within this day's index instead of
    # comparing the global index against len(day), which discarded later days.
    day_positions = day.index.to_list()
    try:
        trigger_pos = day_positions.index(trigger_idx)
    except ValueError:
        return None
    if trigger_pos + 1 >= len(day_positions):
        return None
    entry_idx = day_positions[trigger_pos + 1]

    entry = float(day.loc[entry_idx, "open"])
    stop_dist = base.STOP_ATR * float(signal_atr)
    if stop_dist <= 0:
        return None
    stop = entry - direction * stop_dist
    target = entry + direction * stop_dist * base.TARGET_R

    after = day.loc[entry_idx:].head(base.MAX_HOLD_BARS + 1)
    if after.empty:
        return None

    gross_r = None
    exit_reason = "TIME"
    exit_time = after.iloc[-1]["time_utc"]
    mfe_r = 0.0
    mae_r = 0.0

    for _, row in after.iterrows():
        hi = float(row["high"])
        lo = float(row["low"])
        if direction > 0:
            mfe_r = max(mfe_r, (hi - entry) / stop_dist)
            mae_r = min(mae_r, (lo - entry) / stop_dist)
            stop_hit = lo <= stop
            target_hit = hi >= target
        else:
            mfe_r = max(mfe_r, (entry - lo) / stop_dist)
            mae_r = min(mae_r, (entry - hi) / stop_dist)
            stop_hit = hi >= stop
            target_hit = lo <= target

        if stop_hit:
            gross_r = -1.0
            exit_reason = "STOP"
            exit_time = row["time_utc"]
            break
        if target_hit:
            gross_r = base.TARGET_R
            exit_reason = "TARGET"
            exit_time = row["time_utc"]
            break

    if gross_r is None:
        exit_px = float(after.iloc[-1]["close"])
        gross_r = direction * (exit_px - entry) / stop_dist

    cost_r = base.BASE_COST_PIPS * base.pip_size(pair) / stop_dist
    return {
        "pair": pair,
        "strategy": CONTRACT,
        "session_date": str(day.iloc[0]["local_date"]),
        "signal_time": day.loc[trigger_idx, "time_utc"],
        "entry_time": day.loc[entry_idx, "time_utc"],
        "exit_time": exit_time,
        "direction": direction,
        "asia_high": asia_high,
        "asia_low": asia_low,
        "asia_range_pips": (asia_high - asia_low) / base.pip_size(pair),
        "atr_pips": float(signal_atr) / base.pip_size(pair),
        "gross_r": gross_r,
        "cost_r": cost_r,
        "net_r": gross_r - cost_r,
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "exit_reason": exit_reason,
    }


def main() -> None:
    base.CONTRACT = CONTRACT
    base.simulate_day = simulate_day_fixed
    base.main()


if __name__ == "__main__":
    main()
