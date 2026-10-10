"""Merge timeframe runs and correct one family across all TF/asset/fold grids."""

import argparse
import json
from pathlib import Path

from fx_scanner.cross_asset_lead_lag import INSTRUMENTS, fdr_bh


def merge(paths):
    reports = [json.loads(Path(path).read_text()) for path in paths]
    report = reports[0]
    report["candidates"] = [c for r in reports for c in r["candidates"]]
    datasets = {}
    for r in reports:
        for dataset in r.get("datasets", []):
            key = dataset["file"]
            if key in datasets and datasets[key]["sha256"] != dataset["sha256"]:
                raise ValueError("SOURCE_CHANGED_BETWEEN_RUNS:" + key)
            datasets[key] = dataset
    report["datasets"] = list(datasets.values())
    aliases = {"UDXUSD": "DXY", "SPXUSD": "SPX", "NSXUSD": "NQ", "WTIUSD": "WTI"}
    available = {aliases.get(d["symbol"], d["symbol"]) for d in report["datasets"]}
    report["missing_datasets"] = {
        target: [s for s in INSTRUMENTS[target] if s not in available]
        for target in INSTRUMENTS
    }
    entries = [
        row
        for c in report["candidates"]
        for fold in [*c["walk_forward"], c["oos"]]
        for row in fold.get("grid", [])
    ]
    for entry, q in zip(entries, fdr_bh([r["train_p"] for r in entries])):
        entry["train_q_global"] = float(q)
    for candidate in report["candidates"]:
        chosen = candidate["oos"].get("selection")
        if not chosen:
            continue
        candidate["train_q_global"] = next(
            row["train_q_global"]
            for row in candidate["oos"]["grid"]
            if row["lag_minutes"] == chosen["lag_minutes"]
        )
        candidate["rejection_reasons"] = [
            r
            for r in candidate["rejection_reasons"]
            if r != "MULTIPLE_TESTING_FDR_FAILED"
        ]
        if candidate["train_q_global"] >= 0.05:
            candidate["rejection_reasons"].append("MULTIPLE_TESTING_FDR_FAILED")
    report["multiple_tests"] = len(entries)
    report["ranking"] = sorted(
        [
            {
                "target": c["target"],
                "leader": c["leader"],
                "timeframe_minutes": c["timeframe_minutes"],
                "lag_minutes": c.get("optimal_lag_minutes"),
                "oos": c["oos"].get("conditional"),
                "train_q_global": c.get("train_q_global"),
                "verdict": "RESEARCH_ONLY",
                "reasons": c["rejection_reasons"],
                "oos_year": int(c["oos"].get("train_end", "2025")[:4]),
            }
            for c in report["candidates"]
        ],
        key=lambda r: (r["oos_year"] == 2025, (r["oos"] or {}).get("ci_low") or -1),
        reverse=True,
    )
    report["limitations"].extend(
        [
            "DXY here is HistData UDXUSD CFD proxy, not direct ICE index timestamps; SPX is SPXUSD CFD proxy.",
            "Training Spearman uses deterministic chronological thinning capped approximately 50,000 rows/grid point; exact Pearson/partial correlations use all valid training observations.",
            "Daily block wild null uses 199 draws: p-value resolution 0.005. FDR rejection is conservative and not proof no economic relation exists.",
            "OOS 2025 was unseen by lead–lag selection; frozen baseline was previously selected using 2016–2025 and is not itself independently OOS.",
            "Rank order is descriptive; no leader/timeframe is selected from OOS probability for execution.",
            "NQ is NSXUSD Nasdaq CFD proxy, not CME futures. WTI is WTIUSD CFD proxy; fetching 2024/2025 failed. WTI uses an exploratory 2023 asset-specific holdout, not the common 2025 holdout.",
            "M1 training uses one seeded random observation per 15-minute block, with features calculated on the full M1 history; validation/OOS evaluate all eligible events. M5/M15 training uses every valid observation.",
        ]
    )
    report["period"] = "2016–2025"
    report["validation"] = (
        "Expanding annual train → 2017–2024 walk-forward; final 2025 lead–lag holdout"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("inputs", nargs="+")
    args = parser.parse_args()
    Path(args.output).write_text(
        json.dumps(merge(args.inputs), indent=2, allow_nan=False)
    )
