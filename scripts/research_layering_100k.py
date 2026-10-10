"""100,000 layering configurations, frozen signals, exact cached M1 equity."""

import argparse
import hashlib
import json
import pickle
import time
from pathlib import Path

import numpy as np
import pandas as pd
from numba import set_num_threads

from fx_scanner.distributed_layer_replay import (
    Variant,
    load_raw,
    opportunities,
    prepare_traces,
    reversal_features,
    simulate_basket,
)
from fx_scanner.frozen_xau_layer_inputs import load_frozen
from fx_scanner.layering_grid import (
    BASELINE_ID,
    N_CONFIGS,
    PATTERNS,
    SIZERS,
    configuration,
    replay_batch,
)

START = pd.Timestamp("2016-01-01", tz="UTC").value
END = pd.Timestamp("2026-01-01", tz="UTC").value


def build(
    data,
    symbol,
    cache,
    *,
    spread_factor=1.0,
    slip_factor=1.0,
    confirm_delay_minutes=0,
    pattern_ids=None,
    execution_quote_drop=0.0,
):
    files = (
        sorted(data.glob("EURUSD_*.parquet"))
        if symbol == "EURUSD"
        else sorted(list((data / "data").glob("*.csv")) + list(data.glob("g-*.npz")))
    )
    proof = [
        {"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in files
    ]
    fingerprint = hashlib.sha256(json.dumps(proof, sort_keys=True).encode()).hexdigest()
    cache.mkdir(parents=True, exist_ok=True)
    cp = cache / f"{symbol}_{fingerprint}_frozen.pkl"
    if cp.exists():
        records, traces = pickle.loads(cp.read_bytes())
    else:
        print("LOAD", symbol, flush=True)
        if symbol == "XAUUSD":
            raw, records = load_frozen(data)
        else:
            raw = load_raw(data, symbol)
            records = opportunities(raw, symbol)
        traces = prepare_traces(raw, records, reversal_features(raw, symbol))
        cp.write_bytes(pickle.dumps((records, traces), protocol=5))
    selected_patterns = None if pattern_ids is None else set(pattern_ids)
    rng = np.random.default_rng(110100)
    xau = symbol == "XAUUSD"
    nt = len(records)
    geom = np.zeros((nt, 8))
    info = np.zeros((nt, 4), np.int64)
    lengths = np.zeros(nt, np.int64)
    returns = np.zeros((nt, 501, 4))
    idx = np.full((1001, nt, 6), -1, np.int16)
    slots = np.zeros((1001, nt, 6, 6))
    sizes = np.zeros((1001, 2), np.int64)
    for p, (depth, n, confirm, ttl) in enumerate(PATTERNS):
        sizes[p] = n, int(confirm)
    sizes[1000] = 1, 1
    for t, (opp, trace) in enumerate(zip(records, traces)):
        if execution_quote_drop:
            keep = rng.random(len(trace)) >= execution_quote_drop
            keep[0] = keep[-1] = True
            trace = trace.iloc[keep]
        side = opp["side"]
        units = 1 if xau else 1000
        spread = trace.spread.to_numpy() if xau else np.full(len(trace), 0.00012)
        spread = spread * spread_factor
        slip = (0.05 if xau else 0.00001) * slip_factor
        roll = trace.roll.to_numpy() if xau else np.zeros(len(trace))
        entry = trace.open.iloc[0] + (spread[0] if side == 1 else 0) + side * slip
        if xau:
            anchor = opp["anchor"] + (spread[0] if side == -1 else 0)
            distance = max(
                2.65 * opp["atr"],
                0.5,
                side * (entry - anchor) if np.isfinite(anchor) else 0,
            )
            scale = 1.0
        else:
            from fx_scanner.eurusd_frozen_dd37 import multiplier

            distance = opp["distance"]
            scale = multiplier(opp["fast"], opp["slow"])
        result = simulate_basket(
            trace,
            opp,
            symbol,
            1_000_000.0,
            Variant("BASELINE"),
            spread_factor=spread_factor,
            slip_factor=slip_factor,
        )
        if result is None:
            raise ValueError("GEOMETRY_REFERENCE_REJECTED")
        length = len(result["path"])
        lengths[t] = length
        arrays = np.asarray(result["path"]) / result["children"]
        returns[t, :length, :2] = arrays
        # EUR old marker clamps each child's positive excursion; aggregate
        # floating equity is used here. Baseline remains numerically identical.
        px = trace[["open", "high", "low", "close"]].to_numpy()
        offset = np.where(side == -1, spread, 0.0)
        quote_close = px[:, 3] + offset
        close_return = units * side * (quote_close - entry) - (roll - roll[0])
        returns[t, :length, 2] = close_return[:length]
        if xau:
            terminal = result["exit_reason"]
            if terminal in ("STOP", "MARGIN", "TARGET", "TIME"):
                returns[t, length - 1, 2] = arrays[-1, 1]
        else:
            target = entry + side * 4 * distance
            stop = entry - side * distance
            fav = px[:length, 1] if side == 1 else px[:length, 2] + spread[:length]
            fav = np.minimum(fav, target) if side == 1 else np.maximum(fav, target)
            returns[t, :length, 1] = units * side * (fav - side * slip - entry)
            # TIME/GAP liquidation: no subsequent whole-bar excursion.
            actual_at = trace.index[0] + pd.Timedelta(minutes=result["holding_minutes"])
            terminal_bar = trace.loc[actual_at]
            normal_target = (
                terminal_bar.high >= target
                if side == 1
                else terminal_bar.low + spread[length - 1] <= target
            )
            normal_stop = (
                terminal_bar.low <= stop
                if side == 1
                else terminal_bar.high + spread[length - 1] >= stop
            )
            if arrays[-1, 0] == arrays[-1, 1] or (
                not normal_target and not normal_stop
            ):
                returns[t, length - 1, :3] = arrays[-1, 0]
        returns[t, 0, 3] = side
        exit_return = result["pnl"] / result["children"]
        geom[t] = (
            entry,
            distance,
            slip,
            units,
            scale,
            exit_return,
            units * entry / 100,
            units * (spread[0] + slip),
        )
        day = int(trace.index[0].tz_convert("Asia/Jakarta").strftime("%Y%m%d"))
        info[t] = opp["at"].value, result["exit_at"].value, day, opp["at"].year
        op_quote = px[:, 0] + offset
        op_return = units * side * (op_quote - entry) - (roll - roll[0])
        extremum = px[:, 2] + spread if side == 1 else px[:, 1]
        depth_seen = side * (entry - extremum) / distance
        deepest_previous = np.r_[0, np.maximum.accumulate(depth_seen)[:-1]]
        flag_frame = trace[["buy_confirm", "sell_confirm", "confirm_at"]]
        if confirm_delay_minutes:
            flag_frame = flag_frame.shift(
                freq=pd.Timedelta(minutes=confirm_delay_minutes)
            ).reindex(trace.index)
        flags = (
            flag_frame["buy_confirm" if side == 1 else "sell_confirm"]
            .eq(True)
            .to_numpy()
        )
        stamps = (
            pd.to_datetime(flag_frame.confirm_at, utc=True).astype("int64").to_numpy()
        )
        invalid = side * (op_quote - (entry - side * distance)) <= 0
        elapsed = (trace.index - opp["at"]).total_seconds().to_numpy() / 60
        target = entry + side * (6.6 if xau else 4) * distance
        target_hit = px[:, 1] >= target if side == 1 else px[:, 2] + spread <= target
        stop_hit = (
            px[:, 2] <= entry - distance
            if side == 1
            else px[:, 1] + spread >= entry + distance
        )
        fill_quote = px[:, 0] + (spread if side == 1 else 0) + side * slip
        beneficial = side * (entry - fill_quote) >= 0.05 * distance
        stage_cache = {}
        for p, (maximum, n, confirm, ttl) in enumerate(PATTERNS):
            if selected_patterns is not None and p not in selected_patterns:
                continue
            key = (maximum, n, confirm)
            if key not in stage_cache:
                chosen = [0]
                last_stamp = -9223372036854775808
                for stage in range(1, n):
                    depth = maximum * stage / (n - 1)
                    if confirm:
                        eligible = (
                            (deepest_previous >= depth)
                            & flags
                            & beneficial
                            & ~invalid
                            & (stamps != last_stamp)
                        )
                    else:
                        eligible = (
                            (depth_seen >= depth) & ~invalid & ~(target_hit & ~stop_hit)
                        )
                    eligible[length:] = False
                    eligible[0] = eligible[0] and not confirm
                    if chosen[-1] < 0:
                        chosen.append(-1)
                        continue
                    eligible[: chosen[-1]] = False
                    candidates = np.flatnonzero(eligible)
                    j = int(candidates[0]) if len(candidates) else -1
                    chosen.append(j)
                    if j >= 0 and confirm:
                        last_stamp = stamps[j]
                stage_cache[key] = chosen
            chosen = stage_cache[key]
            for stage, j in enumerate(chosen):
                if j < 0 or (stage > 0 and elapsed[j] > ttl):
                    continue
                # Frozen TIME/GAP expiry bars cannot add positions.
                if (
                    stage > 0
                    and j == length - 1
                    and (result["exit_at"] < trace.index[j] or result.get("gap", False))
                ):
                    continue
                if stage == 0:
                    fill = entry
                elif confirm:
                    fill = fill_quote[j]
                else:
                    fill = (
                        entry
                        - side * (maximum * stage / (n - 1)) * distance
                        + side * slip
                    )
                risk = units * (side * (fill - (entry - side * distance)) + slip)
                if risk <= 0:
                    continue
                idx[p, t, stage] = j
                slots[p, t, stage] = (
                    units * side * (entry - fill),
                    units * fill / 100,
                    risk,
                    op_return[j],
                    float(roll[j] - roll[0]),
                    units * (spread[j] + slip),
                )
        idx[1000, t, 0] = 0
        slots[1000, t, 0] = [
            0.0,
            units * entry / 100,
            units * (distance + slip),
            op_return[0],
            0.0,
            units * (spread[0] + slip),
        ]
        if t % 200 == 0:
            print("CACHE_FILL_PLANS", symbol, t, nt, flush=True)
    return (
        geom,
        info,
        lengths,
        returns,
        idx,
        slots,
        sizes,
        np.asarray(SIZERS, float),
    ), proof


def metric(row):
    return {
        "ending_balance_usd": float(row[0]),
        "profit_factor": float(row[1]),
        "max_dd_m1_percent": float(row[2]),
        "max_dd_closed_percent": float(row[3]),
        "trades": int(row[4]),
        "win_rate": float(row[5] / row[4]) if row[4] else 0,
        "children": int(row[6]),
        "baskets_with_adds": int(row[7]),
        "max_planned_risk_percent": float(row[8]),
        "max_margin_percent": float(row[9]),
        "long": int(row[10]),
        "short": int(row[11]),
        "train_2016_2024_balance": float(row[12]),
        "train_dd_percent": float(row[13]),
        "train_pf": float(row[14]),
        "train_trades": int(row[15]),
    }


def run(args):
    set_num_threads(8)
    inputs, proof = build(args.data, args.symbol, args.cache)
    base, annual = replay_batch(
        np.array([BASELINE_ID]), *inputs, args.symbol == "XAUUSD", START, END
    )
    print("BASELINE", args.symbol, metric(base[0]), flush=True)
    expected = (
        (11106.236716427939, 1.8919020427939148, 45.56637028644209, 560)
        if args.symbol == "XAUUSD"
        else (11820.225714285078, 2.2111414005448498, 37.0772072, 204)
    )
    np.testing.assert_allclose(base[0, [0, 1, 2, 4]], expected, rtol=1e-7, atol=1e-6)
    started = time.monotonic()
    rows = []
    years = []
    for start in range(0, N_CONFIGS, 1000):
        ids = np.arange(start, min(start + 1000, N_CONFIGS))
        values, y = replay_batch(ids, *inputs, args.symbol == "XAUUSD", START, END)
        rows.append(values)
        years.append(y)
        if start % 5000 == 0:
            print(
                "PROGRESS",
                args.symbol,
                start + len(ids),
                "of",
                N_CONFIGS,
                "seconds",
                round(time.monotonic() - started, 1),
                flush=True,
            )
    matrix = np.concatenate(rows)
    yearly = np.concatenate(years)
    np.savez_compressed(
        args.output.with_suffix(".npz"),
        metrics=matrix,
        annual_prefix=yearly,
        baseline=base,
        baseline_annual=annual,
    )
    mask = (
        (matrix[:, 12] > base[0, 12])
        & (matrix[:, 13] < base[0, 13])
        & (matrix[:, 14] >= base[0, 14] * 0.95)
        & (matrix[:, 15] >= base[0, 15] * 0.75)
    )
    ids = np.flatnonzero(mask)
    # Train-only Pareto; never select by full ending balance.
    order = ids[np.lexsort((-matrix[ids, 12], matrix[ids, 13]))]
    shortlist = []
    seen = set()
    for i in order:
        signature = tuple(np.round(yearly[i, :9].ravel(), 8))
        if signature in seen:
            continue
        seen.add(signature)
        shortlist.append(int(i))
        if len(shortlist) >= 50:
            break
    simultaneous = np.flatnonzero(
        (matrix[:, 0] > base[0, 0]) & (matrix[:, 2] < base[0, 2])
    )
    result = {
        "symbol": args.symbol,
        "configurations_tested": N_CONFIGS,
        "period": ["2016-01-01", "2025-12-31"],
        "baseline": metric(base[0]),
        "source_files": proof,
        "production_status": "RESEARCH_ONLY",
        "selection": "TRAIN 2016–2024 lower M1 DD + higher balance, PF>=95% and trades>=75%; train DD then train balance, dedup identical annual prefix metrics",
        "train_qualifying_parameter_sets": int(mask.sum()),
        "full_sample_joint_improvement_parameter_sets": len(simultaneous),
        "shortlist": [
            {"configuration": configuration(i), "metrics": metric(matrix[i])}
            for i in shortlist
        ],
        "full_sample_best_joint_diagnostic": None,
        "walk_forward": [],
        "oos_2025": [],
        "elapsed_grid_seconds": time.monotonic() - started,
        "limitations": [
            "History already observed; 2025 is retrospective temporal validation, not blinded fresh OOS",
            "Synthetic frozen spreads, slippage, carry and reference leverage; no historical broker ASK",
            "Limit one stage attempt per fresh reversal, including zero-size attempts",
            "EUR aggregate floating-equity OHLC bound; XAU frozen adverse-then-close marker",
            "Risk degear changes basket budget downward only; never widens frozen risk/margin/SL/TP",
        ],
    }
    if len(simultaneous):
        i = int(simultaneous[np.argmax(matrix[simultaneous, 0])])
        result["full_sample_best_joint_diagnostic"] = {
            "configuration": configuration(i),
            "metrics": metric(matrix[i]),
            "scope": "POSTHOC_DIAGNOSTIC_NOT_MODEL_SELECTION",
        }
    # Every WF configuration is picked from that year's train prefix only.
    for year in range(2019, 2026):
        k = year - 2017
        train = yearly[:, k]
        b = annual[0, k]
        pf = np.divide(
            train[:, 2], train[:, 3], out=np.zeros(len(train)), where=train[:, 3] > 0
        )
        good = (
            (train[:, 0] > b[0])
            & (train[:, 1] < b[1])
            & (pf >= 0.95 * b[2] / b[3])
            & (train[:, 4] >= 0.75 * b[4])
        )
        ix = np.flatnonzero(good)
        chosen = (
            int(ix[np.lexsort((-train[ix, 0], train[ix, 1]))][0])
            if len(ix)
            else BASELINE_ID
        )
        cut = pd.Timestamp(f"{year}-01-01", tz="UTC").value
        end = pd.Timestamp(f"{year + 1}-01-01", tz="UTC").value
        pair, _ = replay_batch(
            np.array([chosen, BASELINE_ID]),
            *inputs,
            args.symbol == "XAUUSD",
            cut,
            end,
            float(b[0]),
        )
        result["walk_forward"].append(
            {
                "test_year": year,
                "configuration": configuration(chosen),
                "common_initial_balance_usd": float(b[0]),
                "candidate": metric(pair[0]),
                "baseline": metric(pair[1]),
            }
        )
    common = annual[0, 8, 0]
    for i in shortlist:
        values, _ = replay_batch(
            np.array([i, BASELINE_ID]),
            *inputs,
            args.symbol == "XAUUSD",
            pd.Timestamp("2025-01-01", tz="UTC").value,
            END,
            float(common),
        )
        result["oos_2025"].append(
            {
                "configuration": configuration(i),
                "common_initial_balance_usd": float(common),
                "candidate": metric(values[0]),
                "baseline": metric(values[1]),
            }
        )
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False))
    cp = args.cache / f"{args.symbol}_compiled_inputs.pkl"
    cp.write_bytes(pickle.dumps(inputs, protocol=5))
    print(
        "DONE",
        args.symbol,
        "train qualifying",
        mask.sum(),
        "joint full",
        len(simultaneous),
        "seconds",
        round(time.monotonic() - started, 1),
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", choices=("XAUUSD", "EURUSD"), required=True)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    run(args)
