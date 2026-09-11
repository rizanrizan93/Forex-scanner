from __future__ import annotations

import json
from pathlib import Path

import adaptive_public_v1 as base


def choose_mapping_consistent(trades, keys):
    """V1.1 correction: use the same non-overlap exposure rule in selection and OOS."""
    train = trades[trades["split"] == "TRAIN"]
    val = trades[trades["split"] == "VALIDATION"]
    mapping = {}
    for vals in train[keys].drop_duplicates().itertuples(index=False, name=None):
        qtr, qv = train, val
        for key, value in zip(keys, vals):
            qtr = qtr[qtr[key] == value]
            qv = qv[qv[key] == value]
        candidates = []
        for strategy in base.SPECS:
            a = base.nonoverlap(qtr[qtr["strategy"] == strategy])
            b = base.nonoverlap(qv[qv["strategy"] == strategy])
            if (
                len(a) >= base.MIN_TRAIN
                and len(b) >= base.MIN_VALIDATION
                and a["net_r"].mean() > 0
                and b["net_r"].mean() > 0
            ):
                candidates.append((float(a["net_r"].mean()), strategy))
        mapping[vals] = max(candidates)[1] if candidates else "NO_TRADE"
    return mapping


def main() -> None:
    base.choose_mapping = choose_mapping_consistent
    base.main()

    out = Path("research_output")
    src = out / "adaptive_public_v1.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    data["contract"] = "ADAPTIVE_PUBLIC_RESEARCH_V1_1"
    data["methodology_correction"] = (
        "Train/validation strategy evidence is non-overlapped before sample-size and expectancy gates, "
        "matching the OOS exposure policy. No strategy parameters, split dates, costs, or regime thresholds changed."
    )
    data["selection_rule"] = (
        f"non-overlap first; train n>={base.MIN_TRAIN}, validation n>={base.MIN_VALIDATION}, "
        "positive expectancy in both; rank by TRAIN expectancy only; otherwise NO_TRADE"
    )
    dst = out / "adaptive_public_v1_1.json"
    dst.write_text(json.dumps(data, indent=2), encoding="utf-8")

    summary = out / "adaptive_public_v1.md"
    if summary.exists():
        text = summary.read_text(encoding="utf-8")
        (out / "adaptive_public_v1_1.md").write_text(
            text.replace("Adaptive Public Research V1", "Adaptive Public Research V1.1", 1)
            + "\n\nMethodology correction: selection-stage trades are non-overlapped before gates.\n",
            encoding="utf-8",
        )

    print("V1.1 methodology correction applied: non-overlap selection evidence.")
    print(json.dumps(data["systems"], indent=2))
    print("PAIR_MAP", json.dumps(data["pair_map"], indent=2))
    print("REGIME_MAP", json.dumps(data["regime_map"], indent=2))
    print("PAIR_REGIME_MAP", json.dumps(data["pair_regime_map"], indent=2))


if __name__ == "__main__":
    main()
