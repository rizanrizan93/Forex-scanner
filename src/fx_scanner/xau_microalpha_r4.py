"""RIZAN MicroAlpha R4 research — objective liquidity sweep, confirm, structural stop.

READ-ONLY, no brokerage/order/bridge/network. Built around 5-minute completed
candles and the M15/H1 backward-asof indicators in xau_microalpha_r3.
The nominal margin model and costs are assumptions until verified on FP cTrader.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import floor, isfinite
from typing import Any

import numpy as np
import pandas as pd

from .xau_microalpha_r3 import build_features as r3_build_features

CONTRACT = "RIZAN_XAU_MICROALPHA_R4_LIQUIDITY_RESEARCH_ONLY"
EXECUTION_AUTHORITY = False
WIB = "Asia/Jakarta"


@dataclass(frozen=True)
class R4Settings:
    initial_usd: float = 100.0
    leverage: float = 200.0
    contract_oz_per_lot: float = 100.0
    min_lot: float = .01
    lot_step: float = .01
    max_lot: float = .50
    risk_fraction: float = .05
    max_margin_fraction: float = .50
    roundtrip_cost_usd_per_oz: float = .80
    reward_r: float = 2.0
    max_hold_bars: int = 24
    sweep_buffer_atr: float = .08
    stop_buffer_atr: float = .10
    stopout_margin_level: float = .50


def build_liquidity_signals(
    raw: pd.DataFrame, *, pool: str = "ROLL12", trend: str = "NONE",
    confirm_bars: int = 3,
) -> pd.DataFrame:
    """Reclaim previous liquidity then break sweep-candle high/low within N M5 bars.

    Modes pool ROLL12, ROLL24, ASIA_OPEN_06_08 are objectively defined.
    Confirmation only uses a CLOSED M5 price and PREVIOUS sweep observations.
    Trigger can occur only from 08:00 to 13:00 WIB, verified after close.
    """
    if pool not in {"ROLL12", "ROLL24", "ASIA_OPEN_06_08"}:
        raise ValueError("BAD_R4_POOL")
    if trend not in {"NONE", "M15", "H1", "BOTH"}:
        raise ValueError("BAD_R4_TREND")
    if not 1 <= confirm_bars <= 4:
        raise ValueError("BAD_R4_CONFIRM_BARS")

    f = r3_build_features(raw).copy()
    utc = f["datetime"]
    local = utc.dt.tz_convert(WIB)
    local_hour = local.dt.hour
    local_day = local.dt.date
    # Use only fully completed regular 06:00–07:55 WIB opening range,
    # available to a strategy trading AFTER 08:00 WIB.
    if pool == "ASIA_OPEN_06_08":
        opening = f.loc[(local_hour >= 6) & (local_hour < 8)].copy()
        opening["_wib_day"] = local_day.loc[opening.index]
        sessions = opening.groupby("_wib_day", sort=False).agg(
            opening_high=("high", "max"),
            opening_low=("low", "min"),
            opening_count=("close", "size"),
        )
        data = pd.DataFrame({"_wib_day": local_day}).join(sessions, on="_wib_day")
        pool_high = data["opening_high"].where(data["opening_count"] == 24)
        pool_low = data["opening_low"].where(data["opening_count"] == 24)
    else:
        n = 12 if pool == "ROLL12" else 24
        pool_high = f["high"].rolling(n, min_periods=n).max().shift(1)
        pool_low = f["low"].rolling(n, min_periods=n).min().shift(1)
        # Never roll liquidity observations across missing M5 market hours.
        contiguous = utc.diff(n).eq(pd.Timedelta(minutes=5 * n))
        pool_high = pool_high.where(contiguous)
        pool_low = pool_low.where(contiguous)

    atr = f["m5_atr14"]
    ready = atr.notna() & f["h1_ema200"].notna()
    session = local_hour.between(8, 12)
    # Do not allow the sweep to start before the opening range is complete.
    sweep_buy = (
        ready & session
        & f["low"].lt(pool_low - atr * .05)
        & f["close"].gt(pool_low)
        & f["close"].gt(f["open"])
    )
    sweep_sell = (
        ready & session
        & f["high"].gt(pool_high + atr * .05)
        & f["close"].lt(pool_high)
        & f["close"].lt(f["open"])
    )

    # For reference risk the high/low of the actual swept candle is fixed.
    signal = np.zeros(len(f), dtype="int8")
    stop = np.full(len(f), np.nan, dtype="float64")
    reference = np.full(len(f), -1, dtype="int16")
    m15_bull = f["m15_ema20"].gt(f["m15_ema50"])
    m15_bear = f["m15_ema20"].lt(f["m15_ema50"])
    h1_bull = f["close"].gt(f["h1_ema50"])
    h1_bear = f["close"].lt(f["h1_ema50"])

    for k in range(1, confirm_bars + 1):
        contiguous = utc.sub(utc.shift(k)).eq(pd.Timedelta(minutes=5 * k))
        # Shifted signals are explicitly at least one fully CLOSED bar old.
        buy = (
            pd.Series(signal, index=f.index).eq(0)
            & contiguous & sweep_buy.shift(k, fill_value=False)
            & f["close"].gt(f["high"].shift(k))
            & f["close"].gt(f["open"])
            & session & ready
        )
        sell = (
            pd.Series(signal, index=f.index).eq(0)
            & contiguous & sweep_sell.shift(k, fill_value=False)
            & f["close"].lt(f["low"].shift(k))
            & f["close"].lt(f["open"])
            & session & ready
        )
        if trend in ("M15", "BOTH"):
            buy &= m15_bull
            sell &= m15_bear
        if trend in ("H1", "BOTH"):
            buy &= h1_bull
            sell &= h1_bear
        # Ambiguous simultaneous confirmation -> no signal.
        buy = buy & ~sell
        sell = sell & ~buy
        b = buy.to_numpy(dtype=bool)
        s = sell.to_numpy(dtype=bool)
        if b.any():
            signal[b] = 1
            stop[b] = (
                f["low"].shift(k) - f["m5_atr14"].shift(k) * .10
            ).to_numpy()[b]
            reference[b] = k
        if s.any():
            signal[s] = -1
            stop[s] = (
                f["high"].shift(k) + f["m5_atr14"].shift(k) * .10
            ).to_numpy()[s]
            reference[s] = k

    f["r4_signal"] = signal
    f["r4_structural_stop"] = stop
    f["r4_confirm_lag_bars"] = reference
    f["r4_pool"] = pool
    f["r4_trend_filter"] = trend
    return f


def apply_lagged_macro_filter(
    signals: pd.DataFrame, macro_h1: pd.DataFrame, *, mode: str,
) -> pd.DataFrame:
    """Research ONLY: historical FRED/H.10 publisher-lagged seven-day proxies.

    These are NOT licensed ICE DXY, nor intraday Treasury real yield readings.
    Time conversion is backward asof with a strict 2-hour maximum staleness.
    """
    if mode not in {"REAL_AND_USD", "REAL_NOMINAL_USD", "OFF"}:
        raise ValueError("BAD_R4_MACRO_MODE")
    if mode == "OFF":
        return signals.copy()
    required = ("macro_DFII10_chg7d", "macro_DGS10_chg7d", "macro_DTWEXBGS_pct7d")
    if "asof" not in macro_h1.columns or any(c not in macro_h1 for c in required):
        raise ValueError("MISSING_HISTORICAL_MACRO_FIELDS")
    h = macro_h1[["asof", *required]].copy()
    h["asof"] = pd.to_datetime(h["asof"], utc=True, errors="raise").astype("datetime64[ns, UTC]")
    if h["asof"].duplicated().any() or not h["asof"].is_monotonic_increasing:
        raise ValueError("MACRO_ASOF_MUST_INCREASE")
    q = pd.merge_asof(
        signals[["closed_at"]].sort_values("closed_at"),
        h, left_on="closed_at", right_on="asof", direction="backward",
        tolerance=pd.Timedelta(hours=2),
    )
    real = pd.to_numeric(q[required[0]], errors="coerce")
    nominal = pd.to_numeric(q[required[1]], errors="coerce")
    usd = pd.to_numeric(q[required[2]], errors="coerce")
    buy = real.lt(0) & usd.lt(0)
    sell = real.gt(0) & usd.gt(0)
    if mode == "REAL_NOMINAL_USD":
        buy &= nominal.le(0)
        sell &= nominal.ge(0)
    ret = signals.copy()
    original = ret["r4_signal"]
    good = ((original.eq(1) & buy) | (original.eq(-1) & sell)).fillna(False)
    ret["r4_signal"] = original.where(good, 0)
    ret["r4_structural_stop"] = ret["r4_structural_stop"].where(good)
    return ret


def backtest(
    signals: pd.DataFrame, cfg: R4Settings = R4Settings(), *,
    session: str = "ASIA", window_start: str | None = None,
    window_end: str | None = None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Next M5 OPEN fill with assumed roundtrip friction and structural stop.

    If same candle hits SL and TP, SL wins. Gap opens beyond stop fill at
    observed open. Session ASIA exits on first M5 bar at 13:00 WIB.
    Position is exclusive, no simultaneous orders and no order routing.
    """
    if session not in {"ASIA", "ALL"}:
        raise ValueError("BAD_R4_SESSION")
    if not (0 < cfg.risk_fraction <= .2 and 0 < cfg.max_margin_fraction <= 1
            and 0 < cfg.stopout_margin_level < 1 and cfg.initial_usd > 0
            and cfg.leverage > 0 and cfg.contract_oz_per_lot > 0 and cfg.min_lot > 0
            and cfg.lot_step > 0 and cfg.max_lot >= cfg.min_lot
            and cfg.roundtrip_cost_usd_per_oz >= 0 and cfg.reward_r > 0
            and 1 <= cfg.max_hold_bars <= 288):
        raise ValueError("BAD_R4_SETTINGS")
    rows = signals.reset_index(drop=True)
    t = rows["datetime"].to_numpy(dtype="datetime64[ns]")
    opens = rows["open"].to_numpy(dtype=float)
    highs = rows["high"].to_numpy(dtype=float)
    lows = rows["low"].to_numpy(dtype=float)
    closes = rows["close"].to_numpy(dtype=float)
    sides = rows["r4_signal"].to_numpy(dtype=np.int8)
    sls = rows["r4_structural_stop"].to_numpy(dtype=float)
    wb = rows["datetime"].dt.tz_convert(WIB)
    hour = wb.dt.hour.to_numpy()
    # YYYY-MM-DD local date is used only for human-readable transactions.
    wib_dates = wb.dt.date.astype(str).to_numpy()
    n = len(t)
    lo_cut = np.datetime64(pd.Timestamp(window_start, tz="UTC").to_datetime64()) if window_start else None
    hi_cut = np.datetime64(pd.Timestamp(window_end, tz="UTC").to_datetime64()) if window_end else None

    equity = peak = float(cfg.initial_usd)
    dd, floating_dd = 0.0, 0.0
    records = []
    blocked_risk = blocked_margin = skipped_gap = skipped_unaffordable_stop = 0
    half = cfg.roundtrip_cost_usd_per_oz / 2
    step = cfg.contract_oz_per_lot * cfg.lot_step
    min_units = cfg.min_lot * cfg.contract_oz_per_lot
    max_units = cfg.max_lot * cfg.contract_oz_per_lot

    i = 0
    while i < n - 1 and equity > 0:
        side = int(sides[i])
        if not side or not isfinite(sls[i]):
            i += 1
            continue
        j = i + 1
        if lo_cut is not None and t[j] < lo_cut:
            i += 1
            continue
        if hi_cut is not None and t[j] >= hi_cut:
            break
        if session == "ASIA" and not 8 <= hour[j] < 13:
            i += 1
            continue
        if t[j] - t[i] != np.timedelta64(5, "m"):
            skipped_gap += 1
            i += 1
            continue
        entry = opens[j] + side * half
        stop = float(sls[i])
        stop_width = side * (entry - stop)
        if not 0 < stop_width < entry * .05:
            skipped_unaffordable_stop += 1
            i += 1
            continue
        risk_per_unit = stop_width + half
        desired = floor((equity * cfg.risk_fraction / risk_per_unit + 1e-10) / step) * step
        if desired + 1e-9 < min_units:
            blocked_risk += 1
            i += 1
            continue
        permitted_margin = floor(
            (equity * cfg.max_margin_fraction * cfg.leverage / opens[j] + 1e-10) / step
        ) * step
        units = min(desired, permitted_margin, max_units)
        if units + 1e-9 < min_units:
            blocked_margin += 1
            i += 1
            continue
        margin = units * opens[j] / cfg.leverage
        target = entry + side * cfg.reward_r * stop_width
        liquid = entry - side * max(0.0, equity - units * half
                                     - cfg.stopout_margin_level * margin) / units
        exit_index, exit_px, why = -1, None, "NO_FILL"
        for k in range(j, min(n, j + cfg.max_hold_bars)):
            # Asian positions are flat at first 13:00 WIB opening.
            if session == "ASIA" and hour[k] >= 13:
                exit_index, exit_px, why = k, opens[k], "ASIA_CUTOFF"
                break
            if k > j and t[k] - t[k - 1] != np.timedelta64(5, "m"):
                exit_index, exit_px, why = k, opens[k], "MARKET_GAP"
                break
            op, hi, low = opens[k], highs[k], lows[k]
            gap_sl = (op <= stop) if side > 0 else (op >= stop)
            gap_liquid = (op <= liquid) if side > 0 else (op >= liquid)
            hit_sl = (low <= stop) if side > 0 else (hi >= stop)
            hit_liquid = (low <= liquid) if side > 0 else (hi >= liquid)
            hit_tp = (hi >= target) if side > 0 else (low <= target)
            liquid_first = hit_liquid and ((liquid >= stop) if side > 0 else (liquid <= stop))
            if gap_sl or gap_liquid:
                exit_index, exit_px, why = k, op, "STOP_GAP"
            elif liquid_first:
                exit_index, exit_px, why = k, liquid, "STOPOUT"
            elif hit_sl:
                exit_index, exit_px, why = k, stop, "STOP"
            elif hit_tp:
                exit_index, exit_px, why = k, target, "TARGET"
            elif k == min(n, j + cfg.max_hold_bars) - 1:
                exit_index, exit_px, why = k, closes[k], "TIME"
            adverse = low if side > 0 else hi
            if exit_px is not None:
                adverse = max(adverse, exit_px) if side > 0 else min(adverse, exit_px)
            unrealized = equity + units * (side * (adverse - entry) - half)
            floating_dd = max(floating_dd, (peak - max(0.0, unrealized)) / peak)
            if exit_px is not None:
                break
        if exit_px is None:
            skipped_gap += 1
            i += 1
            continue
        pnl = units * (side * (exit_px - entry) - half)
        equity = max(0.0, equity + pnl)
        dd = max(dd, (peak - equity) / peak)
        peak = max(peak, equity)
        records.append({
            "entry_wib_date": wib_dates[j],
            "entry_utc": str(rows.iloc[j]["datetime"]),
            "side": "BUY" if side > 0 else "SELL",
            "lots": units / cfg.contract_oz_per_lot,
            "stop_width": stop_width, "target_width": cfg.reward_r * stop_width,
            "risk_usd": units * risk_per_unit, "margin_usd": margin,
            "exit_reason": why, "pnl_usd": pnl, "equity_usd": equity,
        })
        i = exit_index + 1

    trades = pd.DataFrame.from_records(records)
    pos = sum(max(0.0, x["pnl_usd"]) for x in records)
    neg = sum(max(0.0, -x["pnl_usd"]) for x in records)
    return {
        "contract": CONTRACT, "start_usd": cfg.initial_usd,
        "ending_usd": round(equity, 2),
        "net_pct": round(100 * (equity / cfg.initial_usd - 1), 2),
        "count": len(records),
        "win_rate_pct": round(100 * sum(x["pnl_usd"] > 0 for x in records) / len(records), 2) if records else None,
        "profit_factor": round(pos / neg, 3) if neg else None,
        "mean_r": round(sum(x["pnl_usd"] / x["risk_usd"] for x in records) / len(records), 4) if records else None,
        "closed_dd_pct": round(dd * 100, 2),
        "ohlc_floating_dd_estimate_pct": round(floating_dd * 100, 2),
        "blocked_risk": blocked_risk, "blocked_margin": blocked_margin,
        "skipped_gaps": skipped_gap,
        "invalid_stop": skipped_unaffordable_stop,
        "basis": "PUBLIC_M5_MID_OHLC_NOT_TICK_OR_FP_MARKETS",
        "trading_authority": False, "macro_backtested": False,
    }, trades
