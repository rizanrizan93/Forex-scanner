"""RIZAN XAU Alpha R2: read-only H1 indicator and conservative $100 research sizing.

This module has no order, credential, bridge or broker imports.
Research evidence is NOT a live trading permission.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import floor, isfinite

import pandas as pd

VERSION = "RIZAN_XAU_ALPHA_R2_RESEARCH_ONLY"
EXECUTION_AUTHORITY = False


@dataclass(frozen=True)
class ResearchSettings:
    initial_equity: float = 100.0
    leverage: float = 200.0
    contract_oz_per_lot: float = 100.0
    min_lot: float = 0.01
    lot_step: float = 0.01
    risk_fraction: float = 0.05
    max_margin_fraction: float = 0.50
    stop_atr: float = 2.0
    reward_r: float = 2.0
    friction_usd_per_oz_roundtrip: float = 0.80
    max_hold_h1_bars: int = 24
    stopout_margin_level: float = 0.50


def indicators(raw: pd.DataFrame) -> pd.DataFrame:
    """Only completed UTC H1 candles belong in raw. No live candle is inferred."""
    frame = raw.copy()
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    key = next((x for x in ("datetime", "timestamp", "time", "date") if x in frame), None)
    if key is None or any(c not in frame for c in ("open", "high", "low", "close")):
        raise ValueError("REQUIRES_UTC_H1_DATETIME_OHLC")
    frame["datetime"] = pd.to_datetime(frame[key], utc=True, errors="coerce")
    for c in ("open", "high", "low", "close"):
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
    if frame[["datetime", "open", "high", "low", "close"]].isna().any().any():
        raise ValueError("MISSING_OR_INVALID_H1_DATA")
    if (frame["low"] > frame[["open", "close"]].min(axis=1)).any() or (
        frame["high"] < frame[["open", "close"]].max(axis=1)
    ).any() or (frame["low"] > frame["high"]).any() or (frame["low"] <= 0).any():
        raise ValueError("IMPOSSIBLE_H1_OHLC")
    if frame["datetime"].duplicated().any() or not frame["datetime"].is_monotonic_increasing:
        raise ValueError("H1_TIME_NOT_STRICTLY_INCREASING")
    if len(frame) < 225:
        raise ValueError("NEED_AT_LEAST_225_CLOSED_H1_BARS")

    previous_close = frame["close"].shift(1)
    true_range = pd.concat([
        frame["high"] - frame["low"],
        (frame["high"] - previous_close).abs(),
        (frame["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    frame["atr14"] = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    frame["ema200"] = frame["close"].ewm(span=200, adjust=False, min_periods=200).mean()
    delta = frame["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0, float("nan"))
    frame["rsi14"] = (100 - 100 / (1 + rs)).fillna(50)
    frame["channel_high20"] = frame["high"].rolling(20).max().shift(1)
    frame["channel_low20"] = frame["low"].rolling(20).min().shift(1)
    valid = frame["atr14"].gt(0) & frame["ema200"].notna()
    buy = valid & frame["close"].gt(frame["channel_high20"]) & frame["close"].gt(frame["ema200"]) & frame["rsi14"].ge(60)
    sell = valid & frame["close"].lt(frame["channel_low20"]) & frame["close"].lt(frame["ema200"]) & frame["rsi14"].le(40)
    frame["signal"] = 0
    frame.loc[buy, "signal"] = 1
    frame.loc[sell, "signal"] = -1
    return frame.reset_index(drop=True)


def latest_indicator(frame: pd.DataFrame, settings: ResearchSettings, macro_bias: str = "UNKNOWN") -> dict:
    """Technical evidence plus tradability. Macro is descriptive unless verified."""
    x = frame.iloc[-1]
    side = {1: "BUY", -1: "SELL", 0: "WAIT"}[int(x["signal"])]
    stop_distance = settings.stop_atr * float(x["atr14"])
    qty_min = settings.min_lot * settings.contract_oz_per_lot
    estimated_min_risk = qty_min * (stop_distance + settings.friction_usd_per_oz_roundtrip)
    estimated_min_margin = qty_min * float(x["close"]) / settings.leverage
    allowed = (
        side != "WAIT" and estimated_min_risk <= settings.initial_equity * settings.risk_fraction
        and estimated_min_margin <= settings.initial_equity * settings.max_margin_fraction
    )
    return {
        "version": VERSION, "as_of_closed_h1_utc": x["datetime"].isoformat(),
        "direction": side,
        "state": "READY_RESEARCH_ONLY" if allowed else (
            "BLOCKED_BY_RISK" if side != "WAIT" else "WAIT_SIGNAL"),
        "close": round(float(x["close"]), 3),
        "ema200": round(float(x["ema200"]), 3),
        "rsi14": round(float(x["rsi14"]), 2),
        "atr14": round(float(x["atr14"]), 3),
        "channel_high20": round(float(x["channel_high20"]), 3),
        "channel_low20": round(float(x["channel_low20"]), 3),
        "reference_stop_distance": round(stop_distance, 3),
        "minimum_lot_risk_usd": round(estimated_min_risk, 2),
        "minimum_lot_margin_usd": round(estimated_min_margin, 2),
        "macro_bias": str(macro_bias or "UNKNOWN").upper(),
        "macro_validated": False,
        "execution_authority": EXECUTION_AUTHORITY, "execution_influence": False,
    }


def simulate(frame: pd.DataFrame, cfg: ResearchSettings, session: str = "ALL") -> tuple[dict, pd.DataFrame]:
    """Closed H1 signal -> next H1 open. Intrabar SL before TP when ambiguous.

    Market spreads and broker stop-out specifics are not observed. Reported
    floating DD is an OHLC-bar estimate, not tick-by-tick broker equity.
    """
    if session not in ("ALL", "ASIA_08_13", "NY_19_24"):
        raise ValueError("UNKNOWN_SESSION")
    if not (0 < cfg.risk_fraction <= 1 and 0 < cfg.max_margin_fraction <= 1):
        raise ValueError("INVALID_RISK")
    if min(cfg.initial_equity, cfg.leverage, cfg.contract_oz_per_lot, cfg.min_lot, cfg.lot_step,
           cfg.stop_atr, cfg.reward_r, cfg.max_hold_h1_bars) <= 0:
        raise ValueError("INVALID_SETTINGS")
    if cfg.friction_usd_per_oz_roundtrip < 0 or not 0 < cfg.stopout_margin_level < 1:
        raise ValueError("INVALID_COSTS_OR_STOPOUT")

    records = []
    equity = float(cfg.initial_equity)
    peak = equity
    dd = 0.0
    intrabar_dd = 0.0
    blocked_risk = blocked_margin = 0
    half_frict = cfg.friction_usd_per_oz_roundtrip / 2
    unit_step = cfg.contract_oz_per_lot * cfg.lot_step
    unit_min = cfg.contract_oz_per_lot * cfg.min_lot
    rows = frame.reset_index(drop=True)
    i = 201
    while i < len(rows) - cfg.max_hold_h1_bars - 1 and equity > 0:
        candle = rows.iloc[i]
        side = int(candle["signal"])
        if side == 0 or not isfinite(float(candle["atr14"])):
            i += 1
            continue
        nxt = rows.iloc[i + 1]
        if (nxt["datetime"] - candle["datetime"]).total_seconds() > 7200:
            i += 1
            continue
        h_wib = (nxt["datetime"].hour + 7) % 24
        if session == "ASIA_08_13" and not 8 <= h_wib < 13:
            i += 1
            continue
        if session == "NY_19_24" and not 19 <= h_wib < 24:
            i += 1
            continue
        stop_width = cfg.stop_atr * float(candle["atr14"])
        risk_per_oz = stop_width + cfg.friction_usd_per_oz_roundtrip
        desired_steps = floor((equity * cfg.risk_fraction / risk_per_oz + 1e-10) / unit_step)
        units = desired_steps * unit_step
        if units + 1e-9 < unit_min:
            blocked_risk += 1
            i += 1
            continue
        units = min(units, floor((equity * cfg.max_margin_fraction * cfg.leverage /
                                 float(nxt["open"]) + 1e-10) / unit_step) * unit_step)
        if units + 1e-9 < unit_min:
            blocked_margin += 1
            i += 1
            continue

        margin = units * float(nxt["open"]) / cfg.leverage
        entry = float(nxt["open"]) + side * half_frict
        sl = entry - side * stop_width
        tp = entry + side * cfg.reward_r * stop_width
        # Broker-specific stop-out is a hypothetical guard; do not claim parity.
        liquidation = entry - side * max(0.0, equity - units * half_frict -
                                          margin * cfg.stopout_margin_level) / units
        exit_px = None
        exit_index = i + 1
        reason = "TIME"
        floating_low = equity
        for j in range(i + 1, min(i + cfg.max_hold_h1_bars + 1, len(rows))):
            bar = rows.iloc[j]
            o, hi, lo = (float(bar[k]) for k in ("open", "high", "low"))
            # If a gap opens beyond a protective threshold, fill at the open.
            stop_at_open = (side == 1 and o <= sl) or (side == -1 and o >= sl)
            liquid_at_open = ((side == 1 and o <= liquidation) or
                              (side == -1 and o >= liquidation))
            if stop_at_open or liquid_at_open:
                exit_px, exit_index, reason = o, j, ("STOPOUT_GAP" if liquid_at_open else "SL_GAP")
            else:
                sl_hit = (lo <= sl if side == 1 else hi >= sl)
                liquidation_hit = (lo <= liquidation if side == 1 else hi >= liquidation)
                tp_hit = (hi >= tp if side == 1 else lo <= tp)
                liquid_first = liquidation_hit and (
                    (liquidation >= sl) if side == 1 else (liquidation <= sl))
                if liquid_first:
                    exit_px, exit_index, reason = liquidation, j, "STOPOUT"
                elif sl_hit:
                    exit_px, exit_index, reason = sl, j, "SL"
                elif tp_hit:
                    exit_px, exit_index, reason = tp, j, "TP"
            # Clamp worst excursion at the protective exit price if exited here.
            adverse = lo if side == 1 else hi
            if exit_px is not None:
                adverse = max(adverse, exit_px) if side == 1 else min(adverse, exit_px)
            floating_low = min(floating_low, equity + units * side * (adverse - entry) - units * half_frict)
            intrabar_dd = max(intrabar_dd, (peak - floating_low) / peak)
            if exit_px is not None:
                break
            if j == i + cfg.max_hold_h1_bars:
                exit_px, exit_index, reason = float(bar["close"]), j, "TIME"
                break
        if exit_px is None:
            i += 1
            continue
        pnl = units * (side * (exit_px - entry) - half_frict)
        equity = max(0.0, equity + pnl)
        peak = max(peak, equity)
        dd = max(dd, (peak - equity) / peak)
        records.append({
            "entry_utc": nxt["datetime"], "side": "BUY" if side == 1 else "SELL",
            "ounces": units, "lots": units / cfg.contract_oz_per_lot,
            "risk_usd": units * risk_per_oz, "margin_usd": margin,
            "exit_reason": reason, "pnl_usd": pnl, "equity_usd": equity,
        })
        i = exit_index + 1

    trades = pd.DataFrame.from_records(records)
    wins = float(trades.loc[trades["pnl_usd"] > 0, "pnl_usd"].sum()) if not trades.empty else 0.0
    losses = float(-trades.loc[trades["pnl_usd"] < 0, "pnl_usd"].sum()) if not trades.empty else 0.0
    return {
        "initial_usd": cfg.initial_equity, "final_usd": round(equity, 2),
        "net_return_pct": round((equity / cfg.initial_equity - 1) * 100, 2),
        "trades": len(records), "profit_factor": round(wins / losses, 3) if losses else None,
        "closed_trade_dd_pct": round(dd * 100, 2),
        "intrabar_dd_estimate_pct": round(intrabar_dd * 100, 2),
        "blocked_by_risk": blocked_risk, "blocked_by_margin": blocked_margin,
        "basis": "OHLC_H1_RESEARCH_ONLY", "broker_margin_verified": False,
        "tick_bid_ask_verified": False, "execution_authority": EXECUTION_AUTHORITY,
    }, trades
