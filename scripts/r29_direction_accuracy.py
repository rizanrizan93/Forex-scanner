"""R29 research: independent side selection with purged chronological evaluation.

No runtime writes or orders. Previously inspected archives are reused research
data, not pristine holdout. All candidate/rule selection excludes each test year.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

CUTS = (.50, .53, .56, .60, .65, .70)
MIN_SIDE = {"1h": 100, "4h": 40, "1D": 20, "1W": 8}
TF_NAMES = {"1h": "H1", "4h": "H4", "1D": "D1", "1W": "W1"}


def wilson(k, n):
    if not n:
        return None
    p = k/n
    z = 1.959963984540054
    return float((p+z*z/(2*n)-z*np.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n))


def metrics(y, buy, sell):
    buy, sell = np.asarray(buy, bool), np.asarray(sell, bool)
    conflict = buy & sell
    buy, sell = buy & ~conflict, sell & ~conflict
    out = {}
    for name, mask, label in (("BUY", buy, 1), ("SELL", sell, 0)):
        n = int(mask.sum())
        k = int((np.asarray(y)[mask] == label).sum())
        out[name] = {"n": n, "correct": k, "accuracy": k/n if n else None,
                     "wilson_lower95": wilson(k, n)}
    n = int((buy | sell).sum())
    k = out["BUY"]["correct"]+out["SELL"]["correct"]
    out.update(n=n, correct=k, accuracy=k/n if n else None,
               coverage=n/len(y) if len(y) else 0, eligible=int(len(y)),
               conflicts=int(conflict.sum()), wilson_lower95=wilson(k, n))
    return out


def chronological_masks(times, maturity, valid, year, window=0):
    """Fit before two validation years; all labels mature before boundaries."""
    start = pd.Timestamp(f"{year}-01-01", tz="UTC")
    val_start = pd.Timestamp(f"{year-2}-01-01", tz="UTC")
    end = pd.Timestamp(f"{year+1}-01-01", tz="UTC")
    train = valid & (times < val_start) & np.asarray(maturity < val_start)
    refit = valid & (times < start) & np.asarray(maturity < start)
    if window:
        train &= times >= val_start-pd.DateOffset(years=window)
        refit &= times >= start-pd.DateOffset(years=window)
    val = valid & (times >= val_start) & (times < start) & np.asarray(maturity < start)
    test = valid & (times >= start) & (times < end) & np.asarray(maturity < end)
    return tuple(np.asarray(a) for a in (train, val, refit, test))


def policies(y, predictions, minimum):
    """Choose BUY and SELL models using validation predictions ONLY."""
    ranked = {"BUY": [], "SELL": []}
    for key, p in predictions.items():
        for side, label in (("BUY", 1), ("SELL", 0)):
            scores = p if label else 1-p
            for cut in CUTS:
                mask = scores >= cut if cut != .5 or label else scores > cut
                n = int(mask.sum())
                if n < minimum or n/len(y) < .10:
                    continue
                k = int((y[mask] == label).sum())
                ranked[side].append((wilson(k, n), n, key, cut, mask))
    for side in ranked:
        ranked[side].sort(key=lambda a: (-a[0], -a[1], a[2], a[3]))
    best = None
    for b in ranked["BUY"][:12]:
        for s in ranked["SELL"][:12]:
            m = metrics(y, b[4], s[4])
            if min(m["BUY"]["n"], m["SELL"]["n"]) < minimum or m["coverage"] < .20:
                continue
            rank = (min(m["BUY"]["wilson_lower95"], m["SELL"]["wilson_lower95"]),
                    m["wilson_lower95"], m["coverage"])
            if best is None or rank > best[0]:
                best = (rank, {"BUY": {"model": b[2], "cut": b[3]},
                               "SELL": {"model": s[2], "cut": s[3]}}, m)
    return None if best is None else {"policy": best[1], "validation": best[2]}


def model(kind):
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import HistGradientBoostingClassifier, ExtraTreesClassifier
    if kind.startswith("logit"):
        return make_pipeline(StandardScaler(), LogisticRegression(C=float(kind.split(":")[1]), max_iter=600))
    if kind == "hgb":
        return HistGradientBoostingClassifier(max_iter=80, max_leaf_nodes=7,
            max_depth=3, min_samples_leaf=40, l2_regularization=20,
            learning_rate=.05, random_state=29)
    return ExtraTreesClassifier(n_estimators=100, max_depth=5,
        min_samples_leaf=30, random_state=29, n_jobs=1)


def data(tf):
    from r14_multitimeframe_direction import load_tf
    from r16_direction_complexity import features
    from r281_ecb_usd_context import loadfx, cross
    from r281_live_shadow_parity import extended_ecb
    d, z, _, y, valid, times = load_tf(tf)
    p = features(z)
    fx, fx_meta = extended_ecb()
    if fx_meta["status"] != "ECB_2026_APPENDED":
        raise ValueError("Cannot evaluate 2026 without matching ECB input")
    q = cross(fx, d, times, tf)
    a = z.atr14.replace(0, np.nan)
    structure = p.copy()
    structure["return1_atr"] = d.c.diff()/a
    structure["return2_atr"] = d.c.diff(2)/a
    structure["distance_high20"] = (d.c-z.prev20h)/a
    structure["distance_low20"] = (d.c-z.prev20l)/a
    structure["trend_body"] = p.ema*p.body
    structure["trend_clv"] = p.ema*p.clv
    groups = {"price": p, "structure": structure,
              "structure_fx": pd.concat([structure, q], axis=1)}
    common = valid & (times.year >= 2019)
    for f in groups.values():
        common &= np.isfinite(f.to_numpy(float)).all(axis=1)
    # Prefix audit of added structure features: no future candles required.
    from r10_million import ohlc_indicators
    audit = []
    for i in np.flatnonzero(common)[::max(1, int(common.sum())//12)][:12]:
        prefix = d.iloc[:i+1]
        zz = ohlc_indicators(prefix)
        expected = [(prefix.c.diff()/zz.atr14).iloc[-1],
                    (prefix.c.diff(2)/zz.atr14).iloc[-1],
                    ((prefix.c-zz.prev20h)/zz.atr14).iloc[-1],
                    ((prefix.c-zz.prev20l)/zz.atr14).iloc[-1]]
        actual = structure.iloc[i][["return1_atr", "return2_atr", "distance_high20", "distance_low20"]]
        if not np.allclose(expected, actual.to_numpy(float), atol=1e-9, rtol=1e-9):
            raise AssertionError("R29 prefix causal audit failed")
        audit.append(d.index[i].isoformat())
    return d, y, times, common, groups, q, fx_meta, audit


def baseline(tf, year, y, times, maturity, valid, groups, forex):
    from r281_live_shadow_parity import record, classifier
    archive, _, family, _ = record(tf)
    source_year = min(year, 2025)
    annual = next(a for a in archive["annual"] if a["year"] == source_year)
    policy = annual["policies"][family]
    x = groups["price"] if family == "price" else forex if family == "fx" else pd.concat([groups["price"], forex], axis=1)
    start = pd.Timestamp(f"{year}-01-01", tz="UTC")
    # The deployed 2026 reconstruction refits through 2025. Historical 2023-25
    # originals train only before their validation year, not after selection.
    fit_end = start if year == 2026 else pd.Timestamp(f"{year-1}-01-01", tz="UTC")
    train = valid & (times < fit_end) & np.asarray(maturity < fit_end)
    _, _, _, test = chronological_masks(times, maturity, valid, year)
    masks = {}
    for side, label in (("BUY", 1), ("SELL", 0)):
        cfg = policy[side+"_config"]
        if cfg is None:
            masks[side] = np.zeros(int(test.sum()), bool)
            continue
        m = classifier(cfg["C"])
        m.fit(x.to_numpy(float)[train], (y[train] == label).astype(int))
        masks[side] = m.predict_proba(x.to_numpy(float)[test])[:, 1] >= cfg["threshold"]
    return metrics(y[test], masks["BUY"], masks["SELL"])


def run(tf):
    d, y, times, valid, groups, forex, fx_meta, audit = data(tf)
    maturity = pd.Series(times, index=d.index).shift(-1)
    arrays = {k: f.to_numpy(float) for k, f in groups.items()}
    folds = []
    fits = 0
    for year in (2023, 2024, 2025, 2026):
        configs, predictions = {}, {}
        for group in arrays:
            for kind in ("logit:0.03", "logit:0.3", "hgb", "extra"):
                for window in (0, 3):
                    tr, va, refit, te = chronological_masks(times, maturity, valid, year, window)
                    if tr.sum() < 60 or va.sum() < 2*MIN_SIDE[tf] or te.sum() < 10:
                        continue
                    key = f"{group}|{kind}|{window}"
                    estimator = model(kind)
                    estimator.fit(arrays[group][tr], y[tr])
                    predictions[key] = estimator.predict_proba(arrays[group][va])[:, 1]
                    configs[key] = (group, kind, window)
                    fits += 1
        _, va, _, te = chronological_masks(times, maturity, valid, year)
        chosen = policies(y[va], predictions, MIN_SIDE[tf])
        if chosen is None:
            folds.append({"year": year, "status": "NO_VALIDATION_POLICY"})
            continue
        masks = {}
        for side, label in (("BUY", 1), ("SELL", 0)):
            policy = chosen["policy"][side]
            group, kind, window = configs[policy["model"]]
            tr, _, refit, _ = chronological_masks(times, maturity, valid, year, window)
            estimator = model(kind)
            estimator.fit(arrays[group][refit], y[refit])
            p = estimator.predict_proba(arrays[group][te])[:, 1]
            value = p if label else 1-p
            masks[side] = value >= policy["cut"] if policy["cut"] != .5 or label else value > .5
            fits += 1
        result = metrics(y[te], masks["BUY"], masks["SELL"])
        ref = baseline(tf, year, y, times, maturity, valid, groups, forex)
        row = {"year": year, "status": "EVALUATED", **chosen,
               "r29": result, "r281_same_sample": ref,
               "accuracy_delta_pp": 100*(result["accuracy"]-ref["accuracy"]) if result["accuracy"] is not None and ref["accuracy"] is not None else None}
        folds.append(row)
        print(json.dumps({"tf": tf, **row}), flush=True)
    checksums = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                 for root, pattern in (("/tmp/r10", "r10-*.csv"), ("/tmp/r98", "daily-*.csv"))
                 for p in sorted(Path(root).glob(pattern))}
    output = {"contract": "RIZAN_R29_ACCURACY_RESEARCH_V1", "tf": TF_NAMES[tf],
              "research_only": True, "execution_authority": False,
              "production_changed": False, "fits": fits, "folds": folds,
              "protocol": "fit before validation; two preceding years select side policies; refit before test; purge boundary labels",
              "limitations": ["Previously inspected archives; chronological evaluation is not pristine holdout",
                              "2026 partial year ends at source archive cutoff, not current broker time",
                              "ECB daily proxy availability is assumed, not point-in-time audited",
                              "Historical partial-candle filters differ from strict broker aggregation",
                              "No automatic live promotion; independent prospective evidence required"],
              "last_source_candle_open": d.index[-1].isoformat(),
              "ecb": fx_meta, "prefix_checks": audit, "source_sha256": checksums}
    root = Path("artifacts/r29")
    root.mkdir(parents=True, exist_ok=True)
    (root/f"r29-{tf}.json").write_text(json.dumps(output, indent=2, allow_nan=False)+"\n")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tf", choices=list(TF_NAMES), required=True)
    run(parser.parse_args().tf)
