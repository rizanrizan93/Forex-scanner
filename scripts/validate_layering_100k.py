"""Independent position-by-position scalar check and pre-fixed robustness."""

import argparse
import json
import math
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from numba import set_num_threads
from research_layering_100k import END, START, build, metric

from fx_scanner.layering_grid import BASELINE_ID, configuration, replay_batch


def scalar(inputs, identifier, xau):
    geom, info, lengths, path, idx, slots, sizes, policies = inputs
    p = 1000 if identifier == BASELINE_ID else identifier // 100
    if identifier == BASELINE_ID:
        share, power, mode, throttle = 1.0, 0.0, 0.0, False
    else:
        share, power, mode, throttle = policies[identifier % 100]
    cash = peak = closed_peak = 100.0
    dd = cdd = gains = losses = 0.0
    ledger = []
    maxrisk = maxmargin = 0.0
    cursor = START - 1
    daycounts = {}
    n = int(sizes[p, 0])
    weights = [(k + 1) ** power for k in range(1, n)]
    for t, row in enumerate(geom):
        at, ex, day, _ = info[t]
        if (
            at < START
            or at >= END
            or at <= cursor
            or cash <= 0
            or (xau and daycounts.get(day, 0) >= 6)
        ):
            continue
        _, distance, slip, units, scale, exitreturn, margin, fee = row
        risk = units * (distance + slip)
        riskcap = (0.125 if xau else 0.2725) * scale
        mc = (0.5 if xau else 0.6) * scale
        cap = 2**31 - 1 if xau else math.floor(195 * (cash / 100) ** 0.0625)
        if xau:
            count = min(
                max(1, math.floor(cash / 100)),
                math.floor(riskcap * cash / risk),
                math.floor(mc * cash / margin),
                math.floor(cash / (margin + fee)),
            )
        else:
            count = math.floor(
                min(
                    195 * (cash / 100) ** 0.0625,
                    riskcap * cash / risk,
                    mc * cash / margin,
                )
                + 1e-9
            )
        degear = 0.5 if throttle and (closed_peak - cash) / closed_peak >= 0.10 else 1.0
        budget = (riskcap * cash if mode else count * risk) * degear
        initial = min(
            max(1, math.floor(count * share * degear)), math.floor(budget / risk + 1e-9)
        )
        if count < 1 or initial < 1:
            continue
        reserved = max(0.0, budget - initial * risk)
        holds = []
        usedrisk = usedmargin = 0.0
        for k in range(n):
            j = int(idx[p, t, k])
            if j < 0:
                continue
            delta, margin, risk, op, credit, fee = slots[p, t, k]
            allocation = (
                initial * risk if k == 0 else reserved * weights[k - 1] / sum(weights)
            )
            wanted = initial if k == 0 else math.floor(allocation / risk + 1e-9)
            floating = sum(q * (op + d) for _, q, d in holds)
            mb = mc * max(0.0, min(cash, cash + floating))
            q = min(
                wanted,
                math.floor(max(0.0, budget - usedrisk) / risk + 1e-9),
                math.floor(max(0.0, mb - usedmargin) / margin + 1e-9),
                cap - sum(q for _, q, _ in holds),
            )
            if xau:
                q = min(
                    q,
                    math.floor(max(0.0, cash + floating - usedmargin) / (margin + fee)),
                )
            if q < 1:
                continue
            holds.append((k, q, delta + credit))
            usedrisk += q * risk
            usedmargin += q * margin
        if not holds:
            continue
        for j in range(lengths[t]):
            active = [(k, q, d) for k, q, d in holds if idx[p, t, k] <= j]
            low = sum(q * (path[t, j, 0] + d) for k, q, d in active)
            high = sum(
                q
                * (
                    (
                        path[t, j, 2]
                        if k > 0 and idx[p, t, k] == j and not sizes[p, 1]
                        else path[t, j, 1]
                    )
                    + d
                )
                for k, q, d in active
            )
            if not xau:
                peak = max(peak, cash + high)
            dd = max(dd, (peak - cash - low) / peak)
            peak = max(peak, cash + high)
        pnl = sum(q * (exitreturn + d) for _, q, d in holds)
        ledger.append(
            {
                "at_ns": int(at),
                "pnl": float(pnl),
                "before": cash,
                "return": float(pnl / cash),
                "children": sum(q for _, q, _ in holds),
                "adds": sum(k > 0 for k, _, _ in holds),
                "direction": int(path[t, 0, 3]),
            }
        )
        maxrisk = max(maxrisk, usedrisk / cash)
        maxmargin = max(maxmargin, usedmargin / cash)
        cash += pnl
        gains += max(pnl, 0)
        losses += max(-pnl, 0)
        cursor = ex
        daycounts[day] = daycounts.get(day, 0) + 1
        peak = max(peak, cash)
        dd = max(dd, (peak - cash) / peak)
        closed_peak = max(closed_peak, cash)
        cdd = max(cdd, (closed_peak - cash) / closed_peak)
    metrics = np.array(
        [
            cash,
            gains / losses if losses else 0,
            dd * 100,
            cdd * 100,
            len(ledger),
            sum(t["pnl"] > 0 for t in ledger),
            sum(t["children"] for t in ledger),
            sum(t["adds"] > 0 for t in ledger),
            maxrisk * 100,
            maxmargin * 100,
            sum(t["direction"] == 1 for t in ledger),
            sum(t["direction"] == -1 for t in ledger),
        ]
    )
    return metrics, ledger


def inference(candidate, baseline):
    a = {t["at_ns"]: t["return"] for t in candidate}
    b = {t["at_ns"]: t["return"] for t in baseline}
    keys = sorted(set(a) & set(b))
    d = np.array([a[k] - b[k] for k in keys])
    rng = np.random.default_rng(100001)
    means = []
    for _ in range(500):
        ix = np.concatenate(
            [
                (np.arange(s, s + 5) % len(d))
                for s in rng.integers(len(d), size=(len(d) + 4) // 5)
            ]
        )[: len(d)]
        means.append(float(d[ix].mean()))
    mc = []
    for _ in range(500):
        order = rng.permutation(len(keys))
        ca = 100 * np.cumprod(1 + np.array([a[k] for k in keys])[order])
        cb = 100 * np.cumprod(1 + np.array([b[k] for k in keys])[order])
        pa = np.maximum.accumulate(np.r_[100.0, ca])[1:]
        pb = np.maximum.accumulate(np.r_[100.0, cb])[1:]
        mc.append([100 * np.max((pa - ca) / pa), 100 * np.max((pb - cb) / pb)])
    return {
        "matched_setup_count": len(d),
        "monte_carlo_candidate_baseline_dd_p50_p95_p99": np.quantile(
            mc, [0.5, 0.95, 0.99], axis=0
        ).tolist(),
        "monte_carlo_scope": "Paired permutation of fixed historical percentage returns; not a full native-child resizing replay",
        "paired_percent_return_difference_ci95": (
            100 * np.quantile(means, [0.025, 0.975])
        ).tolist(),
        "method": "500 bootstrap draws of 5-trade blocks; historical matched returns; exploratory, no multiple-testing-adjusted significance claim",
    }


def run(args):
    set_num_threads(8)
    report = json.loads(args.result.read_text())
    inputs = pickle.loads(
        (args.cache / f"{args.symbol}_compiled_inputs.pkl").read_bytes()
    )
    xau = args.symbol == "XAUUSD"
    diagnostic = report["full_sample_best_joint_diagnostic"]["configuration"]["id"]
    train = (
        report["shortlist"][0]["configuration"]["id"]
        if report["shortlist"]
        else BASELINE_ID
    )
    ids = np.array(sorted({BASELINE_ID, diagnostic, train, 0, 99999}))
    compiled, _ = replay_batch(ids, *inputs, xau, START, END)
    ledgers = {}
    for i, row in zip(ids, compiled):
        independent, ledger = scalar(inputs, int(i), xau)
        np.testing.assert_allclose(independent, row[:12], atol=1e-6, rtol=1e-9)
        ledgers[int(i)] = ledger
        print("SCALAR_MATCH", args.symbol, int(i), flush=True)
    evidence = {
        "scalar_checks": [int(i) for i in ids],
        "bootstrap_diagnostic": inference(ledgers[diagnostic], ledgers[BASELINE_ID]),
        "diagnostic_ledger": ledgers[diagnostic],
        "stress": [],
    }
    tested = np.array(sorted({BASELINE_ID, diagnostic, train}))
    patterns = sorted({int(i) // 100 for i in tested if i != BASELINE_ID})
    for label, sf, delay, missing in [
        ("COST_X1_5", 1.5, 0, 0),
        ("COST_X2", 2.0, 0, 0),
        ("COST_X3", 3.0, 0, 0),
        ("CONFIRM_DELAY_1M", 1.0, 1, 0),
        ("CONFIRM_DELAY_5M", 1.0, 5, 0),
        ("CONFIRM_DELAY_10M", 1.0, 10, 0),
        ("EXECUTION_QUOTE_DROP_1PCT", 1.0, 0, 0.01),
    ]:
        print("STRESS_BUILD", args.symbol, label, flush=True)
        changed, _ = build(
            args.data,
            args.symbol,
            args.cache,
            spread_factor=sf,
            slip_factor=sf,
            confirm_delay_minutes=delay,
            pattern_ids=patterns,
            execution_quote_drop=missing,
        )
        out, _ = replay_batch(tested, *changed, xau, START, END)
        evidence["stress"].append(
            {
                "name": label,
                "configurations": [
                    {"configuration": configuration(int(i)), "metrics": metric(r)}
                    for i, r in zip(tested, out)
                ],
            }
        )
    rng = np.random.default_rng(100001)
    keep = rng.random(len(inputs[0])) >= 0.10
    g, info, l, ret, idx, slots, sizes, policies = inputs
    removed = (
        g[keep],
        info[keep],
        l[keep],
        ret[keep],
        idx[:, keep],
        slots[:, keep],
        sizes,
        policies,
    )
    out, _ = replay_batch(tested, *removed, xau, START, END)
    evidence["stress"].append(
        {
            "name": "OPPORTUNITY_DROP_10PCT",
            "configurations": [
                {"configuration": configuration(int(i)), "metrics": metric(r)}
                for i, r in zip(tested, out)
            ],
        }
    )
    common = report["walk_forward"][-1]["common_initial_balance_usd"]
    vals, _ = replay_batch(
        tested,
        *inputs,
        xau,
        pd.Timestamp("2025-01-01", tz="UTC").value,
        END,
        float(common),
    )
    evidence["diagnostic_2025_common_cash"] = [
        {"configuration": configuration(int(i)), "metrics": metric(r)}
        for i, r in zip(tested, vals)
    ]
    evidence["common_initial_balance_2025"] = common
    matrix = np.load(args.result.with_suffix(".npz"), allow_pickle=False)["metrics"]
    config = configuration(diagnostic)
    neighbors = []
    for change in (-10000, 10000, -2000, 2000, -100, 100, -20, 20, -4, 4):
        neighbor = diagnostic + change
        if not 0 <= neighbor < 100000:
            continue
        candidate = configuration(neighbor)
        if sum(candidate[k] != value for k, value in config.items() if k != "id") != 1:
            continue
        neighbors.append(
            {
                "configuration": candidate,
                "ending_balance_usd": float(matrix[neighbor, 0]),
                "max_dd_m1_percent": float(matrix[neighbor, 2]),
                "scope": "One parameter dimension changed; descriptive perturbation, not new model selection",
            }
        )
    evidence["parameter_neighbors"] = neighbors
    args.output.write_text(json.dumps(evidence, indent=2, allow_nan=False))
    print("VALIDATION_DONE", args.symbol, flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", required=True)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--result", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args())
