"""RIZAN XAU R5 — causal regime-adaptive trend continuation research.

All features are computed on fully CLOSED M5 candles. M15/H1 context uses
backward-asof joins from complete aggregates (R3 feature engine). The regime
labels are deterministic; there is no claimed or calibrated probability.
No broker/bridge/order/network calls, no LIVE authority.
"""
from __future__ import annotations

from math import isfinite

import numpy as np
import pandas as pd

from .xau_microalpha_r3 import build_features
from .xau_microalpha_r4 import WIB

CONTRACT = "RIZAN_XAU_R5_REGIME_TREND_RESEARCH_ONLY"
EXECUTION_AUTHORITY = False
CANDIDATES = (
    "BREAKOUT_12_H1_M15",
    "BREAKOUT_24_M15",
    "TREND_PULLBACK_M5",
    "COMPRESSION_EXPANSION",
    "ASIA_OPEN_BREAKOUT",
    "H1_TREND_M5_MICROBREAK",
)


def features(raw: pd.DataFrame) -> pd.DataFrame:
    """Causal engineered OHLC and multi-timeframe context, no current H1 leakage."""
    f = build_features(raw)
    utc = f["datetime"]
    close = f["close"]
    atr = f["m5_atr14"]
    # Snapshot current decision is after this M5 candle closes.
    f["wib_hour"] = utc.dt.tz_convert(WIB).dt.hour
    f["wib_date"] = utc.dt.tz_convert(WIB).dt.date
    f["daily_entry_window"] = f["wib_hour"].between(8, 12)
    for n in (6, 12, 24):
        enough = utc.diff(n).eq(pd.Timedelta(minutes=5 * n))
        f[f"high_prev_{n}"] = f["high"].rolling(n, min_periods=n).max().shift(1).where(enough)
        f[f"low_prev_{n}"] = f["low"].rolling(n, min_periods=n).min().shift(1).where(enough)
    # Ratio is conditioned on PAST atr median only. No future volatility leakage.
    f["atr_median_prev96"] = atr.rolling(96, min_periods=96).median().shift(1)
    f["atr_relative"] = atr.div(f["atr_median_prev96"])
    # 06:00–07:55 WIB opening range must contain 24 nonmissing M5 observations.
    opening = f.loc[f["wib_hour"].between(6, 7), [
        "wib_date", "high", "low", "datetime"
    ]]
    session = opening.groupby("wib_date").agg(
        asia_high=("high", "max"),
        asia_low=("low", "min"),
        count=("low", "count"),
        first_at=("datetime", "min"),
        last_at=("datetime", "max"),
    )
    complete = session["count"].eq(24) & (
        session["last_at"] - session["first_at"] == pd.Timedelta(minutes=115)
    )
    session["asia_high"] = session["asia_high"].where(complete)
    session["asia_low"] = session["asia_low"].where(complete)
    f = f.join(session[["asia_high", "asia_low"]], on="wib_date")
    # H1-only regime backed by EMA50 vs EMA200, M15 context independent.
    f["h1_up"] = f["h1_ema50"].gt(f["h1_ema200"]) & close.gt(f["h1_ema50"])
    f["h1_down"] = f["h1_ema50"].lt(f["h1_ema200"]) & close.lt(f["h1_ema50"])
    f["m15_up"] = f["m15_ema20"].gt(f["m15_ema50"]) & f["m15_rsi14"].ge(52)
    f["m15_down"] = f["m15_ema20"].lt(f["m15_ema50"]) & f["m15_rsi14"].le(48)
    f["regime"] = "MIXED"
    f.loc[f["h1_up"] & f["m15_up"], "regime"] = "TREND_UP"
    f.loc[f["h1_down"] & f["m15_down"], "regime"] = "TREND_DOWN"
    f["momentum_buy"] = f["m5_rsi14"].ge(55) & close.gt(f["open"])
    f["momentum_sell"] = f["m5_rsi14"].le(45) & close.lt(f["open"])
    f["volatility_ok"] = f["atr_relative"].between(.60, 2.0)
    return f


def build_signals(data: pd.DataFrame, *, candidate: str) -> pd.DataFrame:
    """Generate closed-bar signal and a structural SL, NEVER an order request."""
    if candidate not in CANDIDATES:
        raise ValueError("UNRECOGNIZED_R5_HYPOTHESIS")
    f = data.copy()
    p = f["close"]
    prev = p.shift(1)
    hi6, lo6 = f["high_prev_6"], f["low_prev_6"]
    hi12, lo12 = f["high_prev_12"], f["low_prev_12"]
    hi24, lo24 = f["high_prev_24"], f["low_prev_24"]
    m5ema = f["m5_ema20"]
    atr = f["m5_atr14"]
    m = f["daily_entry_window"] & f["volatility_ok"] & f["h1_ema200"].notna()
    up = f["h1_up"] & f["m15_up"]
    dn = f["h1_down"] & f["m15_down"]
    # Confirmation on the current CLOSED bar, execution in next M5 open.
    if candidate == "BREAKOUT_12_H1_M15":
        buy = m & up & f["momentum_buy"] & p.gt(hi12) & prev.le(hi12.shift(1))
        sell = m & dn & f["momentum_sell"] & p.lt(lo12) & prev.ge(lo12.shift(1))
        stop_buy, stop_sell = lo6 - .10 * atr, hi6 + .10 * atr
    elif candidate == "BREAKOUT_24_M15":
        # M15 direction and H1 *price* backdrop; h1 fast/slow not required.
        buy = m & f["m15_up"] & p.gt(f["h1_ema200"]) & f["momentum_buy"] & p.gt(hi24)
        sell = m & f["m15_down"] & p.lt(f["h1_ema200"]) & f["momentum_sell"] & p.lt(lo24)
        stop_buy, stop_sell = lo6 - .10 * atr, hi6 + .10 * atr
    elif candidate == "TREND_PULLBACK_M5":
        # EMA20 reclaim/recross in aligned trend; anchor SL beyond 6-candle swing.
        buy = m & up & f["momentum_buy"] & prev.le(m5ema.shift(1)) & p.gt(m5ema)
        sell = m & dn & f["momentum_sell"] & prev.ge(m5ema.shift(1)) & p.lt(m5ema)
        stop_buy, stop_sell = lo6 - .10 * atr, hi6 + .10 * atr
    elif candidate == "COMPRESSION_EXPANSION":
        prior_quiet = atr.shift(1).lt(f["atr_median_prev96"].shift(1) * .80)
        expansion = (p - f["open"]).abs().gt(.60 * atr)
        buy = m & up & f["momentum_buy"] & prior_quiet & expansion & p.gt(hi12)
        sell = m & dn & f["momentum_sell"] & prior_quiet & expansion & p.lt(lo12)
        stop_buy, stop_sell = lo6 - .10 * atr, hi6 + .10 * atr
    elif candidate == "ASIA_OPEN_BREAKOUT":
        buy = m & up & f["momentum_buy"] & p.gt(f["asia_high"]) & prev.le(f["asia_high"])
        sell = m & dn & f["momentum_sell"] & p.lt(f["asia_low"]) & prev.ge(f["asia_low"])
        stop_buy, stop_sell = lo6 - .10 * atr, hi6 + .10 * atr
    else:  # H1_TREND_M5_MICROBREAK, larger sample without M15 hard gate.
        buy = m & f["h1_up"] & f["momentum_buy"] & p.gt(hi6) & prev.le(hi6.shift(1))
        sell = m & f["h1_down"] & f["momentum_sell"] & p.lt(lo6) & prev.ge(lo6.shift(1))
        stop_buy, stop_sell = lo6 - .10 * atr, hi6 + .10 * atr
    ambiguous = buy & sell
    buy = buy & ~ambiguous
    sell = sell & ~ambiguous
    # Must be a real STRUCTURAL stop outside current closed price.
    valid_buy = buy & stop_buy.lt(p) & stop_buy.gt(0)
    valid_sell = sell & stop_sell.gt(p)
    f["r4_signal"] = np.select([valid_buy, valid_sell], [1, -1], default=0).astype(np.int8)
    f["r4_structural_stop"] = np.where(valid_buy, stop_buy, np.where(valid_sell, stop_sell, np.nan))
    f["r5_candidate"] = candidate
    return f


def live_shadow_state(
    technical: pd.DataFrame, macro: dict, *, now: pd.Timestamp,
    account_usd: float = 100.0, risk_fraction: float = .05,
    min_lot: float = .01, contract_oz: float = 100.0,
    frict_usd_per_oz: float = .8, leverage: float = 200.,
    margin_limit: float = .50,
) -> dict:
    """Never grants execution; unknown macro and stale candles force WAIT."""
    latest = technical.iloc[-1]
    at = latest["closed_at"]
    age = (now - at).total_seconds()
    side = {1: "BUY", -1: "SELL", 0: "WAIT"}[int(latest["r4_signal"])]
    min_units = contract_oz * min_lot
    stop = latest["r4_structural_stop"]
    price = float(latest["close"])
    estimated_risk = (
        min_units * (abs(price - float(stop)) + frict_usd_per_oz)
        if isfinite(float(stop)) else None
    )
    nominal_margin = min_units * price / leverage
    state = "WAIT"
    if not 0 <= age <= 600:
        state = "WAIT_STALE_PRICE"
    elif side == "WAIT":
        state = "WAIT_TECHNICAL"
    elif estimated_risk is None or estimated_risk > account_usd * risk_fraction:
        state = "BLOCKED_BY_RISK"
    elif nominal_margin > account_usd * margin_limit:
        state = "BLOCKED_BY_MARGIN"
    elif macro.get("state") != "MACRO_ALIGNED_CONTEXT":
        state = "WAIT_MACRO"
    elif macro.get("direction") != side:
        state = "WAIT_MACRO_OPPOSED"
    else:
        state = "SHADOW_CONCORDANCE_ONLY"
    return {
        "contract": CONTRACT, "technical": side,
        "macro": macro.get("direction", "WAIT"), "state": state,
        "price_asof_utc": at.isoformat(), "age_seconds": round(age, 1),
        "reference_structural_stop": float(stop) if isfinite(float(stop)) else None,
        "min_size_risk_usd": round(estimated_risk, 2) if estimated_risk is not None else None,
        "nominal_min_margin_usd": round(nominal_margin, 2),
        "regime": str(latest["regime"]),
        "execution_authority": False, "execution_influence": False,
        "macro_accuracies_calibrated": False,
    }
