"""RIZAN MicroAlpha R3: M5 precision entry with closed M15/H1 and read-only macro.

No broker, execution, order or write-capable data access. This engine must not
authorize LIVE orders. Out-of-sample and tick/bid-ask profitability unverified.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import floor, isfinite
from typing import Any, Mapping

import pandas as pd

CONTRACT = "RIZAN_XAU_MICROALPHA_R3_RESEARCH_ONLY"
M5_INTERVAL = timedelta(minutes=5)
MACRO_MAX_AGE_S = 900
EXECUTION_AUTHORITY = False


@dataclass(frozen=True)
class MicroSettings:
    initial_equity: float = 100.0
    leverage: float = 200.0
    lot_size_oz: float = 100.0
    minimum_lot: float = 0.01
    lot_step: float = 0.01
    maximum_lot: float = 0.50  # research capacity cap, adjustable after broker check
    risk_fraction: float = 0.05
    margin_fraction: float = 0.50
    stop_atr: float = 1.0
    take_profit_r: float = 2.0
    friction_roundtrip_usd_per_oz: float = 0.80
    hold_bars: int = 24
    stopout_margin_level: float = 0.50


def _ema(values: pd.Series, period: int) -> pd.Series:
    return values.ewm(span=period, adjust=False, min_periods=period).mean()


def _rsi(values: pd.Series, period: int = 14) -> pd.Series:
    delta = values.diff()
    gains = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    losses = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rsi = 100 - 100 / (1 + gains / losses.where(losses != 0))
    return rsi.mask((losses == 0) & (gains > 0), 100).mask((gains == 0) & (losses > 0), 0)


def _atr(frame: pd.DataFrame) -> pd.Series:
    prev = frame["close"].shift(1)
    tr = pd.concat([frame["high"] - frame["low"], (frame["high"] - prev).abs(),
                    (frame["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()


def _completed_aggregate(m5: pd.DataFrame, frequency: str, bars_expected: int) -> pd.DataFrame:
    """Only complete, uninterrupted M5 blocks form higher-timeframe candles."""
    base = m5.set_index("datetime")
    g = base.resample(frequency, label="left", closed="left")
    out = g.agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    count = g["close"].count()
    # A group with 3/12 valid M5 records is consecutive because input is
    # unique, aligned to 5-minute grid and resampled on exact UTC boundaries.
    out = out.loc[count == bars_expected].copy()
    out["closed_at"] = out.index + pd.Timedelta(frequency)
    return out.reset_index(drop=True)


def build_features(raw: pd.DataFrame) -> pd.DataFrame:
    rows = raw.copy()
    rows.columns = [str(x).strip().lower() for x in rows.columns]
    key = next((k for k in ("datetime", "timestamp", "time") if k in rows.columns), None)
    if key is None or not {"open", "high", "low", "close"}.issubset(rows.columns):
        raise ValueError("REQUIRES_M5_UTC_DATETIME_OHLC")
    rows["datetime"] = pd.to_datetime(rows[key], utc=True, errors="coerce")
    for c in ("open", "high", "low", "close"):
        rows[c] = pd.to_numeric(rows[c], errors="coerce")
    if rows[["datetime", "open", "high", "low", "close"]].isna().any().any():
        raise ValueError("M5_MISSING_OR_INVALID_DATA")
    if (rows["low"] > rows[["open", "close"]].min(axis=1)).any() or (
        rows["high"] < rows[["open", "close"]].max(axis=1)
    ).any() or (rows["low"] <= 0).any() or (rows["high"] < rows["low"]).any():
        raise ValueError("M5_IMPOSSIBLE_OHLC")
    if (rows["datetime"].duplicated().any()
            or not rows["datetime"].is_monotonic_increasing
            or (rows["datetime"].dt.minute % 5).any()
            or rows["datetime"].dt.second.ne(0).any()
            or rows["datetime"].diff().dropna().lt(pd.Timedelta(minutes=5)).any()):
        raise ValueError("M5_CADENCE_INVALID")
    if len(rows) < 2600:
        raise ValueError("M5_MINIMUM_2600_CLOSED_BARS")
    rows = rows[["datetime", "open", "high", "low", "close"]].reset_index(drop=True)
    rows["closed_at"] = rows["datetime"] + pd.Timedelta(minutes=5)
    rows["m5_ema20"] = _ema(rows["close"], 20)
    rows["m5_atr14"] = _atr(rows)
    rows["m5_rsi14"] = _rsi(rows["close"])
    m15 = _completed_aggregate(rows, "15min", 3)
    h1 = _completed_aggregate(rows, "1h", 12)
    if len(m15) < 100 or len(h1) < 205:
        raise ValueError("NOT_ENOUGH_COMPLETE_H1_M15_DATA")
    m15["m15_ema20"] = _ema(m15["close"], 20)
    m15["m15_ema50"] = _ema(m15["close"], 50)
    m15["m15_rsi14"] = _rsi(m15["close"])
    h1["h1_ema50"] = _ema(h1["close"], 50)
    h1["h1_ema200"] = _ema(h1["close"], 200)
    m15 = m15[["closed_at", "m15_ema20", "m15_ema50", "m15_rsi14"]]
    h1 = h1[["closed_at", "h1_ema50", "h1_ema200"]]
    # merge_asof backward at M5 candle close: no current unclosed H1/M15 leakage.
    rows = pd.merge_asof(rows.sort_values("closed_at"), m15.sort_values("closed_at"),
                         on="closed_at", direction="backward")
    rows = pd.merge_asof(rows.sort_values("closed_at"), h1.sort_values("closed_at"),
                         on="closed_at", direction="backward")
    old_ema = rows["m5_ema20"].shift(1)
    previous_close = rows["close"].shift(1)
    # Match pilot eligibility: only act after 200 COMPLETED H1 candles.
    ready_h1 = rows["h1_ema200"].notna()
    bullish = (
        ready_h1
        & rows["m15_ema20"].gt(rows["m15_ema50"])
        & rows["close"].gt(rows["h1_ema50"])
        & previous_close.lt(old_ema)
        & rows["close"].gt(rows["m5_ema20"])
    )
    bearish = (
        ready_h1
        & rows["m15_ema20"].lt(rows["m15_ema50"])
        & rows["close"].lt(rows["h1_ema50"])
        & previous_close.gt(old_ema)
        & rows["close"].lt(rows["m5_ema20"])
    )
    rows["signal"] = 0
    rows.loc[bullish, "signal"] = 1
    rows.loc[bearish, "signal"] = -1
    return rows


def macro_direction(snapshot: Mapping[str, Any] | None, *, now: datetime) -> dict[str, Any]:
    """Use scanner's quality-validated V400 rather than a raw score or stale FRED."""
    result = {
        "direction": "WAIT", "state": "WAIT_MACRO_DATA", "reason": "MACRO_UNAVAILABLE",
        "source": "FOREXSCANNER_V400", "execution_authority": False,
        "execution_influence": False, "calibrated_probability": None,
    }
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    if not snapshot:
        return result
    try:
        from .dashboard_independent_feeds import macro_input
        evaluated = macro_input(dict(snapshot), now=now)
        e = evaluated["evaluation"]
        q = dict(e.get("attribution_quality") or {})
        quality_state = str(q.get("quality_state") or "")
        if quality_state != "ALIGNED_CONTEXT_ONLY":
            return {**result, "state": "WAIT_MACRO_QUALITY",
                    "reason": quality_state or "V400_QUALITY_MISSING"}
        bias = str(q.get("quality_screened_bias") or "")
        if bias not in ("BULLISH_XAU", "BEARISH_XAU"):
            return {**result, "state": "WAIT_MACRO_DIRECTION",
                    "reason": "NO_DIRECTIONAL_V400_CONSENSUS"}
        if not q.get("intraday_confirmation_eligible"):
            return {**result, "state": "WAIT_INTRADAY", "reason": "INTRADAY_NOT_ELIGIBLE"}
        confirmed = dict(e.get("intraday_macro_confirmation") or {})
        components = dict(confirmed.get("components") or {})
        fresh = []
        for name in ("DXY", "US10Y_INTRADAY", "FED_FUNDS_FUTURES"):
            row = dict(components.get(name) or {})
            at = pd.to_datetime(row.get("current_at"), utc=True, errors="coerce")
            age = ((now - at.to_pydatetime()).total_seconds()
                   if not pd.isna(at) else None)
            implication = str(row.get("gold_implication") or "").upper()
            if (row.get("available") is True and age is not None
                    and 0 <= age <= MACRO_MAX_AGE_S
                    and implication in {"GOLD_SUPPORT", "GOLD_SUPPORT_CONFIRMED",
                                        "GOLD_HEADWIND", "GOLD_HEADWIND_CONFIRMED"}):
                fresh.append(name)
        if "DXY" not in fresh or not ({"US10Y_INTRADAY", "FED_FUNDS_FUTURES"} & set(fresh)):
            return {**result, "state": "WAIT_INTRADAY", "reason": "DXY_AND_RATE_NOT_FRESH"}
        return {
            **result, "direction": "BUY" if bias == "BULLISH_XAU" else "SELL",
            "state": "MACRO_ALIGNED_CONTEXT", "reason": "DAILY_AND_INTRADAY_ALIGNED",
            "original_observed_at": evaluated["observed_at"],
            "independent_families": q.get("independent_families"),
            "fresh_intraday_families": fresh,
        }
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        return {**result, "reason": type(exc).__name__, "state": "WAIT_MACRO_DATA"}


def latest_research_state(
    frame: pd.DataFrame, cfg: MicroSettings,
    *, macro: Mapping[str, Any], now: datetime,
) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    last = frame.iloc[-1]
    signal = int(last["signal"])
    technical = "BUY" if signal > 0 else "SELL" if signal < 0 else "WAIT"
    age = (now.astimezone(UTC) - last["closed_at"].to_pydatetime()).total_seconds()
    width = cfg.stop_atr * float(last["m5_atr14"])
    min_oz = cfg.minimum_lot * cfg.lot_size_oz
    risk_min = min_oz * (width + cfg.friction_roundtrip_usd_per_oz)
    margin_min = min_oz * float(last["close"]) / cfg.leverage
    fresh = 0 <= age <= 600
    if not fresh:
        state = "WAIT_STALE_M5"
    elif technical == "WAIT":
        state = "WAIT_TECHNICAL"
    elif risk_min > cfg.initial_equity * cfg.risk_fraction:
        state = "BLOCKED_BY_RISK"
    elif margin_min > cfg.initial_equity * cfg.margin_fraction:
        state = "BLOCKED_BY_MARGIN"
    elif macro.get("state") != "MACRO_ALIGNED_CONTEXT":
        state = "WAIT_MACRO"
    elif macro.get("direction") != technical:
        state = "WAIT_DIRECTION_CONFLICT"
    else:
        state = "SHADOW_ALIGNED_NOT_EXECUTABLE"
    return {
        "contract": CONTRACT, "signal": technical, "state": state,
        "m5_closed_at": last["closed_at"].isoformat(),
        "m5_data_age_seconds": round(age, 1),
        "source_price": float(last["close"]), "ema20": float(last["m5_ema20"]),
        "atr14": float(last["m5_atr14"]),
        "m15_ema20": float(last["m15_ema20"]),
        "m15_ema50": float(last["m15_ema50"]),
        "h1_ema50": float(last["h1_ema50"]),
        "risk_min_usd": round(risk_min, 3),
        "margin_min_usd": round(margin_min, 3),
        "macro_direction": macro.get("direction", "WAIT"),
        "macro_state": macro.get("state", "WAIT_MACRO"),
        "execution_authority": False, "execution_influence": False,
    }


def replay(frame: pd.DataFrame, cfg: MicroSettings, *, session: str = "ASIA") -> tuple[dict, pd.DataFrame]:
    """Pure technical replay, NEVER use current macro snapshot on historical bars."""
    if session not in ("ASIA", "ALL", "US"):
        raise ValueError("SESSION_INVALID")
    if not (0 < cfg.risk_fraction <= 0.2 and
            0 < cfg.margin_fraction <= 1 and 0 < cfg.stopout_margin_level < 1 and
            cfg.hold_bars >= 1 and cfg.minimum_lot > 0 and cfg.lot_step > 0 and
            cfg.lot_size_oz > 0 and cfg.maximum_lot >= cfg.minimum_lot and cfg.leverage > 0 and cfg.stop_atr > 0 and
            cfg.take_profit_r > 0 and cfg.initial_equity > 0 and
            cfg.friction_roundtrip_usd_per_oz >= 0):
        raise ValueError("INVALID_R3_SETTINGS")
    rows = frame.reset_index(drop=True)
    equity = peak = float(cfg.initial_equity)
    close_dd = intrabar_dd = 0.0
    blocked_risk = blocked_margin = 0
    cost_per_side = cfg.friction_roundtrip_usd_per_oz / 2
    unit_step = cfg.lot_step * cfg.lot_size_oz
    unit_min = cfg.minimum_lot * cfg.lot_size_oz
    records = []
    i = 0
    while i < len(rows) - cfg.hold_bars - 1 and equity > 0:
        candle = rows.iloc[i]
        side = int(candle["signal"])
        if side == 0 or not isfinite(float(candle["m5_atr14"])):
            i += 1
            continue
        following = rows.iloc[i + 1]
        if following["datetime"] - candle["datetime"] != pd.Timedelta(minutes=5):
            i += 1
            continue
        hour_wib = (following["datetime"].hour + 7) % 24
        if session == "ASIA" and not 8 <= hour_wib < 13:
            i += 1
            continue
        if session == "US" and not 19 <= hour_wib < 24:
            i += 1
            continue
        stop_width = cfg.stop_atr * float(candle["m5_atr14"])
        cost_risk = stop_width + cfg.friction_roundtrip_usd_per_oz
        units = floor((equity * cfg.risk_fraction / cost_risk + 1e-10) / unit_step) * unit_step
        if units + 1e-9 < unit_min:
            blocked_risk += 1
            i += 1
            continue
        units = min(units, floor(
            (equity * cfg.margin_fraction * cfg.leverage / float(following["open"]) + 1e-10)
            / unit_step) * unit_step)
        if units + 1e-9 < unit_min:
            blocked_margin += 1
            i += 1
            continue
        units = min(units, floor((cfg.maximum_lot * cfg.lot_size_oz + 1e-10) / unit_step) * unit_step)
        if units + 1e-9 < unit_min:
            blocked_margin += 1
            i += 1
            continue
        margin = units * float(following["open"]) / cfg.leverage
        entry = float(following["open"]) + side * cost_per_side
        stop = entry - side * stop_width
        target = entry + side * cfg.take_profit_r * stop_width
        liquid = entry - side * max(
            0.0, equity - units * cost_per_side - cfg.stopout_margin_level * margin
        ) / units
        reason = "TIME"
        exit_px = None
        exit_index = i + 1
        for j in range(i + 1, min(len(rows), i + 1 + cfg.hold_bars)):
            bar = rows.iloc[j]
            o, high, low = float(bar["open"]), float(bar["high"]), float(bar["low"])
            adverse = low if side > 0 else high
            gap_stop = o <= stop if side > 0 else o >= stop
            gap_liquid = o <= liquid if side > 0 else o >= liquid
            hit_stop = low <= stop if side > 0 else high >= stop
            hit_liquid = low <= liquid if side > 0 else high >= liquid
            hit_tp = high >= target if side > 0 else low <= target
            liquid_first = hit_liquid and (liquid >= stop if side > 0 else liquid <= stop)
            if gap_stop or gap_liquid:
                exit_px, exit_index, reason = o, j, "STOP_GAP"
            elif liquid_first:
                exit_px, exit_index, reason = liquid, j, "STOPOUT"
            elif hit_stop:
                exit_px, exit_index, reason = stop, j, "SL"
            elif hit_tp:
                exit_px, exit_index, reason = target, j, "TP"
            elif j == min(len(rows), i + cfg.hold_bars) :
                exit_px, exit_index, reason = float(bar["close"]), j, "TIME"
            # If the recording ends at the next market gap, exit at next open
            # rather than assume a nonexistent mid-candle fill.
            if exit_px is None and j + 1 < len(rows):
                next_bar = rows.iloc[j + 1]
                if next_bar["datetime"] - bar["datetime"] > pd.Timedelta(minutes=5):
                    exit_px, exit_index, reason = float(next_bar["open"]), j + 1, "MARKET_GAP"
            limited = (max(adverse, exit_px) if side > 0 else min(adverse, exit_px)) if exit_px is not None else adverse
            path_equity = equity + units * (side * (limited - entry) - cost_per_side)
            intrabar_dd = max(intrabar_dd, (peak - max(0.0, path_equity)) / peak)
            if exit_px is not None:
                break
        if exit_px is None:
            i += 1
            continue
        pnl = units * (side * (exit_px - entry) - cost_per_side)
        equity = max(0.0, equity + pnl)
        close_dd = max(close_dd, (peak - equity) / peak)
        peak = max(peak, equity)
        records.append({
            "entry_at": following["datetime"], "side": "BUY" if side > 0 else "SELL",
            "ounces": units, "lots": units / cfg.lot_size_oz,
            "risk_usd": units * cost_risk, "margin_usd": margin,
            "exit_reason": reason, "pnl_usd": pnl, "equity_usd": equity,
        })
        i = exit_index + 1
    trades = pd.DataFrame.from_records(records)
    profits = trades.loc[trades.pnl_usd > 0, "pnl_usd"].sum() if len(trades) else 0
    losses = -trades.loc[trades.pnl_usd < 0, "pnl_usd"].sum() if len(trades) else 0
    return {
        "contract": CONTRACT, "initial_equity": cfg.initial_equity,
        "ending_equity": round(equity, 2),
        "return_pct": round(100 * (equity / cfg.initial_equity - 1), 2),
        "trades": len(records), "profit_factor": round(profits / losses, 3) if losses else None,
        "win_rate_pct": round(100 * sum(row["pnl_usd"] > 0 for row in records) / len(records), 2) if records else None,
        "expectancy_r": round(sum(row["pnl_usd"] / row["risk_usd"] for row in records) / len(records), 4) if records else None,
        "maximum_lot_assumed": cfg.maximum_lot,
        "closed_dd_pct": round(close_dd * 100, 2),
        "ohlc_intrabar_dd_estimate_pct": round(intrabar_dd * 100, 2),
        "blocked_risk": blocked_risk, "blocked_margin": blocked_margin,
        "scope": "M5_TECHNICAL_ONLY_NOT_MACRO_BACKTEST",
        "bid_ask_tick_validated": False, "broker_min_lot_verified": False,
        "execution_authority": False, "execution_influence": False,
    }, trades
