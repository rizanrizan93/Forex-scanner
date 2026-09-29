from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np


def _median_lookup(train, test, keys, *, min_n=40):
    groups = {}
    for row in train:
        key = tuple(row[k] for k in keys)
        groups.setdefault(key, []).append(float(row["target"]))
    tf_fallback = {}
    for row in train:
        tf_fallback.setdefault((row["timeframe"], row["direction"]), []).append(float(row["target"]))
    overall = float(np.median([float(r["target"]) for r in train]))
    pred = []
    for row in test:
        key = tuple(row[k] for k in keys)
        values = groups.get(key, [])
        if len(values) >= min_n:
            pred.append(float(np.median(values)))
        else:
            fallback = tf_fallback.get((row["timeframe"], row["direction"]), [])
            pred.append(float(np.median(fallback)) if fallback else overall)
    return np.asarray(pred, dtype=float)


def _mae(y, pred):
    return float(np.mean(np.abs(np.asarray(y, dtype=float) - np.asarray(pred, dtype=float))))


def _wilson_interval(successes, total, z=1.959963984540054):
    if int(total) <= 0:
        return [None, None]
    n = float(total)
    p = max(0.0, min(1.0, float(successes) / n))
    z2 = z * z
    denominator = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denominator
    margin = z * ((p * (1.0 - p) / n + z2 / (4.0 * n * n)) ** 0.5) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def _volatility_thresholds(train_rows):
    out = {}
    for timeframe in ("H4", "H1", "M15"):
        values = [
            float(r.get("atr_pct") or 0.0)
            for r in train_rows
            if r.get("timeframe") == timeframe and float(r.get("atr_pct") or 0.0) > 0.0
        ]
        if values:
            out[timeframe] = [
                float(np.quantile(values, 1.0 / 3.0)),
                float(np.quantile(values, 2.0 / 3.0)),
            ]
    return out


def _volatility_bucket(row, thresholds):
    value = float(row.get("atr_pct") or 0.0)
    low, high = thresholds.get(row.get("timeframe"), [0.0, float("inf")])
    if value <= low:
        return "LOW"
    if value <= high:
        return "MEDIUM"
    return "HIGH"


def _pressure_bucket(row):
    value = float(row.get("late_opposing_pressure") or 0.0)
    if value >= 40.0:
        return "OPPOSING_STRONG"
    if value >= 15.0:
        return "OPPOSING"
    if value > -15.0:
        return "BALANCED"
    return "REVERSAL_SIDE_CONTROL"


def _competing_risk_groups(rows, group_keys, *, min_n=30):
    bands = [(i / 10.0, (i + 1) / 10.0) for i in range(10)]
    groups = {}
    for row in rows:
        key = tuple(str(row.get(k) or "UNKNOWN") for k in group_keys)
        groups.setdefault(key, []).append(row)

    output = []
    for key, group_rows in sorted(groups.items()):
        band_rows = []
        for lower, upper in bands:
            at_risk = [
                row
                for row in group_rows
                if float(row.get("max_depth_reached") or 0.0) + 1e-12 >= lower
            ]
            n = len(at_risk)
            if n < min_n:
                continue
            reversal = sum(bool(row.get("reaction_hit")) for row in at_risk)
            broken = sum(bool(row.get("break_hit")) for row in at_risk)
            unresolved = max(0, n - reversal - broken)
            band_rows.append(
                {
                    "band": f"{int(lower*100):02d}-{int(upper*100):02d}%",
                    "lower_depth": lower,
                    "upper_depth": upper,
                    "at_risk": n,
                    "reversal_first": reversal,
                    "break_first": broken,
                    "unresolved": unresolved,
                    "p_reversal_first": reversal / n,
                    "p_break_first": broken / n,
                    "p_unresolved": unresolved / n,
                    "reversal_wilson_95": _wilson_interval(reversal, n),
                    "break_wilson_95": _wilson_interval(broken, n),
                    "break_minus_reversal": (broken - reversal) / n,
                }
            )
        if band_rows:
            output.append(
                {
                    "group": {name: value for name, value in zip(group_keys, key)},
                    "episodes": len(group_rows),
                    "bands": band_rows,
                    "break_crossover_band": next(
                        (
                            row["band"]
                            for row in band_rows
                            if row["p_break_first"] > row["p_reversal_first"]
                        ),
                        None,
                    ),
                }
            )
    return output


def _walk_forward_depth(rows):
    output = []
    for test_year in range(2019, 2027):
        train = [
            r for r in rows
            if int(r["year"]) < test_year
            and bool(r["reaction_hit"])
            and r.get("target") is not None
        ]
        test = [
            r for r in rows
            if int(r["year"]) == test_year
            and bool(r["reaction_hit"])
            and r.get("target") is not None
        ]
        if len(train) < 500 or len(test) < 50:
            continue
        y = [float(r["target"]) for r in test]
        base = _median_lookup(train, test, ["timeframe", "direction"])
        pressure = _median_lookup(
            train,
            test,
            ["timeframe", "direction", "transition_state", "session"],
        )
        output.append(
            {
                "test_year": test_year,
                "train_end_year": test_year - 1,
                "n_train": len(train),
                "n_test": len(test),
                "base_mae_depth_fraction": _mae(y, base),
                "pressure_session_mae_depth_fraction": _mae(y, pressure),
                "mae_improvement": _mae(y, base) - _mae(y, pressure),
            }
        )
    return output


def _ridge_features(rows, categories):
    out = []
    for row in rows:
        atr = max(float(row["atr_points"]), 1e-12)
        cont = [
            float(row["level_opposing_pressure"]) / 100.0,
            float(row["early_opposing_pressure"]) / 100.0,
            float(row["late_opposing_pressure"]) / 100.0,
            float(row["fade_delta"]) / 100.0,
            float(row["approach_progress_atr"]),
            float(row["late_progress_atr"]),
            float(row["range_compression_ratio"]),
            float(row["mean_body_efficiency"]),
            float(row["mean_close_location"]),
            float(row["zone_width"]) / atr,
        ]
        cats = []
        for name, values in categories.items():
            cats.extend(1.0 if row[name] == value else 0.0 for value in values)
        out.append([1.0] + cont + cats)
    return np.asarray(out, dtype=float)


def _ridge_predict(train, test):
    categories = {
        "timeframe": ["H4", "H1", "M15"],
        "direction": ["LONG", "SHORT"],
        "transition_state": ["STRONG_FADE", "FADE", "BALANCE_OR_CONTROL_FLIP", "REACCELERATION", "STABLE"],
        "session": ["SYDNEY", "TOKYO", "LONDON", "NEW_YORK", "SYDNEY_TOKYO_OVERLAP", "LONDON_NY_OVERLAP", "OFF_SESSION"],
    }
    x = _ridge_features(train, categories)
    xt = _ridge_features(test, categories)
    y = np.asarray([float(r["target"]) for r in train], dtype=float)
    means = x[:, 1:11].mean(axis=0)
    stds = x[:, 1:11].std(axis=0)
    stds[stds < 1e-9] = 1.0
    x[:, 1:11] = (x[:, 1:11] - means) / stds
    xt[:, 1:11] = (xt[:, 1:11] - means) / stds
    penalty = np.eye(x.shape[1]) * 3.0
    penalty[0, 0] = 0.0
    beta = np.linalg.solve(x.T @ x + penalty, x.T @ y)
    return np.clip(xt @ beta, 0.0, 1.0)


def run() -> int:
    root = Path(os.getenv("XAU_V250_SHARD_DIR", "/tmp/v250-shards"))
    output = Path(os.getenv("XAU_V250_FULL_OUTPUT", "artifacts/xau-pressure-transition-depth-v250-full.json"))
    rows = []
    for path in sorted(root.rglob("xau-pressure-transition-depth-v250-*.json")):
        payload = json.loads(path.read_text())
        rows.extend(dict(x) for x in payload.get("episodes", []))
    if not rows:
        raise SystemExit("XAU_V250_NO_ROWS")

    for row in rows:
        depth = row.get("turning_depth")
        row["target"] = None if depth is None else max(0.0, min(1.0, float(depth)))
    causal_train_rows = [r for r in rows if int(r["year"]) <= 2024]
    vol_thresholds = _volatility_thresholds(causal_train_rows)
    for row in rows:
        row["volatility_bucket"] = _volatility_bucket(row, vol_thresholds)
        row["pressure_bucket"] = _pressure_bucket(row)
    train = [r for r in rows if int(r["year"]) <= 2024 and bool(r["reaction_hit"]) and r["target"] is not None]
    test = [r for r in rows if int(r["year"]) >= 2025 and bool(r["reaction_hit"]) and r["target"] is not None]
    y = np.asarray([float(r["target"]) for r in test], dtype=float)

    variants = {}
    for name, keys in {
        "BASE_TF_DIR": ["timeframe", "direction"],
        "PRESSURE_LEVEL": ["timeframe", "direction", "transition_state"],
        "TRANSITION_SESSION": ["timeframe", "direction", "transition_state", "session"],
    }.items():
        pred = _median_lookup(train, test, keys)
        variants[name] = {
            "mae_depth_fraction": _mae(y, pred),
            "mean_prediction": float(np.mean(pred)),
            "n_test": len(test),
        }
    ridge = _ridge_predict(train, test)
    variants["CONTINUOUS_RIDGE"] = {
        "mae_depth_fraction": _mae(y, ridge),
        "mean_prediction": float(np.mean(ridge)),
        "n_test": len(test),
    }

    baseline = variants["BASE_TF_DIR"]["mae_depth_fraction"]
    for metrics in variants.values():
        metrics["mae_improvement_vs_baseline"] = baseline - metrics["mae_depth_fraction"]
        metrics["relative_improvement_vs_baseline"] = (baseline - metrics["mae_depth_fraction"]) / baseline if baseline else None

    # Two-stage contract: do not force a reversal depth when the training cell
    # itself has weak hold evidence. This is evaluated as coverage vs accuracy.
    hold_groups = {}
    for row in [r for r in rows if int(r["year"]) <= 2024]:
        key = (row["timeframe"], row["direction"], row["transition_state"], row["session"])
        hold_groups.setdefault(key, []).append(bool(row["reaction_hit"]))
    confidence_rows = []
    for row in test:
        key = (row["timeframe"], row["direction"], row["transition_state"], row["session"])
        vals = hold_groups.get(key, [])
        if len(vals) >= 50:
            confidence_rows.append((row, sum(vals) / len(vals)))
    confidence = {}
    transition_pred = _median_lookup(train, [r for r, _ in confidence_rows], ["timeframe","direction","transition_state","session"]) if confidence_rows else np.asarray([])
    for threshold in (0.60, 0.65, 0.70, 0.75):
        idx = [i for i, (_, p) in enumerate(confidence_rows) if p >= threshold]
        if not idx:
            confidence[str(threshold)] = {"n": 0, "coverage": 0.0, "mae_depth_fraction": None}
            continue
        yy = [float(confidence_rows[i][0]["target"]) for i in idx]
        pp = [float(transition_pred[i]) for i in idx]
        confidence[str(threshold)] = {
            "n": len(idx),
            "coverage": len(idx) / len(test) if test else 0.0,
            "mae_depth_fraction": _mae(yy, pp),
        }

    payload = {
        "contract": "XAU_PRESSURE_TRANSITION_DEPTH_V250_FULL_1",
        "research_version": "XAU_PRESSURE_TRANSITION_DEPTH_V250_1",
        "train_years": "2012-2024",
        "test_years": "2025-2026",
        "historical_pressure_source": "CAUSAL_M1_OHLC_TRANSITION_PROXY_NOT_DOM",
        "train_reaction_rows": len(train),
        "test_reaction_rows": len(test),
        "variants": variants,
        "two_stage_confidence": confidence,
        "walk_forward_depth": _walk_forward_depth(rows),
        "volatility_thresholds_atr_pct_train_2012_2024": vol_thresholds,
        "competing_risk": {
            "denominator_contract": "ALL_FIRST_TOUCH_EPISODES_THAT_REACHED_BAND_LOWER_BOUND",
            "outcome_contract": "REACTION_GTE_0_50_ATR_VS_CLOSE_BREAK_BEYOND_DISTAL",
            "historical_pressure_source": "CAUSAL_M1_OHLC_TRANSITION_PROXY_NOT_DOM",
            "oos_2025_2026_by_timeframe_direction": _competing_risk_groups(
                [r for r in rows if int(r["year"]) >= 2025],
                ["timeframe", "direction"],
            ),
            "oos_2025_2026_by_session": _competing_risk_groups(
                [r for r in rows if int(r["year"]) >= 2025],
                ["timeframe", "direction", "session"],
            ),
            "oos_2025_2026_by_pressure_transition": _competing_risk_groups(
                [r for r in rows if int(r["year"]) >= 2025],
                ["timeframe", "direction", "transition_state"],
            ),
            "oos_2025_2026_by_pressure_level": _competing_risk_groups(
                [r for r in rows if int(r["year"]) >= 2025],
                ["timeframe", "direction", "pressure_bucket"],
            ),
            "oos_2025_2026_by_volatility": _competing_risk_groups(
                [r for r in rows if int(r["year"]) >= 2025],
                ["timeframe", "direction", "volatility_bucket"],
            ),
            "eras_by_timeframe_direction": {
                "2012_2018": _competing_risk_groups(
                    [r for r in rows if 2012 <= int(r["year"]) <= 2018],
                    ["timeframe", "direction"],
                ),
                "2019_2024": _competing_risk_groups(
                    [r for r in rows if 2019 <= int(r["year"]) <= 2024],
                    ["timeframe", "direction"],
                ),
                "2025_2026": _competing_risk_groups(
                    [r for r in rows if 2025 <= int(r["year"]) <= 2026],
                    ["timeframe", "direction"],
                ),
            },
        },
        "interpretation": "Depth is only predicted conditional on a reaction. Competing-risk reports use every first-touch episode that reached each band. Historical pressure is a causal M1 OHLC proxy; live execution uses true cTrader Level-II transition and never treats the proxy as DOM.",
        "execution_influence": False,
        "execution_authority": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(f"XAU_PRESSURE_TRANSITION_DEPTH_V250 train={len(train)} test={len(test)} baseline={baseline:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())