"""Frozen EURUSD replay + matched shadow filter ablations; no new signal family.

Public BID M1 and declared synthetic Standard spread/slippage, not actual fills.
Virtual outcome EMAs advance even when the shadow filter skips a real trade,
matching the frozen sizing contract. XAU replay needs its historical news/macro
inputs; never silently drops those requirements to produce a comparison.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .cross_asset_lead_lag import sessions
from .eurusd_frozen_dd37 import (
    POLICY,
    POLICY_HASH,
    features,
    layers,
    signal,
    virtual_step,
)


def eurusd_virtual_trades(raw):
    state = {}
    f = features(raw, state)
    cursor = None
    fast = slow = 0.0
    trades = []
    for at, row in f.iterrows():
        if cursor is not None and at <= cursor:
            continue
        candidate = signal(at, row)
        if candidate is None or at not in raw.index:
            continue
        i = raw.index.get_loc(at)
        side, distance = candidate["side"], candidate["distance"]
        entry = (
            float(raw.open.iloc[i])
            + (POLICY.virtual_spread if side == 1 else 0)
            + side * POLICY.virtual_slip
        )
        pending = {
            **candidate,
            "entry": entry,
            "last_at": at.isoformat(),
            "last_close": float(raw.open.iloc[i]),
        }
        mae = mfe = 0.0
        path = []
        for bar_at, bar in raw.iloc[i : i + 500].iterrows():
            result = virtual_step(pending, bar_at, bar)
            # Bound intrabar excursions at the bracket; exact intrabar ordering
            # is unavailable from M1 OHLC. STOP_FIRST is used by virtual_step.
            adverse = (
                side
                * ((bar.low if side == 1 else bar.high + POLICY.virtual_spread) - entry)
                / distance
            )
            favorable = (
                side
                * ((bar.high if side == 1 else bar.low + POLICY.virtual_spread) - entry)
                / distance
            )
            adverse = max(adverse, -1.0)
            favorable = min(favorable, 4.0)
            if result:
                adverse = min(adverse, result[0])
            mae = min(mae, adverse)
            mfe = max(mfe, favorable)
            path.append((bar_at, adverse, favorable))
            if result:
                net_r, exit_time = result
                cursor = pd.Timestamp(exit_time)
                trades.append(
                    {
                        "at": at,
                        "exit_at": cursor,
                        "side": side,
                        "entry": entry,
                        "distance": distance,
                        "r": net_r,
                        "fast": fast,
                        "slow": slow,
                        "mae_r": -mae,
                        "mfe_r": mfe,
                        "holding_minutes": (cursor - at).total_seconds() / 60,
                        "path": path,
                    }
                )
                fast = (2 / 3) * net_r + (1 / 3) * fast
                slow = (2 / 9) * net_r + (7 / 9) * slow
                break
    return trades


def replay_account(
    trades, *, start, end, accept=None, extra_cost=0.0, remove_seed=None
):
    """Paired compounding account; exact frozen EUR child sizing, 1:100 proxy."""
    balance = peak = 100.0
    max_dd = 0.0
    realized, r_values, accepted = [], [], []
    rng = np.random.default_rng(remove_seed) if remove_seed is not None else None
    for trade in trades:
        if not start <= trade["at"] < end:
            continue
        if accept is not None and not accept(trade):
            continue
        if rng is not None and rng.random() < 0.1:
            continue
        k = layers(
            balance, trade["entry"], trade["distance"], trade["fast"], trade["slow"]
        )
        if k <= 0:
            continue
        risk_dollars = 1000 * k * trade["distance"]
        cost_r = extra_cost / trade["distance"]
        for _, adverse, favorable in trade["path"]:
            # Conservative equity DD: realized prior peak versus adverse M1
            # extremum, then favorable extremum. The true tick-order is unknown.
            equity_min = balance + risk_dollars * (adverse - cost_r)
            max_dd = max(max_dd, (peak - equity_min) / peak)
            peak = max(peak, balance + risk_dollars * favorable)
        net_r = trade["r"] - cost_r
        pnl = risk_dollars * net_r
        balance += pnl
        peak = max(peak, balance)
        max_dd = max(max_dd, (peak - balance) / peak)
        realized.append(pnl)
        r_values.append(net_r)
        accepted.append(trade)
    wins = sum(p for p in realized if p > 0)
    losses = -sum(p for p in realized if p < 0)
    months = (end - start).total_seconds() / (365.25 / 12 * 86400)
    session_split = {}
    if accepted:
        labels = sessions(pd.DatetimeIndex([t["at"] for t in accepted]))
        for label in labels.unique():
            values = np.asarray(realized)[labels.to_numpy() == label]
            gains, loss = values[values > 0].sum(), -values[values < 0].sum()
            session_split[label] = {
                "trades": len(values),
                "profit_factor": float(gains / loss) if loss else None,
                "net_profit_usd": float(values.sum()),
            }
    return {
        "scope": "PUBLIC_BID_SYNTHETIC_COST_REPLAY",
        "policy_hash": POLICY_HASH,
        "trades": len(realized),
        "trades_month": len(realized) / months,
        "win_rate": float(np.mean(np.array(realized) > 0)) if realized else None,
        "profit_factor": wins / losses if losses else None,
        "expectancy_r": float(np.mean(r_values)) if r_values else None,
        "max_dd_equity_m1_percent": 100 * max_dd,
        "ending_balance_usd": balance,
        "net_return_percent": balance - 100,
        "average_r": float(np.mean(r_values)) if r_values else None,
        "median_r": float(np.median(r_values)) if r_values else None,
        "mae_r": float(np.mean([t["mae_r"] for t in accepted])) if accepted else None,
        "mfe_r": float(np.mean([t["mfe_r"] for t in accepted])) if accepted else None,
        "holding_minutes": float(np.mean([t["holding_minutes"] for t in accepted]))
        if accepted
        else None,
        "long": sum(t["side"] == 1 for t in accepted),
        "short": sum(t["side"] == -1 for t in accepted),
        "session_split": session_split,
        "sharpe": None,
        "sortino": None,
        "cost": {
            "spread": POLICY.virtual_spread,
            "slip_per_side": POLICY.virtual_slip,
            "extra_round_trip": extra_cost,
        },
        "limitations": [
            "M1 OHLC equity extrema, not tick-order drawdown",
            "No native broker ASK/spread history, swaps or execution latency",
            "Constant 1:100 research margin, not current DEMO broker leverage",
            "Conditional trade removal preserves frozen virtual feedback",
        ],
    }
