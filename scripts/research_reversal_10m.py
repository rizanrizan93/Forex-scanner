"""Exact sufficient-statistic search, not ten million independent strategies.

10,000,000 distinct parameter tuples; repeated outcome masks are possible.
Every tuple gets chronological train/validation/holdout counts. Holdout remains
unseen until 20 validation finalists are locked. No trading or DB credentials.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fx_scanner.reversal_zones import (GRID, SHAPE, CONFIGURATIONS, CONTRACT,
    normalize_bars, closed_features, base_events, thin_events, config_from_index, matches)


@njit(cache=True)
def outcomes(times, high, low, close, starts, entry, level, atr, side):
    result = np.zeros((len(starts), 5, 5, 4), np.int8)
    stops = np.array([.2, .35, .5, .75, 1.])
    targets = np.array([.5, .75, 1., 1.5, 2.])
    horizons = np.array([30, 60, 120, 240])
    for e in range(len(starts)):
        for si in range(5):
            stop = level[e] - side*stops[si]*atr[e]
            for ti in range(5):
                target = entry[e] + side*targets[ti]*atr[e]
                for hi in range(4):
                    begin = starts[e]
                    end = times[begin] + horizons[hi]*60
                    state = 0
                    prev = times[begin]-60
                    complete = False
                    for j in range(begin, len(times)):
                        if times[j] >= end:
                            complete = True
                            break
                        if times[j]-prev > 300:
                            state = -2  # right-censored gap; never a win/loss
                            complete = True
                            break
                        prev = times[j]
                        invalid = low[j] <= stop if side == 1 else high[j] >= stop
                        reversal = high[j] >= target if side == 1 else low[j] <= target
                        if invalid:  # conservative stop first on ambiguous M1
                            state = -1
                            complete = True
                            break
                        if reversal:
                            state = 1
                            complete = True
                            break
                    result[e, si, ti, hi] = state if complete else -2
    return result


def expand_hist(hist):
    # axes: wick>=threshold, approach>=threshold, age<=threshold, trend, session
    hist = np.flip(np.cumsum(np.flip(hist, axis=0), axis=0), axis=0)
    hist = np.flip(np.cumsum(np.flip(hist, axis=1), axis=1), axis=1)
    hist = np.cumsum(hist, axis=2)
    return np.concatenate([hist.sum(axis=3, keepdims=True), hist], axis=3)


def labels_for(m1, events, side):
    times = m1.index.asi8 // 10**9
    signal = events.index.asi8 // 10**9
    starts = np.searchsorted(times, signal)
    good = starts < len(m1)
    # Do not slide an observation into the next session if next minute missing.
    good[good] &= times[starts[good]] == signal[good]
    events = events.loc[good]
    return events, outcomes(times, m1.high.to_numpy(), m1.low.to_numpy(), m1.close.to_numpy(),
        starts[good], events.close.to_numpy(), events.level.to_numpy(), events.atr.to_numpy(), side)


def shard(csv, year, output):
    m1 = normalize_bars(pd.read_csv(csv))
    f = closed_features(m1)
    count = np.zeros(SHAPE, np.int32)
    wins = np.zeros(SHAPE, np.int32)
    losses = np.zeros(SHAPE, np.int32)
    censored = 0
    event_count = 0
    for sid, side in enumerate(GRID["side"]):
        for li, lookback in enumerate(GRID["lookback_h1"]):
            for wi, width in enumerate(GRID["half_width_atr"]):
                events = thin_events(base_events(f, side, lookback, width).query("year == @year"))
                events, labels = labels_for(m1, events, side)
                bins = tuple(events[c].to_numpy(int) for c in
                             ["wick_bin", "approach_bin", "age_bin", "trend_bin", "session"])
                event_count += len(events)
                for si in range(5):
                    for ti in range(5):
                        for hi in range(4):
                            values = labels[:, si, ti, hi]
                            censored += int((values == -2).sum())
                            for dest, mask in [(count, values != -2), (wins, values == 1), (losses, values == -1)]:
                                hist = np.zeros((5,5,5,3,4), np.int32)
                                np.add.at(hist, tuple(x[mask] for x in bins), 1)
                                # dest tail order wick,trend,approach,age,session
                                dest[sid,li,wi,si,ti,hi] = expand_hist(hist).transpose(0,3,1,2,4)
                print(f"BASE_COMPLETE year={year} side={side} lookback={lookback} width={width} n={len(events)}", flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, count=count, wins=wins, losses=losses)
    meta = {"contract": CONTRACT, "year": year, "configurations": CONFIGURATIONS,
        "rows": len(m1), "first_utc": m1.index[0].isoformat(), "last_utc": m1.index[-1].isoformat(),
        "source_sha256": hashlib.sha256(Path(csv).read_bytes()).hexdigest(),
        "base_observations":event_count, "censored_outcomes":censored,
        "execution_authority":False}
    output.with_suffix(".json").write_text(json.dumps(meta, indent=2)+"\n")


def wilson(w, n):
    n = np.maximum(n, 1)
    p = w/n
    z = 1.96
    return (p+z*z/(2*n)-z*np.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)


def metric(w, n, l):
    return {"n":int(n), "reversals":int(w), "invalidations":int(l),
        "unresolved":int(n-w-l), "probability":float(w/n) if n else None,
        "wilson_lower_95":float(wilson(w,n)) if n else None}


def aggregate(folder, output):
    files = sorted(folder.rglob("year-*.npz"))
    years = {int(p.stem.split("-")[-1]):p for p in files}
    if set(years) != set(range(2016,2026)):
        raise ValueError(f"TEN_YEARS_REQUIRED: {sorted(years)}")
    train = [np.zeros(SHAPE, np.int32) for _ in range(3)]
    val = [np.zeros(SHAPE, np.int32) for _ in range(3)]
    names = ["wins", "count", "losses"]
    train_good_years = np.zeros(SHAPE, np.int8)
    metadata = []
    # Holdout archives deliberately not loaded until finalists locked below.
    for year in range(2016,2024):
        with np.load(years[year]) as data:
            dest = train if year <= 2021 else val
            for a, name in zip(dest, names): a += data[name]
            if year <= 2021: train_good_years += (data["count"] >= 30)
        metadata.append(json.loads(years[year].with_suffix(".json").read_text()))
    score = wilson(val[0], val[1])
    eligible = ((train[1] >= 300) & (val[1] >= 100) & (train_good_years >= 5) &
                (train[0]/np.maximum(train[1],1) >= .5) & (score >= .50))
    score[~eligible] = -1
    flat = score.ravel()
    indices = np.flatnonzero(eligible.ravel())
    order = indices[np.argsort(flat[indices], kind="stable")[-20:][::-1]]
    finalists = []
    for flat_index in order:
        idx = np.unravel_index(int(flat_index), SHAPE)
        finalists.append({"index":int(flat_index), "config":config_from_index(idx),
            "train":metric(*(a[idx] for a in train)), "validation":metric(*(a[idx] for a in val))})
    lock = hashlib.sha256(json.dumps(finalists, sort_keys=True).encode()).hexdigest()
    for year in range(2024,2026):
        with np.load(years[year]) as data:
            for row in finalists:
                idx = np.unravel_index(row["index"], SHAPE)
                row.setdefault("holdout_by_year", {})[str(year)] = metric(*(data[name][idx] for name in names))
        metadata.append(json.loads(years[year].with_suffix(".json").read_text()))
    for row in finalists:
        values = list(row["holdout_by_year"].values())
        row["holdout"] = metric(sum(x["reversals"] for x in values), sum(x["n"] for x in values), sum(x["invalidations"] for x in values))
        row["qualified"] = (row["holdout"]["n"] >= 100 and row["holdout"]["wilson_lower_95"] >= .5
                             and all(x["n"]>=30 and x["probability"]>=.5 for x in values))
    # The validation winner is frozen. Never switch to a lower finalist after
    # looking at holdout. If it fails, show research only, no calibrated map.
    selected = finalists[0] if finalists else None
    result = {"contract":CONTRACT, "configurations_evaluated":CONFIGURATIONS,
        "parameter_grid":GRID, "period":"2016-2025", "train":"2016-2021",
        "validation":"2022-2023", "holdout":"2024-2025", "finalist_lock_sha256":lock,
        "selected":selected, "finalists":finalists, "source_years":metadata,
        "status":"VALIDATED" if selected and selected["qualified"] else "RESEARCH_ONLY",
        "execution_authority":False, "probability_kind":"EMPIRICAL_CONDITIONAL_M5_CONFIRMATION",
        "limitations":["10m parameter tuples may share identical event masks; not 10m independent edges.",
          "Public secondary bid M1 OHLC; no broker spread, commission or profit claim.",
          "Reversal = chosen ATR excursion before invalidation, within chosen horizon; unresolved counts as failure.",
          "Four-hour non-overlap per base; signals across base configurations remain dependent.",
          "Wilson intervals are descriptive, not corrected for 10m selection or serial dependence.",
          "No macro/event conditioning without historical point-in-time provenance."]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(f"SEARCH_COMPLETE configurations={CONFIGURATIONS} eligible={int(eligible.sum())} status={result['status']}", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=Path); p.add_argument("--year", type=int)
    p.add_argument("--shards", type=Path); p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.shards: aggregate(args.shards, args.output)
    else: shard(args.csv, args.year, args.output)
