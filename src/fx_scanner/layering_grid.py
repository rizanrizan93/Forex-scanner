"""Offline, compiled layering search over immutable frozen opportunities.

1000 causal fill schedules x 100 sizing policies. No broker/DB authority.
"""

from itertools import product

import numpy as np
from numba import njit, prange

MAX_DEPTHS = np.linspace(0.15, 0.90, 10)
STAGES = (2, 3, 4, 5, 6)
TTLS = (15, 30, 45, 60, 90, 120, 150, 180, 210, 240)
PATTERNS = list(product(MAX_DEPTHS, STAGES, (False, True), TTLS))
SIZERS = list(
    product((0.2, 0.4, 0.6, 0.8, 1.0), (0.0, 0.5, 1.0, 1.5, 2.0), (0, 1), (False, True))
)
N_CONFIGS = len(PATTERNS) * len(SIZERS)
BASELINE_ID = N_CONFIGS


def configuration(identifier):
    if identifier == BASELINE_ID:
        return {"id": identifier, "name": "FROZEN_BASELINE"}
    depth, stages, confirmation, ttl = PATTERNS[identifier // 100]
    fraction, power, budget, throttle = SIZERS[identifier % 100]
    return {
        "id": int(identifier),
        "max_depth_r": float(depth),
        "stages": int(stages),
        "confirmed": bool(confirmation),
        "add_expiry_minutes": ttl,
        "initial_fraction_of_baseline_children": fraction,
        "depth_weight_power": power,
        "budget": "FROZEN_RISK_CAP" if budget else "BASELINE_PLANNED_USD",
        "closed_dd_10pct_half_budget": bool(throttle),
    }


@njit(cache=True, parallel=True)
def replay_batch(
    ids,
    geom,
    info,
    lengths,
    returns,
    slot_indices,
    slots,
    plan_sizes,
    policies,
    xau,
    start_ns,
    end_ns,
    initial_cash=100.0,
    mark_m1=True,
):
    """Exact native-child compounding with cached causal fill quotes/M1 marks.

    Columns: balance, PF, equity DD, closed DD, trades, wins, children, adds,
    max risk %, max margin %, long, short, train balance, train equity DD,
    train PF, train trades, annual prefix balances/DD/gains/losses/trades.
    The adaptive degear uses CLOSED equity DD, never future adverse extrema.
    """
    out = np.zeros((len(ids), 16))
    yearly = np.zeros((len(ids), 10, 5))
    for case in prange(len(ids)):
        identifier = ids[case]
        is_base = identifier == 100000
        p = 1000 if is_base else identifier // 100
        s = 0 if is_base else identifier % 100
        share = 1.0 if is_base else policies[s, 0]
        power = 0.0 if is_base else policies[s, 1]
        cap_budget = False if is_base else policies[s, 2] > 0
        throttle = False if is_base else policies[s, 3] > 0
        n = plan_sizes[p, 0]
        weights = np.zeros(6)
        denom = 0.0
        for stage in range(1, n):
            weights[stage] = (stage + 1.0) ** power
            denom += weights[stage]
        balance = peak_closed = peak_m1 = initial_cash
        dd = closed_dd = gains = losses = 0.0
        trades = wins = children = added = longs = shorts = 0
        maxrisk = maxmargin = 0.0
        cursor = start_ns - 1
        last_day = -1
        day_count = 0
        for t in range(len(geom)):
            at, exit_at, day, year = info[t]
            if at < start_ns or at >= end_ns or at <= cursor or balance <= 0:
                continue
            if day != last_day:
                last_day, day_count = day, 0
            if xau and day_count >= 6:
                continue
            _entry, distance, slip, units, scale, exit_return, unitmargin, immediate = (
                geom[t]
            )
            childrisk = units * (distance + slip)
            margin_fraction = (0.5 if xau else 0.6) * scale
            risk_fraction = (0.125 if xau else 0.2725) * scale
            hardcap = (
                2147483647 if xau else int(np.floor(195 * (balance / 100.0) ** 0.0625))
            )
            if xau:
                count = min(
                    max(1, int(np.floor(balance / 100.0))),
                    int(np.floor(risk_fraction * balance / childrisk)),
                    int(np.floor(margin_fraction * balance / unitmargin)),
                    int(np.floor(balance / (unitmargin + immediate))),
                )
            else:
                count = int(
                    np.floor(
                        min(
                            195 * (balance / 100.0) ** 0.0625,
                            risk_fraction * balance / childrisk,
                            margin_fraction * balance / unitmargin,
                        )
                        + 1e-9
                    )
                )
            if count < 1:
                continue
            degear = (
                0.5
                if throttle and (peak_closed - balance) / peak_closed >= 0.10
                else 1.0
            )
            budget = (
                balance * risk_fraction if cap_budget else count * childrisk
            ) * degear
            initial_qty = max(1, int(np.floor(count * share * degear)))
            initial_qty = min(initial_qty, int(np.floor(budget / childrisk + 1e-9)))
            if initial_qty < 1:
                continue
            remaining = max(0.0, budget - initial_qty * childrisk)
            totalq = 0
            offset_sum = risk_used = margin_used = 0.0
            fillq = np.zeros(6, np.int64)
            filloffset = np.zeros(6)
            cash_before = balance
            # Quantities depend on known fill-time equity, not on later marks.
            for stage in range(n):
                if slot_indices[p, t, stage] < 0:
                    continue
                delta, margin, risk, op_return, carry_credit, fill_cost = slots[
                    p, t, stage
                ]
                per_budget = (
                    initial_qty * childrisk
                    if stage == 0
                    else remaining * weights[stage] / denom
                )
                planned = (
                    initial_qty
                    if stage == 0
                    else int(np.floor(per_budget / risk + 1e-9))
                )
                floating = totalq * op_return + offset_sum
                mb = margin_fraction * max(
                    0.0, min(cash_before, cash_before + floating)
                )
                qty = min(
                    planned,
                    int(np.floor(max(0.0, budget - risk_used) / risk + 1e-9)),
                    int(np.floor(max(0.0, mb - margin_used) / margin + 1e-9)),
                    hardcap - totalq,
                )
                if xau:
                    qty = min(
                        qty,
                        int(
                            np.floor(
                                max(0.0, cash_before + floating - margin_used)
                                / (margin + fill_cost)
                            )
                        ),
                    )
                if qty < 1:
                    continue
                offset = delta + carry_credit
                fillq[stage], filloffset[stage] = qty, offset
                totalq += qty
                offset_sum += qty * offset
                risk_used += qty * risk
                margin_used += qty * margin
            if mark_m1 and totalq:
                running_q = 0
                running_offset = 0.0
                stage_cursor = 0
                for j in range(lengths[t]):
                    added_q = 0
                    while stage_cursor < n:
                        ix = slot_indices[p, t, stage_cursor]
                        if ix < 0:
                            stage_cursor += 1
                            continue
                        if ix > j:
                            break
                        qty = fillq[stage_cursor]
                        running_q += qty
                        running_offset += qty * filloffset[stage_cursor]
                        added_q += qty if stage_cursor > 0 else 0
                        stage_cursor += 1
                    low = running_q * returns[t, j, 0] + running_offset
                    high = running_q * returns[t, j, 1] + running_offset
                    if plan_sizes[p, 1] == 0 and added_q:
                        high += added_q * (returns[t, j, 2] - returns[t, j, 1])
                    if not xau:
                        peak_m1 = max(peak_m1, cash_before + high)
                    dd = max(dd, (peak_m1 - cash_before - low) / peak_m1)
                    peak_m1 = max(peak_m1, cash_before + high)
            if totalq < 1:
                continue
            pnl = totalq * exit_return + offset_sum
            balance += pnl
            cursor = exit_at
            day_count += 1
            trades += 1
            wins += pnl > 0
            children += totalq
            adds = 0
            for stage in range(1, n):
                adds += fillq[stage] > 0
            added += adds > 0
            longs += returns[t, 0, 3] > 0
            shorts += returns[t, 0, 3] < 0
            maxrisk = max(maxrisk, risk_used / cash_before)
            maxmargin = max(maxmargin, margin_used / cash_before)
            gains += max(pnl, 0.0)
            losses += max(-pnl, 0.0)
            peak_closed = max(peak_closed, balance)
            closed_dd = max(closed_dd, (peak_closed - balance) / peak_closed)
            peak_m1 = max(peak_m1, balance)
            dd = max(dd, (peak_m1 - balance) / peak_m1)
            y = year - 2016
            if 0 <= y < 10:
                yearly[case, y, 0] = balance
                yearly[case, y, 1] = dd
                yearly[case, y, 2] = gains
                yearly[case, y, 3] = losses
                yearly[case, y, 4] = trades
        # Fill years without an executable trade using previous prefix state.
        previous = np.array([initial_cash, 0.0, 0.0, 0.0, 0.0])
        for y in range(10):
            if yearly[case, y, 0] == 0:
                yearly[case, y] = previous
            previous = yearly[case, y].copy()
        train = yearly[case, 8]
        out[case] = np.array(
            [
                balance,
                gains / losses if losses > 0 else 0.0,
                dd * 100,
                closed_dd * 100,
                trades,
                wins,
                children,
                added,
                maxrisk * 100,
                maxmargin * 100,
                longs,
                shorts,
                train[0],
                train[1] * 100,
                train[2] / train[3] if train[3] > 0 else 0.0,
                train[4],
            ]
        )
    return out, yearly
