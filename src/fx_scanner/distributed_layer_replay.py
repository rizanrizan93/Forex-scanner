"""Research-only staged baskets. No broker, DB, dashboard, or order authority.

Signals/virtual feedback stay frozen. New fills use actual known quotes; an
earlier trough can qualify a depth stage but never grants a retrospective fill.
XAU signals must be supplied from the audited frozen archive.
"""

from dataclasses import asdict, dataclass
from math import floor

import numpy as np
import pandas as pd

from . import eurusd_frozen_dd37 as eur
from . import xau_frozen_dd50 as xau
from .cross_asset_lead_lag import sessions
from .cross_asset_replay import eurusd_virtual_trades


@dataclass(frozen=True)
class Variant:
    name: str
    spacing: float = 0.25
    exponent: int = 1
    confirmation: bool = False
    risk_normalized: bool = False
    expiry_minutes: int = 120
    delay_minutes: int = 0
    initial_full: bool = False


VARIANTS = [Variant("BASELINE")]
for step in (0.15, 0.25, 0.30):
    VARIANTS.extend(
        [
            Variant(f"UNIFORM_{step}", step, 0),
            Variant(f"DEEP_WEIGHTED_{step}", step, 1),
            Variant(f"CONFIRMED_DEEP_{step}", step, 1, True),
            Variant(f"CONFIRMED_MORE_{step}", step, 1, True, True),
            Variant(f"CONFIRMED_QUADRATIC_{step}", step, 2, True, True),
        ]
    )

for step in (0.15, 0.25, 0.30):
    for power in (1, 2):
        VARIANTS.append(
            Variant(
                f"FULL_INITIAL_CONFIRMED_{power}_{step}",
                step,
                power,
                True,
                True,
                initial_full=True,
            )
        )


def load_raw(directory, symbol):
    from pathlib import Path

    parts = []
    for p in sorted(Path(directory).glob(symbol + "_*.parquet")):
        f = pd.read_parquet(p)
        f.index = (
            pd.DatetimeIndex(f.datetime).tz_localize("Etc/GMT+5").tz_convert("UTC")
        )
        parts.append(f[["open", "high", "low", "close"]])
    raw = pd.concat(parts).sort_index()
    if raw.index.duplicated().any() or not np.isfinite(raw.to_numpy()).all():
        raise ValueError("INVALID_RAW_HISTORY")
    return raw


def completed(raw, minutes):
    f = raw.resample(f"{minutes}min", closed="left", label="right").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    )
    count = raw.close.resample(f"{minutes}min", closed="left", label="right").count()
    return f[count == minutes].dropna()


def reversal_features(raw, symbol):
    """M15 and M5 break prior completed candle; H1 frozen bias must allow side.

    Fresh complete buckets only. No centered swings or future pivot confirmation.
    Confirmation boolean is recomputed each M5 closure; expires after one M5.
    """
    m5, m15, h1 = (completed(raw, m) for m in (5, 15, 60))
    bias = xau.strict(h1) if symbol == "XAUUSD" else _eur_h1_bias(h1)
    a = pd.DataFrame(index=m5.index)
    a["m5_buy"] = (m5.close > m5.high.shift(1)) & (m5.close > m5.open)
    a["m5_sell"] = (m5.close < m5.low.shift(1)) & (m5.close < m5.open)
    b = pd.DataFrame(index=m15.index)
    b["m15_buy"] = (m15.close > m15.high.shift(1)) & (m15.close > m15.open)
    b["m15_sell"] = (m15.close < m15.low.shift(1)) & (m15.close < m15.open)
    b["m15_bias"] = xau.strict(m15)
    a = a.join(b.reindex(a.index, method="ffill", tolerance=pd.Timedelta(minutes=15)))
    a["h1_bias"] = bias.reindex(
        a.index, method="ffill", tolerance=pd.Timedelta(minutes=60)
    )
    if symbol == "XAUUSD":
        buy_htf = (a.h1_bias == 1) & (a.m15_bias == 1)
        sell_htf = (a.h1_bias == -1) & (a.m15_bias == -1)
    else:
        buy_htf = a.h1_bias.isin([0, 1])
        sell_htf = a.h1_bias.isin([0, -1])
    result = pd.DataFrame(
        {
            "buy": a.m5_buy & a.m15_buy & buy_htf,
            "sell": a.m5_sell & a.m15_sell & sell_htf,
        }
    )
    return result.fillna(False)


def _eur_h1_bias(h):
    ema = h.close.ewm(span=50, adjust=False).mean()
    slope = ema - ema.shift(3)
    return pd.Series(
        np.where(
            (h.close > ema) & (slope > 0),
            1,
            np.where((h.close < ema) & (slope < 0), -1, 0),
        ),
        index=h.index,
    )


def bracket_exit(
    at,
    bar,
    *,
    side,
    entry,
    distance,
    target_r,
    spread,
    slip,
    previous_at,
    previous_close,
    expiry,
):
    """STOP_FIRST, gap exit, no quote interpolation. Returns exit price/reason."""
    offset = spread if side == -1 else 0
    op, hi, lo = bar[:3] + offset
    if previous_at is not None and at - previous_at > pd.Timedelta(minutes=5):
        return op - side * slip, "GAP"
    if at >= expiry:
        return previous_close + offset - side * slip, "TIME"
    stop, target = entry - side * distance, entry + side * distance * target_r
    if lo <= stop if side == 1 else hi >= stop:
        return (min(stop, op) if side == 1 else max(stop, op)) - side * slip, "STOP"
    if hi >= target if side == 1 else lo <= target:
        return target - side * slip, "TARGET"
    return None, None


def opportunities(raw, symbol):
    if symbol == "EURUSD":
        records = eurusd_virtual_trades(raw)
        return [
            {
                k: t[k]
                for k in (
                    "at",
                    "exit_at",
                    "side",
                    "entry",
                    "distance",
                    "fast",
                    "slow",
                    "r",
                )
            }
            for t in records
        ]
    raise ValueError("XAU_REQUIRES_FROZEN_ARCHIVED_SIGNALS")


def integer_allocation(total, exponent):
    """Reserve at least one initial child; redistribute integer remainder."""
    n = min(4, total)
    if n <= 0:
        return []
    weights = np.arange(1, n + 1, dtype=float) ** exponent
    first = max(1, floor(total * weights[0] / weights.sum()))
    if n == 1:
        return [total]
    ideal = (total - first) * weights[1:] / weights[1:].sum()
    rest = np.floor(ideal).astype(int)
    for j in np.argsort(-(ideal - rest), kind="stable")[
        : total - first - int(rest.sum())
    ]:
        rest[j] += 1
    return [first, *rest.tolist()]


def simulate_basket(
    trace, opportunity, symbol, balance, variant, *, spread_factor=1.0, slip_factor=1.0
):
    """All entries share initial absolute SL/TP; risk cap fixed at basket start.

    risk_normalized may exceed baseline child count after confirmation, but not
    baseline planned dollar risk, frozen margin or EUR hard count cap. XAU's
    balance-step desired count is explicitly relaxed ONLY in this research mode.
    """
    if symbol == "XAUUSD":
        return simulate_frozen_xau(
            trace,
            opportunity,
            balance,
            variant,
            spread_factor=spread_factor,
            slip_factor=slip_factor,
        )
    side, distance = opportunity["side"], opportunity["distance"]
    spread = (0.00012 if symbol == "EURUSD" else 0.30) * spread_factor
    slip = (0.00001 if symbol == "EURUSD" else 0.05) * slip_factor
    units, target_r = (1000, 4.0) if symbol == "EURUSD" else (1, 6.6)
    at = opportunity["at"]
    initial = trace.open.iloc[0] + (spread if side == 1 else 0) + side * slip
    stop = initial - side * distance
    scale = (
        eur.multiplier(opportunity["fast"], opportunity["slow"])
        if symbol == "EURUSD"
        else 1.0
    )
    margin_fraction = (0.6 if symbol == "EURUSD" else 0.5) * scale
    if symbol == "EURUSD":
        count = eur.layers(
            balance, initial, distance, opportunity["fast"], opportunity["slow"]
        )
        hard_cap = floor(195 * (balance / 100) ** 0.0625)
    else:
        count = xau.layers(balance, balance, distance, units * initial / 100, balance)
        hard_cap = 10**9
    if count <= 0:
        return None
    risk_budget = count * units * (distance + slip)
    # Never widen the frozen cap even if stress slippage exceeds its allowance.
    risk_budget = min(
        risk_budget, balance * (0.2725 if symbol == "EURUSD" else 0.125) * scale
    )
    if variant.initial_full:
        risk_budget = balance * (0.2725 if symbol == "EURUSD" else 0.125) * scale
        quantities, n = [count], 4
    elif variant.name == "BASELINE":
        quantities, n = [count], 1
    else:
        quantities = integer_allocation(count, variant.exponent)
        n = 4 if variant.risk_normalized and count > 1 else len(quantities)
    depths = np.arange(n) * variant.spacing
    weights = np.arange(1, n + 1, dtype=float) ** variant.exponent
    initial_qty = quantities[0]
    reserved = initial_qty * units * (distance + slip)
    risk_shares = np.zeros(n)
    if n > 1:
        risk_shares[1:] = (
            max(0, risk_budget - reserved) * weights[1:] / weights[1:].sum()
        )
    holdings, filled, fill_records = [], set(), []
    used_risk = used_margin = 0.0
    elapsed_deadline = at + pd.Timedelta(minutes=variant.expiry_minutes)
    expiry = min(
        at + pd.Timedelta(minutes=240 if symbol == "EURUSD" else 480),
        at.normalize() + pd.Timedelta(hours=20),
    )
    deepest = 0.0
    previous_at, previous_close = at, trace.open.iloc[0]
    previous_confirmation = None
    min_pnl = max_pnl = 0.0
    risk_peak = margin_peak = 0.0
    equity_path = []
    values = trace[["open", "high", "low", "close"]].to_numpy(dtype=float)
    buy_flags, sell_flags = trace.buy_confirm.to_numpy(), trace.sell_confirm.to_numpy()
    confirm_times = trace.confirm_at.to_numpy()
    for j, (bt, bar) in enumerate(zip(trace.index, values)):
        px, exit_reason = bracket_exit(
            bt,
            bar,
            side=side,
            entry=initial,
            distance=distance,
            target_r=target_r,
            spread=spread,
            slip=slip,
            previous_at=previous_at,
            previous_close=previous_close,
            expiry=expiry,
        )
        gap_or_expiry = exit_reason in ("GAP", "TIME")
        open_exit_quote = bar[0] + (spread if side == -1 else 0)
        invalid_open = side * (open_exit_quote - stop) <= 0
        new_limits = set()
        confirmation = bool(buy_flags[j] if side == 1 else sell_flags[j])
        for stage in range(n):
            if stage in filled or gap_or_expiry or (stage > 0 and invalid_open):
                continue
            if stage == 0:
                eligible, fill = True, initial
            elif bt > elapsed_deadline:
                continue
            elif variant.confirmation:
                # Only one stage per completed confirmation; additions cannot
                # retrospectively buy the trough that established this depth.
                eligible = (
                    deepest >= depths[stage]
                    and confirmation
                    and confirm_times[j] != previous_confirmation
                )
                fill = bar[0] + (spread if side == 1 else 0) + side * slip
                eligible = eligible and side * (initial - fill) >= 0.05 * distance
            else:
                target = initial + side * distance * target_r
                target_hit = (
                    bar[1] >= target if side == 1 else bar[2] + spread <= target
                )
                stop_hit = bar[2] <= stop if side == 1 else bar[1] + spread >= stop
                if target_hit and not stop_hit:
                    # Unknown intrabar order: cancel pending limits if the
                    # existing basket could have reached TP first.
                    continue
                trigger = initial - side * depths[stage] * distance
                extreme = bar[2] + spread if side == 1 else bar[1]
                eligible = extreme <= trigger if side == 1 else extreme >= trigger
                fill = trigger + side * slip  # conservative limit slippage
                if eligible:
                    new_limits.add(stage)
            if not eligible:
                continue
            child_risk = units * (side * (fill - stop) + slip)
            child_margin = units * fill / 100
            if child_risk <= 0 or child_margin <= 0:
                continue
            planned = (
                initial_qty
                if stage == 0
                else (
                    floor(risk_shares[stage] / child_risk + 1e-9)
                    if variant.risk_normalized
                    else quantities[stage]
                )
            )
            # Floating equity constrains margin too; no recycling floating gain
            # into a larger risk allowance. Budget is fixed at basket open.
            floating = sum(
                q * units * side * (open_exit_quote - e) for _, q, e in holdings
            )
            margin_budget = max(0, min(balance, balance + floating) * margin_fraction)
            q = min(
                planned,
                floor(max(0, risk_budget - used_risk) / child_risk + 1e-9),
                floor(max(0, margin_budget - used_margin) / child_margin + 1e-9),
                hard_cap - sum(h[1] for h in holdings),
            )
            filled.add(stage)
            if q <= 0:
                continue
            holdings.append((stage, q, fill))
            fill_records.append(
                {
                    "at": bt.isoformat(),
                    "stage": stage,
                    "children": q,
                    "entry": float(fill),
                    "depth_r": float(side * (initial - fill) / distance),
                }
            )
            used_risk += q * child_risk
            used_margin += q * child_margin
            risk_peak = max(risk_peak, used_risk / balance)
            margin_peak = max(margin_peak, used_margin / balance)
            if stage > 0 and variant.confirmation:
                previous_confirmation = confirm_times[j]
        if holdings:
            adverse = bar[2] if side == 1 else bar[1] + spread
            favorable = bar[1] if side == 1 else bar[2] + spread
            if px is not None:
                if exit_reason == "STOP":
                    adverse = px + side * slip
                    favorable = (
                        min(favorable, initial + distance * target_r)
                        if side == 1
                        else max(favorable, initial - distance * target_r)
                    )
                elif exit_reason == "TARGET":
                    favorable = px + side * slip
                    adverse = max(adverse, stop) if side == 1 else min(adverse, stop)
                else:
                    adverse = favorable = px + side * slip
            low_pnl = sum(
                q * units * side * (adverse - side * slip - e) for _, q, e in holdings
            )
            high_pnl = 0.0
            for stage, q, e in holdings:
                # A limit filled intrabar cannot earn that bar's pre-fill high.
                fav = (
                    bar[3] + (spread if side == -1 else 0)
                    if stage in new_limits
                    else favorable
                )
                high_pnl += q * units * max(side * (fav - side * slip - e), 0.0)
            min_pnl, max_pnl = min(min_pnl, low_pnl), max(max_pnl, high_pnl)
            equity_path.append((float(low_pnl), float(high_pnl)))
        if px is not None:
            net = sum(q * units * side * (px - e) for _, q, e in holdings)
            return {
                "at": at,
                "exit_at": previous_at if exit_reason == "TIME" else bt,
                "side": side,
                "pnl": float(net),
                "risk_budget": risk_budget,
                "net_r": float(net / risk_budget),
                "mae_r": -min_pnl / risk_budget,
                "mfe_r": max_pnl / risk_budget,
                "path": equity_path,
                "fills": fill_records,
                "children": sum(h[1] for h in holdings),
                "max_risk_percent": 100 * risk_peak,
                "max_margin_percent": 100 * margin_peak,
                "gap": exit_reason == "GAP",
                "holding_minutes": (bt - at).total_seconds() / 60,
            }
        quote_adverse = bar[2] + spread if side == 1 else bar[1]
        deepest = max(deepest, side * (initial - quote_adverse) / distance)
        previous_at, previous_close = bt, bar[3]
    raise ValueError("INCOMPLETE_REPLAY_TRACE")


def prepare_traces(raw, records, reversal):
    """Cache only opportunity slices, with timestamped causal confirmation."""
    traces = []
    rev = reversal.copy()
    rev["confirm_at"] = rev.index
    for t in records:
        i = raw.index.get_loc(t["at"])
        trace = raw.iloc[i : i + 501].copy()
        flags = rev.reindex(
            trace.index, method="ffill", tolerance=pd.Timedelta(minutes=4)
        )
        trace["buy_confirm"] = flags.buy.eq(True)
        trace["sell_confirm"] = flags.sell.eq(True)
        trace["confirm_at"] = flags.confirm_at
        traces.append(trace)
    return traces


def account(
    records, traces, symbol, variant, start, end, *, initial_balance=100.0, **stress
):
    balance = peak = float(initial_balance)
    dd = 0.0
    accepted = []
    cursor = start - pd.Timedelta(minutes=1)
    day_counts = {}
    for t, trace in zip(records, traces):
        day = t["at"].tz_convert("Asia/Jakarta").date()
        if symbol == "XAUUSD" and day_counts.get(day, 0) >= 6:
            continue
        if not start <= t["at"] < end or t["at"] <= cursor or balance <= 0:
            continue
        if variant.delay_minutes:
            trace = trace.copy()
            flags = (
                trace[["buy_confirm", "sell_confirm", "confirm_at"]]
                .shift(freq=pd.Timedelta(minutes=variant.delay_minutes))
                .reindex(trace.index)
            )
            trace[["buy_confirm", "sell_confirm"]] = flags[
                ["buy_confirm", "sell_confirm"]
            ].eq(True)
            trace["confirm_at"] = flags.confirm_at
        result = simulate_basket(trace, t, symbol, balance, variant, **stress)
        if result is None:
            continue
        cursor = result["exit_at"]
        if not result["children"]:
            continue
        for low, high in result["path"]:
            # Conservative M1 bound: highest possible equity before adverse
            # extremum. Exact tick-order DD is unavailable; same rule all modes.
            if symbol != "XAUUSD":
                peak = max(peak, balance + high)
            dd = max(dd, (peak - (balance + low)) / peak)
            peak = max(peak, balance + high)
        balance += result["pnl"]
        peak = max(peak, balance)
        dd = max(dd, (peak - balance) / peak)
        accepted.append(result)
        day_counts[day] = day_counts.get(day, 0) + 1
    gains = sum(max(0, t["pnl"]) for t in accepted)
    losses = -sum(min(0, t["pnl"]) for t in accepted)
    months = (end - start).total_seconds() / (365.25 / 12 * 86400)
    rs = [t["net_r"] for t in accepted]
    labels = sessions(pd.DatetimeIndex([t["at"] for t in accepted])) if accepted else []
    summary = {
        "variant": asdict(variant),
        "trades": len(accepted),
        "ending_balance_usd": balance,
        "initial_balance_usd": initial_balance,
        "net_return_percent": 100 * (balance / initial_balance - 1),
        "profit_factor": gains / losses if losses else None,
        "max_dd_equity_m1_bound_percent": 100 * dd,
        "win_rate": sum(t["pnl"] > 0 for t in accepted) / len(accepted)
        if accepted
        else None,
        "expectancy_r": float(np.mean(rs)) if rs else None,
        "median_r": float(np.median(rs)) if rs else None,
        "trades_month": len(accepted) / months,
        "children": sum(t["children"] for t in accepted),
        "baskets_with_adds": sum(len(t["fills"]) > 1 for t in accepted),
        "max_children": max((t["children"] for t in accepted), default=0),
        "mae_r": float(np.mean([t["mae_r"] for t in accepted])) if accepted else None,
        "mfe_r": float(np.mean([t["mfe_r"] for t in accepted])) if accepted else None,
        "hold_minutes": float(np.mean([t["holding_minutes"] for t in accepted]))
        if accepted
        else None,
        "max_planned_risk_percent": max(
            (t["max_risk_percent"] for t in accepted), default=0
        ),
        "max_margin_percent": max(
            (t["max_margin_percent"] for t in accepted), default=0
        ),
        "long": sum(t["side"] == 1 for t in accepted),
        "short": sum(t["side"] == -1 for t in accepted),
        "gap_exits": sum(t["gap"] for t in accepted),
        "session_split": {str(k): int(sum(labels == k)) for k in set(labels)},
    }
    return summary, accepted


def simulate_frozen_xau(
    trace, opportunity, balance, variant, *, spread_factor=1.0, slip_factor=1.0
):
    """Frozen XAU geometry/cost/expiry with staged fills and fixed basket risk.

    Archived STOP_FIRST and adverse-then-close marking are retained. Synthetic
    NY rollover is charged per child from its own fill, never before it exists.
    """
    side = opportunity["side"]
    slip = 0.05 * slip_factor
    quotes = trace[["open", "high", "low", "close"]].to_numpy(float)
    spreads = trace.spread.to_numpy(float) * spread_factor
    rolls = trace.roll.to_numpy(float)
    s0 = spreads[0]
    if s0 > 1.5:
        return None
    initial = quotes[0, 0] + (s0 if side == 1 else 0) + side * slip
    anchor = opportunity["anchor"] + (s0 if side == -1 else 0)
    distance = max(2.65 * opportunity["atr"], 0.5)
    if np.isfinite(anchor):
        distance = max(distance, side * (initial - anchor))
    child_risk, child_margin = distance + slip, initial / 100
    count = min(
        max(1, floor(balance / 100)),
        floor(0.125 * balance / child_risk),
        floor(0.5 * balance / child_margin),
        floor(balance / (child_margin + s0 + slip)),
    )
    if count < 1:
        return None
    while count and (
        count * child_risk > 0.125 * balance
        or count * child_margin > 0.5 * balance
        or balance - count * (s0 + slip) < count * child_margin
    ):
        count -= 1
    if count < 1:
        return None
    stop, target = initial - side * distance, initial + side * 6.6 * distance
    budget = 0.125 * balance if variant.initial_full else count * child_risk
    quantities = (
        [count]
        if variant.name == "BASELINE"
        else integer_allocation(count, variant.exponent)
    )
    if variant.initial_full:
        quantities = [count]
    n = (
        4
        if variant.initial_full or (variant.risk_normalized and count > 1)
        else len(quantities)
    )
    weights = np.arange(1, n + 1, dtype=float) ** variant.exponent
    shares = np.zeros(n)
    if n > 1:
        shares[1:] = (
            max(0.0, budget - quantities[0] * child_risk)
            * weights[1:]
            / weights[1:].sum()
        )
    at = opportunity["at"]
    expiry = min(
        at + pd.Timedelta(minutes=480),
        at.normalize() + pd.Timedelta(hours=19, minutes=59),
    )
    add_deadline = at + pd.Timedelta(minutes=variant.expiry_minutes)
    holdings, fills, filled, path = [], [], set(), []
    used_risk = used_margin = deepest = 0.0
    min_pnl = max_pnl = 0.0
    previous_confirmation = None
    buy, sell = trace.buy_confirm.to_numpy(), trace.sell_confirm.to_numpy()
    confirmed_at = trace.confirm_at.to_numpy()
    for j, (bt, bar) in enumerate(zip(trace.index, quotes)):
        spread, roll = spreads[j], rolls[j]
        offset = spread if side == -1 else 0.0
        op, hi, lo, cl = bar + offset
        timed = bt >= expiry
        invalid_open = side * (op - stop) <= 0
        fresh = (
            bool(buy[j] if side == 1 else sell[j])
            and confirmed_at[j] != previous_confirmation
        )
        new_limits = set()
        for stage in range(n):
            if stage in filled or (
                stage > 0 and (timed or invalid_open or bt > add_deadline)
            ):
                continue
            if stage == 0:
                eligible, fill = True, initial
            elif variant.confirmation:
                fill = bar[0] + (spread if side == 1 else 0.0) + side * slip
                eligible = (
                    fresh
                    and deepest >= stage * variant.spacing
                    and side * (initial - fill) >= 0.05 * distance
                )
            else:
                target_hit = side * ((hi if side == 1 else lo) - target) >= 0
                stop_hit = side * ((lo if side == 1 else hi) - stop) <= 0
                if target_hit and not stop_hit:
                    continue
                trigger = initial - side * stage * variant.spacing * distance
                extreme = bar[2] + spread if side == 1 else bar[1]
                eligible = extreme <= trigger if side == 1 else extreme >= trigger
                fill = trigger + side * slip
                if eligible:
                    new_limits.add(stage)
            if not eligible:
                continue
            risk = side * (fill - stop) + slip
            margin = fill / 100
            if risk <= 0 or margin <= 0:
                continue
            planned = (
                quantities[0]
                if stage == 0
                else (
                    floor(shares[stage] / risk + 1e-9)
                    if variant.risk_normalized
                    else quantities[stage]
                )
            )
            floating = sum(
                q * side * (op - e) - q * max(roll - r, 0) for q, e, r in holdings
            )
            margin_budget = 0.5 * max(0.0, min(balance, balance + floating))
            q = min(
                planned,
                floor(max(0.0, budget - used_risk) / risk + 1e-9),
                floor(max(0.0, margin_budget - used_margin) / margin + 1e-9),
            )
            # Original free-equity margin rule also includes immediate spread.
            q = min(
                q,
                floor(
                    max(0.0, balance + floating - used_margin)
                    / (margin + spread + slip)
                ),
            )
            filled.add(stage)
            if q < 1:
                continue
            holdings.append((q, fill, roll))
            fills.append(
                {
                    "at": bt.isoformat(),
                    "stage": stage,
                    "children": q,
                    "entry": float(fill),
                    "depth_r": float(side * (initial - fill) / distance),
                }
            )
            used_risk += q * risk
            used_margin += q * margin
            if stage > 0 and variant.confirmation:
                previous_confirmation = confirmed_at[j]
                fresh = False
        qty = sum(q for q, _, _ in holdings)
        if qty == 0:
            return None
        carry = sum(q * max(roll - r, 0) for q, _, r in holdings)
        mean_entry = sum(q * e for q, e, _ in holdings) / qty
        mlevel = mean_entry - side * (balance - carry - 0.5 * used_margin) / qty
        marginnear = side * (mlevel - stop) > 0
        effective = mlevel if marginnear else stop
        adverse, favorable = (lo, hi) if side == 1 else (hi, lo)
        reason, exitpx = None, None
        if timed:
            exitpx, reason = op - side * slip, "TIME"
            if side * (op - target) >= 0:
                exitpx, reason = target, "TARGET"
            # Frozen time exit uses actual open even through the stop.
            if side * (op - effective) <= 0:
                reason = "MARGIN" if marginnear else "STOP"
            low = high = sum(q * side * (exitpx - e) for q, e, _ in holdings) - carry
        else:
            worst = min(adverse, target) if side == 1 else max(adverse, target)
            if side * (worst - effective) <= 0:
                worst = (
                    min(effective, op) if side == 1 else max(effective, op)
                ) - side * slip
            low = sum(q * side * (worst - e) for q, e, _ in holdings) - carry
            if side * (adverse - effective) <= 0:
                exitpx = (
                    min(effective, op) if side == 1 else max(effective, op)
                ) - side * slip
                reason = "MARGIN" if marginnear else "STOP"
            elif side * (favorable - target) >= 0:
                exitpx, reason = target, "TARGET"
            high = (
                sum(q * side * (cl - e) for q, e, _ in holdings) - carry
                if reason is None
                else low
            )
        path.append((float(low), float(high)))
        min_pnl = min(min_pnl, low)
        # MFE is observed favorable excursion; not used as account DD peak.
        fav = cl if new_limits else favorable
        fav = min(fav, target) if side == 1 else max(fav, target)
        max_pnl = max(
            max_pnl, sum(q * side * (fav - e) for q, e, _ in holdings) - carry
        )
        if exitpx is not None:
            net = sum(q * side * (exitpx - e) for q, e, _ in holdings) - carry
            return {
                "at": at,
                "exit_at": bt - pd.Timedelta(nanoseconds=1) if timed else bt,
                "side": side,
                "pnl": float(net),
                "risk_budget": budget,
                "net_r": float(net / budget),
                "mae_r": -min_pnl / budget,
                "mfe_r": max_pnl / budget,
                "path": path,
                "fills": fills,
                "children": qty,
                "max_risk_percent": 100 * used_risk / balance,
                "max_margin_percent": 100 * used_margin / balance,
                "gap": False,
                "holding_minutes": (bt - at).total_seconds() / 60,
                "carry_usd": float(carry),
                "exit_reason": reason,
                "stop": float(stop),
                "target": float(target),
                "distance": float(distance),
                "baseline_children": count,
                "marking": "ADVERSE_THEN_CLOSE",
            }
        extreme = bar[2] + spread if side == 1 else bar[1]
        deepest = max(deepest, side * (initial - extreme) / distance)
    raise ValueError("INCOMPLETE_FROZEN_XAU_TRACE")
