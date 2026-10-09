"""Reproducible exploratory lead–lag evaluation; never promotes a model.

Optional scipy/statsmodels methods are recorded unavailable, not silently passed.
Whole last calendar year is untouched OOS. Earlier years form expanding folds.
Candidate selection uses training only; validation/OOS cannot choose parameters.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .cross_asset_lead_lag import (
    HORIZONS,
    INSTRUMENTS,
    LAGS,
    MODEL_VERSION,
    completed_close,
    conditional_stats,
    event_windows,
    fdr_bh,
    paired_returns,
    regimes,
    return_features,
    sessions,
    synchronize,
)


def correlation(frame, method="pearson"):
    f = frame[["x", "y"]].dropna()
    if len(f) < 100 or f.x.std() == 0 or f.y.std() == 0:
        return None
    return float(f.x.corr(f.y, method=method))


def residuals(frame):
    """Incremental predictive information beyond known target momentum."""
    f = frame.dropna(subset=["x", "y", "target_now", "target_prev"])
    if len(f) < 100:
        return pd.DataFrame(columns=["x", "y"])
    controls = np.column_stack([np.ones(len(f)), f.target_now, f.target_prev])
    values = f[["x", "y"]].to_numpy()
    result = values - controls @ np.linalg.lstsq(controls, values, rcond=None)[0]
    return pd.DataFrame(result, columns=["x", "y"], index=f.index)


def block_null_p(frame, repeats=199, seed=981):
    """Daily sign-flip wild null keeps within-day autocorrelation structure."""
    f = frame[["x", "y"]].dropna()
    if len(f) < 100:
        return 1.0
    codes, days = pd.factorize(f.index.normalize())
    if len(days) < 20:
        return 1.0
    x = f.x.to_numpy() - f.x.mean()
    y = f.y.to_numpy() - f.y.mean()
    denom = np.sqrt(np.dot(x, x) * np.dot(y, y))
    if denom == 0:
        return 1.0
    daily_product = np.bincount(codes, weights=x * y)
    observed = abs(daily_product.sum())
    rng = np.random.default_rng(seed)
    nulls = np.abs(rng.choice([-1, 1], size=(repeats, len(days))) @ daily_product)
    return float((1 + np.sum(nulls >= observed)) / (1 + repeats))


def optional_methods(frame):
    f = frame.dropna(subset=["x", "y"]).copy()
    out = {"mutual_information": None, "granger_p": None, "adf_p": None}
    try:
        from sklearn.metrics import mutual_info_score

        # Fixed equal-frequency discretization; descriptive only, not alpha gate.
        x, y = (
            pd.qcut(f.x, 5, labels=False, duplicates="drop"),
            pd.qcut(f.y, 5, labels=False, duplicates="drop"),
        )
        out["mutual_information"] = float(mutual_info_score(x, y))
    except (ImportError, ValueError) as exc:
        out["mi_status"] = type(exc).__name__
    try:
        from statsmodels.tsa.stattools import adfuller, grangercausalitytests

        # Find a contiguous segment; never concatenate gaps/weekends for VAR.
        gaps = f.index.to_series().diff()
        step = gaps[gaps > pd.Timedelta(0)].min()
        chunks = (gaps != step).cumsum()
        largest = chunks.value_counts().idxmax()
        # VAR receives contemporaneous returns, not the future-shifted CCF
        # target; shifting y here would mislabel temporal causality.
        contiguous = (
            f.loc[chunks == largest, ["target_now", "x"]]
            .rename(columns={"target_now": "y"})
            .iloc[:2000]
        )
        if len(contiguous) < 120:
            raise ValueError("INSUFFICIENT_CONTIGUOUS_SEGMENT")
        out["adf_p"] = float(adfuller(contiguous.x, maxlag=5, autolag="AIC")[1])
        if out["adf_p"] >= 0.05:
            raise ValueError("NONSTATIONARY_RETURNS")
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            g = grangercausalitytests(contiguous, maxlag=[1, 2, 3])
        out["granger_p"] = {str(k): float(v[0]["ssr_ftest"][1]) for k, v in g.items()}
        out["granger_status"] = "DESCRIPTIVE_CONTIGUOUS_SEGMENT_NOT_CAUSAL_PROOF"
    except (ImportError, ValueError, np.linalg.LinAlgError) as exc:
        out["granger_status"] = str(exc)
    return out


def select_on_train(prices, leader, target, minutes, cutoff):
    grid = sorted(set(LAGS) | set(range(0, 31, minutes)))
    rows = []
    purge = pd.Timedelta(minutes=120 + minutes)
    # Reuse causal features across the lag grid, and never compute features
    # on the unseen suffix during parameter selection.
    training_prices = prices.loc[prices.index < cutoff, [leader, target]]
    prepared = return_features(training_prices, leader, target)
    n_train = training_prices.index.searchsorted(cutoff - purge)
    observation_stride = 15 if minutes == 1 else 1
    # M1 training: one seeded random minute per 15-minute block avoids a fixed
    # news-minute phase and reduces serial dependence. Feature calculations
    # retain every original M1 bar; validation/OOS retain all eligible events.
    locations = np.arange(0, n_train, observation_stride)
    if observation_stride > 1:
        locations += np.random.default_rng(7291).integers(
            0, observation_stride, len(locations)
        )
        locations = locations[locations < n_train]
    for lag in grid:
        if lag % minutes:
            continue
        f = paired_returns(
            training_prices, leader, target, minutes, lag, prepared=prepared
        )
        train = f.iloc[locations]
        c = correlation(train)
        partial = residuals(train)
        pc = correlation(partial)
        rows.append(
            {
                "lag_minutes": lag,
                "train_corr": c,
                "train_partial_corr": pc,
                "train_spearman": correlation(
                    train.iloc[:: max(1, len(train) // 50000)], "spearman"
                ),
                "spearman_thinning": max(1, len(train) // 50000),
                "training_observation_stride": observation_stride,
                "train_p": block_null_p(partial),
                "samples": len(train.dropna()),
            }
        )
    candidates = [
        r for r in rows if r["lag_minutes"] > 0 and r["train_partial_corr"] is not None
    ]
    if not candidates:
        return None, rows
    selected = max(candidates, key=lambda r: abs(r["train_partial_corr"]))
    selected = dict(
        selected, sign=1 if selected["train_partial_corr"] > 0 else -1, threshold=2.0
    )
    return selected, rows


def evaluate_fold(prices, leader, target, minutes, train_end, test_end):
    chosen, grid = select_on_train(prices, leader, target, minutes, train_end)
    if chosen is None:
        return {"status": "INSUFFICIENT_TRAIN_DATA", "grid": grid}
    lag = chosen["lag_minutes"]
    horizon = max(5, lag)
    f = paired_returns(prices, leader, target, minutes, lag)
    test = f.loc[
        (f.index >= train_end)
        & (f.index < test_end - pd.Timedelta(minutes=120 + minutes))
    ]
    conditional = paired_returns(prices, leader, target, minutes, lag, horizon)
    conditional = conditional.loc[test.index]
    rolling = test.x.rolling(96, min_periods=48).corr(test.y).dropna()
    result = {
        "status": "EVALUATED",
        "train_end": train_end.isoformat(),
        "test_end": test_end.isoformat(),
        "selection": chosen,
        "grid": grid,
        "test_corr": correlation(test),
        "test_partial_corr": correlation(residuals(test)),
        "test_spearman": correlation(test, "spearman"),
        "rolling_corr_quantiles": [float(x) for x in rolling.quantile([0.1, 0.5, 0.9])]
        if len(rolling)
        else [],
        "conditional": conditional_stats(conditional, chosen["sign"], 2.0, horizon),
        "horizons": {},
        "session": {},
        "regime": {},
        "event": {},
    }
    for h in HORIZONS:
        if h % minutes:
            continue
        p = paired_returns(prices, leader, target, minutes, lag, h).loc[test.index]
        result["horizons"][str(h)] = conditional_stats(p, chosen["sign"], 2.0, h)
        # Divergence: target's current direction is flat or opposes the driver.
        p = p.loc[chosen["sign"] * np.sign(p.x) * p.target_now <= 0]
        result["horizons"][str(h)]["divergence"] = conditional_stats(
            p, chosen["sign"], 2.0, h
        )
    labels = sessions(conditional.index)
    reg = regimes(prices[target]).reindex(conditional.index)
    for name in labels.unique():
        result["session"][name] = conditional_stats(
            conditional.loc[labels == name], chosen["sign"], 2.0, horizon
        )
    for field in ("trend", "volatility"):
        for name in reg[field].unique():
            result["regime"][name] = conditional_stats(
                conditional.loc[reg[field] == name], chosen["sign"], 2.0, horizon
            )
    return result


def research(
    series, *, events=None, minutes_grid=(1, 5, 15), targets=("XAUUSD", "EURUSD")
):
    report = {
        "model_version": MODEL_VERSION,
        "production_status": "RESEARCH_ONLY",
        "execution_authority": False,
        "candidates": [],
        "missing_datasets": {},
        "limitations": [
            "Public secondary quotes are not FP Markets fills; stale unchanged quotes may not be distinguishable from true flat prices.",
            "Session/regime subdivisions are descriptive, not independently optimized or promoted.",
            "Risk-on/off and high-yield volatility require synchronized equity/yield data.",
            "Joint leader probabilities and sequential US2Y→US10Y→DXY→EURUSD→XAU need joint calibration; marginal probabilities cannot be averaged.",
            "No automatic production promotion; paired baseline replay and execution stress gates are mandatory.",
        ],
    }
    if events is None:
        report["limitations"].append(
            "Historical point-in-time macro calendar absent: normal/event comparison unverified."
        )
    for target in targets:
        report["missing_datasets"][target] = [
            s for s in (target, *INSTRUMENTS[target]) if s not in series
        ]
    for minutes in minutes_grid:
        prices = synchronize(series, minutes)
        for target in targets:
            if target not in prices:
                continue
            counts = pd.Series(prices[target].dropna().index.year).value_counts()
            # A fixed-EST December 31 file can end after UTC January 1. That
            # spillover is not a new independent holdout year.
            years = sorted(int(y) for y, count in counts.items() if count >= 1000)
            if len(years) < 3:
                report["limitations"].append(
                    f"{target} M{minutes}: fewer than 3 calendar years; yearly walk-forward unavailable."
                )
                continue
            holdout_start = pd.Timestamp(f"{years[-1]}-01-01", tz="UTC")
            end = min(
                prices.index.max() + pd.Timedelta(minutes=minutes),
                pd.Timestamp(f"{years[-1] + 1}-01-01", tz="UTC"),
            )
            for leader in INSTRUMENTS[target]:
                if leader not in prices:
                    continue
                candidate = {
                    "target": target,
                    "leader": leader,
                    "timeframe_minutes": minutes,
                    "structural_correlation": leader == "DXY" and target == "EURUSD",
                    "walk_forward": [],
                    "rejection_reasons": [],
                    "approved": False,
                }
                for year in years[1:-1]:
                    start = pd.Timestamp(f"{year}-01-01", tz="UTC")
                    stop = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
                    candidate["walk_forward"].append(
                        evaluate_fold(prices, leader, target, minutes, start, stop)
                    )
                oos = evaluate_fold(prices, leader, target, minutes, holdout_start, end)
                candidate["oos"] = oos
                if oos["status"] != "EVALUATED":
                    candidate["rejection_reasons"].append("INSUFFICIENT_DATA")
                else:
                    chosen = oos["selection"]
                    candidate["optimal_lag_minutes"] = chosen["lag_minutes"]
                    f = paired_returns(
                        prices, leader, target, minutes, chosen["lag_minutes"]
                    )
                    test = f.loc[f.index >= holdout_start]
                    candidate["optional_methods"] = optional_methods(test)
                    lag_history = [
                        r["selection"]["lag_minutes"]
                        for r in candidate["walk_forward"]
                        if r.get("selection")
                    ]
                    candidate["lag_stability"] = {
                        "fold_lags": lag_history,
                        "oos_selected_lag": chosen["lag_minutes"],
                        "range_minutes": [min(lag_history), max(lag_history)]
                        if lag_history
                        else None,
                    }
                    conditions = oos["conditional"]
                    if conditions["events"] < 100:
                        candidate["rejection_reasons"].append(
                            "OOS_EVENT_COUNT_BELOW_100"
                        )
                    if conditions["ci_low"] is None or conditions["ci_low"] <= 0.5:
                        candidate["rejection_reasons"].append(
                            "OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT"
                        )
                    folds = [
                        r
                        for r in candidate["walk_forward"]
                        if r.get("status") == "EVALUATED"
                    ]
                    passed = [
                        r
                        for r in folds
                        if r["conditional"].get("ci_low") is not None
                        and r["conditional"]["ci_low"] > 0.5
                    ]
                    candidate["walk_forward_pass_fraction"] = (
                        len(passed) / len(folds) if folds else 0.0
                    )
                    if len(folds) < 2 or len(passed) / max(1, len(folds)) < 0.75:
                        candidate["rejection_reasons"].append("WALK_FORWARD_UNSTABLE")
                    if events is not None:
                        horizon = max(5, chosen["lag_minutes"])
                        ef = paired_returns(
                            prices,
                            leader,
                            target,
                            minutes,
                            chosen["lag_minutes"],
                            horizon,
                        ).loc[test.index]
                        es = event_windows(ef.index, events)
                        for event in es.unique():
                            oos["event"][event] = conditional_stats(
                                ef.loc[es == event], chosen["sign"], 2.0, horizon
                            )
                candidate["rejection_reasons"] += [
                    "BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED",
                    "BROKER_COST_ROBUSTNESS_NOT_VERIFIED",
                ]
                if events is None:
                    candidate["rejection_reasons"].append(
                        "HISTORICAL_EVENT_COVERAGE_MISSING"
                    )
                if candidate["structural_correlation"]:
                    candidate["rejection_reasons"].append(
                        "DXY_EURUSD_STRUCTURAL_DEPENDENCE_REQUIRES_INDEPENDENT_CONFIRMATION"
                    )
                report["candidates"].append(candidate)
    # Correct the training grid across ALL leaders, targets, TFs and folds.
    entries = []
    for c in report["candidates"]:
        for fold in [*c["walk_forward"], c["oos"]]:
            entries.extend(fold.get("grid", []))
    adjusted = fdr_bh([e["train_p"] for e in entries]) if entries else []
    for e, q in zip(entries, adjusted):
        e["train_q_global"] = float(q)
    for c in report["candidates"]:
        chosen = c["oos"].get("selection")
        grid = c["oos"].get("grid", [])
        if chosen:
            q = next(
                r["train_q_global"]
                for r in grid
                if r["lag_minutes"] == chosen["lag_minutes"]
            )
            c["train_q_global"] = q
            if q >= 0.05:
                c["rejection_reasons"].append("MULTIPLE_TESTING_FDR_FAILED")
    report["multiple_tests"] = len(entries)
    report["ranking"] = sorted(
        [
            {
                "leader": c["leader"],
                "target": c["target"],
                "timeframe_minutes": c["timeframe_minutes"],
                "lag_minutes": c.get("optimal_lag_minutes"),
                "oos": c["oos"].get("conditional"),
                "train_q_global": c.get("train_q_global"),
                "verdict": "RESEARCH_ONLY",
                "reasons": c["rejection_reasons"],
            }
            for c in report["candidates"]
        ],
        key=lambda r: (r.get("oos") or {}).get("ci_low") or -1,
        reverse=True,
    )
    return report


def load_directory(directory):
    """HistData source contract uses fixed EST (Etc/GMT+5), M1 open labels."""
    root = Path(directory)
    grouped = {}
    quality = []
    for path in sorted(root.glob("*.parquet")):
        symbol = path.stem.split("_")[0]
        frame = pd.read_parquet(path).rename(columns={"datetime": "timestamp"})
        values = completed_close(frame, source_timezone="Etc/GMT+5")
        grouped.setdefault(symbol, []).append(values)
        quality.append(
            {
                "file": path.name,
                "rows": len(frame),
                "symbol": symbol,
                "first_completed_utc": values.index.min().isoformat(),
                "last_completed_utc": values.index.max().isoformat(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "unchanged_quote_fraction": float((values.diff() == 0).mean()),
                "gaps_over_one_minute": int(
                    (values.index.to_series().diff() > pd.Timedelta(minutes=1)).sum()
                ),
                "source": "HISTDATA_PUBLIC_SECONDARY",
                "timezone": "FIXED_EST_UTC_MINUS_5",
            }
        )
    series = {}
    for symbol, parts in grouped.items():
        result = pd.concat(parts).sort_index()
        if result.index.has_duplicates:
            raise ValueError(f"OVERLAPPING_SOURCE_FILES:{symbol}")
        series[{"UDXUSD": "DXY", "SPXUSD": "SPX"}.get(symbol, symbol)] = result
    return series, quality


def run(directory, output, *, minutes_grid=(1, 5, 15), events_path=None):
    series, quality = load_directory(directory)
    events = pd.read_csv(events_path) if events_path else None
    result = research(series, events=events, minutes_grid=minutes_grid)
    result["datasets"] = quality
    result["event_calendar"] = str(events_path) if events_path else None
    Path(output).write_text(json.dumps(result, indent=2, allow_nan=False))
    return result
