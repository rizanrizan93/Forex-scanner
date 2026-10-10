"""Predeclared staged-layer experiment; no production settings are written."""

import argparse
import hashlib
import json
import pickle
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from fx_scanner.cross_asset_replay import replay_account
from fx_scanner.distributed_layer_replay import (
    VARIANTS,
    account,
    load_raw,
    opportunities,
    prepare_traces,
    reversal_features,
)


def trade_stats(trades):
    balance = peak = 100.0
    dd = 0.0
    for t in trades:
        for low, high in t["path"]:
            if t.get("marking") != "ADVERSE_THEN_CLOSE":
                peak = max(peak, balance + high)
            dd = max(dd, (peak - balance - low) / peak)
            peak = max(peak, balance + high)
        balance += t["pnl"]
        peak = max(peak, balance)
        dd = max(dd, (peak - balance) / peak)
    gains = sum(max(t["pnl"], 0) for t in trades)
    loss = -sum(min(t["pnl"], 0) for t in trades)
    return {
        "trades": len(trades),
        "profit_factor": gains / loss if loss else None,
        "dd_percent": dd * 100,
        "ending_balance_usd": balance,
        "expectancy_r": float(np.mean([t["net_r"] for t in trades]))
        if trades
        else None,
    }


def select(results, baseline, minimum=30):
    eligible = [
        r
        for r in results
        if r["stats"]["trades"] >= minimum
        and r["stats"]["profit_factor"] is not None
        and baseline["profit_factor"] is not None
        and r["stats"]["profit_factor"] >= baseline["profit_factor"] * 0.95
        and r["stats"]["expectancy_r"] >= baseline["expectancy_r"] * 0.95
        and r["stats"]["trades"] >= baseline["trades"] * 0.75
    ]
    return (
        min(
            eligible,
            key=lambda r: (r["stats"]["dd_percent"], -r["stats"]["profit_factor"]),
        )["name"]
        if eligible
        else "BASELINE"
    )


def bootstrap_and_ordering(trades, seed=30903):
    rng = np.random.default_rng(seed)
    if len(trades) < 20:
        return {"status": "INSUFFICIENT_TRADES"}
    r = np.array([t["net_r"] for t in trades])
    means = []
    # Consecutive trade blocks, not independent IID trade bootstrap.
    for _ in range(500):
        indices = np.concatenate(
            [
                (np.arange(s, s + 5) % len(r))
                for s in rng.integers(len(r), size=(len(r) + 4) // 5)
            ]
        )[: len(r)]
        means.append(float(r[indices].mean()))
    balance = 100.0
    returns = []
    for t in trades:
        returns.append(t["pnl"] / balance)
        balance += t["pnl"]
    dds = []
    for _ in range(500):
        curve = 100 * np.cumprod(1 + rng.permutation(returns))
        peak = np.maximum.accumulate(np.r_[100, curve])[1:]
        dds.append(float(np.max((peak - curve) / peak) * 100))
    return {
        "expectancy_block_bootstrap_ci95": np.quantile(means, [0.025, 0.975]).tolist(),
        "monte_carlo_realized_return_order_dd_percentiles": np.quantile(
            dds, [0.5, 0.95, 0.99]
        ).tolist(),
        "ordering_scope": "FIXED_HISTORICAL_PERCENT_RETURN_SURROGATE_NOT_FULL_RESIZING",
        "draws": 500,
    }


def run(symbol, data, output, cache):
    cache.mkdir(parents=True, exist_ok=True)
    source = [
        {"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted(
            data.glob(symbol + "_*.parquet")
            if symbol == "EURUSD"
            else list((data / "data").glob("*.csv")) + list(data.glob("g-*.npz"))
        )
    ]
    from fx_scanner import distributed_layer_replay, frozen_xau_layer_inputs

    implementation = [
        Path(distributed_layer_replay.__file__),
        Path(frozen_xau_layer_inputs.__file__),
    ]
    implementation_sha = hashlib.sha256(
        b"".join(p.read_bytes() for p in implementation)
    ).hexdigest()
    fingerprint = hashlib.sha256(
        (json.dumps(source, sort_keys=True) + implementation_sha).encode()
    ).hexdigest()
    cp = cache / f"{symbol}_{fingerprint}.pkl"
    if cp.exists():
        records, traces = pickle.loads(
            cp.read_bytes()
        )  # exclusively our generated cache
    else:
        print("LOAD", symbol, flush=True)
        if symbol == "XAUUSD":
            from fx_scanner.frozen_xau_layer_inputs import load_frozen

            raw, records = load_frozen(data)
        else:
            raw = load_raw(data, symbol)
            records = opportunities(raw, symbol)
        print("REVERSAL_FEATURES", symbol, "opportunities", len(records), flush=True)
        traces = prepare_traces(raw, records, reversal_features(raw, symbol))
        cp.write_bytes(pickle.dumps((records, traces), protocol=5))
        del raw
    start, end = (
        pd.Timestamp("2016-01-01", tz="UTC"),
        pd.Timestamp("2026-01-01", tz="UTC"),
    )
    report = {
        "symbol": symbol,
        "implementation_sha256": implementation_sha,
        "period": ["2016-01-01", "2025-12-31"],
        "source_files": source,
        "scope": "FROZEN_EUR_VIRTUAL_SIGNALS_NEW_LAYER_BASKETS"
        if symbol == "EURUSD"
        else "FROZEN_XAU_ARCHIVED_SIGNALS_MACRO_NEWS_COSTS",
        "production_status": "RESEARCH_ONLY",
        "execution_authority": False,
        "selection_rule": "TRAIN_ONLY lowest DD with PF/expectancy >=95% baseline, count>=75% baseline and>=30; otherwise baseline",
        "reversal": "Completed M15 + M5 prior-candle break in trade direction and allowed H1 bias; actual next known M1 open, not historic trough",
        "basket_controls": "Initial absolute SL/TP unchanged; split variants reserve baseline planned USD risk; FULL_INITIAL variants reserve frozen maximum basket risk fraction at start, allowing use of previously unused risk; floating equity margin check; native minimum size; no profit recycling",
        "costs": {
            "spread": 0.00012
            if symbol == "EURUSD"
            else "ARCHIVED_CAUSAL_VARIABLE_0.25_0.35_0.40_PLUS_SHOCK_NEWS",
            "slip_per_side": 0.00001 if symbol == "EURUSD" else 0.05,
            "reference_leverage": 100,
            "source": "FROZEN_SYNTHETIC_COSTS_NOT_MEASURED_BROKER_HISTORY",
        },
        "variants": [],
        "walk_forward": [],
        "stress": [],
        "limitations": [
            "No broker historical ASK, variable margin/leverage, liquidity, swaps or exact tick path",
            "EUR DD is OHLC high-before-low bound; XAU preserves frozen adverse-then-close marker; neither is exact tick DD",
            "XAU preserves archived daily macro and full planned-hold news gate; final revised daily yields are not vintage data",
            "Frozen baseline was previously optimized 2016–2025: layering holdout is not independent OOS validation of baseline",
            "Fixed 4 depth stages are predefined; intervals .15/.25/.30R and linear/quadratic size are parameter experiments, not production settings",
            "Virtual opportunity cursor and EUR outcome feedback stay frozen; stress execution may skip overlapping opportunities",
            "Extra children override XAU desired balance-step count only inside research; same planned dollar risk and margin remain bounded",
        ],
    }
    results = {}
    for v in VARIANTS:
        print("SIMULATE", symbol, v.name, flush=True)
        summary, trades = account(records, traces, symbol, v, start, end)
        annual = []
        for year in range(2016, 2026):
            year_summary, _ = account(
                records,
                traces,
                symbol,
                v,
                pd.Timestamp(f"{year}-01-01", tz="UTC"),
                pd.Timestamp(f"{year + 1}-01-01", tz="UTC"),
            )
            annual.append({"year": year, "reset_100": year_summary})
        summary["annual"] = annual
        summary["train_2016_2024"] = trade_stats(
            [t for t in trades if t["at"].year < 2025]
        )
        report["variants"].append(summary)
        results[v.name] = (summary, trades)
        output.write_text(json.dumps(report, indent=2, allow_nan=False, default=str))
    for year in range(2019, 2026):
        baseline = trade_stats(
            [t for t in results["BASELINE"][1] if t["at"].year < year]
        )
        candidates = [
            {
                "name": v.name,
                "stats": trade_stats(
                    [t for t in results[v.name][1] if t["at"].year < year]
                ),
            }
            for v in VARIANTS
        ]
        name = select(candidates, baseline)
        common_cash = baseline["ending_balance_usd"]
        fold_start, fold_end = (
            pd.Timestamp(f"{year}-01-01", tz="UTC"),
            pd.Timestamp(f"{year + 1}-01-01", tz="UTC"),
        )
        chosen_variant = next(v for v in VARIANTS if v.name == name)
        selected, _ = account(
            records,
            traces,
            symbol,
            chosen_variant,
            fold_start,
            fold_end,
            initial_balance=common_cash,
        )
        base, _ = account(
            records,
            traces,
            symbol,
            VARIANTS[0],
            fold_start,
            fold_end,
            initial_balance=common_cash,
        )
        report["walk_forward"].append(
            {
                "initial_balance_common_usd": common_cash,
                "train_end": year - 1,
                "test_year": year,
                "selected": name,
                "validation": selected,
                "baseline": base,
            }
        )
    chosen = report["walk_forward"][-1]["selected"]
    report["selected_train_only_for_2025"] = chosen
    report["bootstrap_and_ordering"] = bootstrap_and_ordering(results[chosen][1])
    target = next(v for v in VARIANTS if v.name == chosen)
    for name, v, sf, lf in [
        ("COST_X1_5", target, 1.5, 1.5),
        ("COST_X2", target, 2.0, 2.0),
        ("COST_X3", target, 3.0, 3.0),
        ("CONFIRM_DELAY_1M", replace(target, delay_minutes=1), 1.0, 1.0),
        ("CONFIRM_DELAY_5M", replace(target, delay_minutes=5), 1.0, 1.0),
        ("CONFIRM_DELAY_10M", replace(target, delay_minutes=10), 1.0, 1.0),
    ]:
        print("STRESS", symbol, name, flush=True)
        value, _ = account(
            records, traces, symbol, v, start, end, spread_factor=sf, slip_factor=lf
        )
        base, _ = account(
            records,
            traces,
            symbol,
            VARIANTS[0],
            start,
            end,
            spread_factor=sf,
            slip_factor=lf,
        )
        report["stress"].append({"name": name, "candidate": value, "baseline": base})
    # Separate user-requested confirmed deeper-more variant even if rejected by train selector.
    probe = next(v for v in VARIANTS if v.name == "CONFIRMED_MORE_0.25")
    report["requested_variant_bootstrap"] = bootstrap_and_ordering(
        results[probe.name][1]
    )
    for sf in (1.5, 2.0, 3.0):
        value, _ = account(
            records, traces, symbol, probe, start, end, spread_factor=sf, slip_factor=sf
        )
        base, _ = account(
            records,
            traces,
            symbol,
            VARIANTS[0],
            start,
            end,
            spread_factor=sf,
            slip_factor=sf,
        )
        report["stress"].append(
            {
                "name": f"REQUESTED_DEEP_MORE_COST_X{sf}",
                "candidate": value,
                "baseline": base,
            }
        )
    for minutes in (1, 5, 10):
        value, _ = account(
            records, traces, symbol, replace(probe, delay_minutes=minutes), start, end
        )
        report["stress"].append(
            {
                "name": f"REQUESTED_CONFIRM_DELAY_{minutes}M",
                "candidate": value,
                "baseline": results["BASELINE"][0],
            }
        )
    rng = np.random.default_rng(30903)
    kept = rng.random(len(records)) >= 0.10
    reduced_records = [t for t, keep in zip(records, kept) if keep]
    reduced_traces = [t for t, keep in zip(traces, kept) if keep]
    missing_quotes = []
    for trace in traces:
        mask = rng.random(len(trace)) >= 0.01
        mask[0] = mask[-1] = True
        missing_quotes.append(trace.iloc[mask])
    for label, rs, xs in [
        ("RANDOM_OPPORTUNITY_REMOVAL_10PCT", reduced_records, reduced_traces),
        ("MISSING_EXECUTION_QUOTES_1PCT", records, missing_quotes),
    ]:
        value, _ = account(rs, xs, symbol, probe, start, end)
        base, _ = account(rs, xs, symbol, VARIANTS[0], start, end)
        report["stress"].append(
            {
                "name": label,
                "candidate": value,
                "baseline": base,
                "scope": "Frozen signals/confirmations retained; perturbation of opportunities or execution quotes only",
            }
        )
    full_probe = next(v for v in VARIANTS if v.name == "FULL_INITIAL_CONFIRMED_1_0.25")
    report["full_initial_requested_bootstrap"] = bootstrap_and_ordering(
        results[full_probe.name][1]
    )
    for label, v, sf, lf in [
        ("FULL_INITIAL_COST_X1_5", full_probe, 1.5, 1.5),
        ("FULL_INITIAL_COST_X2", full_probe, 2.0, 2.0),
        ("FULL_INITIAL_COST_X3", full_probe, 3.0, 3.0),
        ("FULL_INITIAL_DELAY_1M", replace(full_probe, delay_minutes=1), 1.0, 1.0),
        ("FULL_INITIAL_DELAY_5M", replace(full_probe, delay_minutes=5), 1.0, 1.0),
        ("FULL_INITIAL_DELAY_10M", replace(full_probe, delay_minutes=10), 1.0, 1.0),
    ]:
        value, _ = account(
            records, traces, symbol, v, start, end, spread_factor=sf, slip_factor=lf
        )
        base, _ = account(
            records,
            traces,
            symbol,
            VARIANTS[0],
            start,
            end,
            spread_factor=sf,
            slip_factor=lf,
        )
        report["stress"].append({"name": label, "candidate": value, "baseline": base})
    report["trade_audit_full_initial"] = [
        {k: v for k, v in t.items() if k != "path"} for t in results[full_probe.name][1]
    ]
    if symbol == "XAUUSD":
        z = np.load(data / "hybrid-audit-0-1.npz", allow_pickle=False)
        st = z["state"]
        ref = {
            "balance": float(st[0]),
            "trades": int(st[4]),
            "pf": float(st[5] / st[6]),
            "dd": float(st[23] * 100),
        }
        b = results["BASELINE"][0]
        np.testing.assert_allclose(
            [
                b["ending_balance_usd"],
                b["trades"],
                b["profit_factor"],
                b["max_dd_equity_m1_bound_percent"],
            ],
            list(ref.values()),
            atol=1e-6,
            rtol=1e-9,
        )
        report["frozen_reference"] = ref
    if symbol == "EURUSD":
        # Independent frozen reference uses its original DD estimator.
        raw = load_raw(data, symbol)
        frozen = eurusd_reference(raw, start, end)
        b = results["BASELINE"][0]
        for key in ("ending_balance_usd", "trades", "profit_factor"):
            np.testing.assert_allclose(b[key], frozen[key], atol=1e-7, rtol=1e-9)
        report["frozen_reference"] = frozen
    report["trade_audit_requested"] = [
        {k: v for k, v in t.items() if k != "path"} for t in results[probe.name][1]
    ]
    output.write_text(json.dumps(report, indent=2, allow_nan=False, default=str))
    print("DONE", symbol, "selected", chosen, flush=True)


def eurusd_reference(raw, start, end):
    from fx_scanner.cross_asset_replay import eurusd_virtual_trades

    return replay_account(eurusd_virtual_trades(raw), start=start, end=end)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--symbol", choices=["EURUSD", "XAUUSD"], required=True)
    args = p.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    run(args.symbol, args.data, args.output, args.cache)
