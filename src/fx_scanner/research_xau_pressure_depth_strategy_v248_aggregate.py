from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ERA_BOUNDS = {
    "2012_2018": (2012, 2018),
    "2019_2024": (2019, 2024),
    "2025_2026": (2025, 2026),
}


def _max_drawdown(seq):
    equity = peak = max_dd = 0.0
    for value in seq:
        equity += float(value)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _combine(rows: list[dict[str, Any]]) -> dict[str, Any]:
    episodes = sum(int(r.get("episodes") or 0) for r in rows)
    fills = sum(int(r.get("fills") or 0) for r in rows)
    targets = sum(int(r.get("targets") or 0) for r in rows)
    stops = sum(int(r.get("stops") or 0) for r in rows)
    timeouts = sum(int(r.get("timeouts") or 0) for r in rows)
    gross_win = sum(float(r.get("gross_win_r") or 0.0) for r in rows)
    gross_loss = sum(float(r.get("gross_loss_r") or 0.0) for r in rows)
    seq = []
    for r in rows:
        seq.extend(float(x) for x in list(r.get("r_sequence") or []))
    net = sum(seq)
    wins = sum(x > 0 for x in seq)
    return {
        "episodes": episodes,
        "fills": fills,
        "fill_rate": None if episodes == 0 else fills / episodes,
        "targets": targets,
        "stops": stops,
        "timeouts": timeouts,
        "win_rate": None if fills == 0 else wins / fills,
        "profit_factor": None if gross_loss <= 1e-12 else gross_win / gross_loss,
        "expectancy_r": None if fills == 0 else net / fills,
        "net_r": net,
        "gross_win_r": gross_win,
        "gross_loss_r": gross_loss,
        "max_drawdown_r": _max_drawdown(seq),
        "r_sequence": seq,
    }


def run() -> int:
    root = Path(os.getenv("XAU_V248_SHARD_DIR", "/tmp/v248-shards"))
    output = Path(os.getenv("XAU_V248_FULL_OUTPUT", "artifacts/xau-pressure-depth-strategy-v248-full.json"))
    shards = []
    for path in sorted(root.rglob("xau-pressure-depth-strategy-v248-*.json")):
        payload = json.loads(path.read_text())
        shards.append((int(payload["year"]), payload))
    if not shards:
        raise SystemExit("XAU_V248_NO_SHARDS")

    variants = sorted({name for _, payload in shards for name in payload.get("variants", {})})
    full: dict[str, Any] = {}
    eras: dict[str, Any] = {era: {} for era in ERA_BOUNDS}
    yearly: dict[str, Any] = {}

    for variant in variants:
        full_rows = [
            dict(payload["variants"][variant]["cost_002r"])
            for _, payload in shards if variant in payload.get("variants", {})
        ]
        full[variant] = _combine(full_rows)
        for era, (lo, hi) in ERA_BOUNDS.items():
            era_rows = [
                dict(payload["variants"][variant]["cost_002r"])
                for year, payload in shards
                if lo <= year <= hi and variant in payload.get("variants", {})
            ]
            eras[era][variant] = _combine(era_rows)

    for year, payload in shards:
        yearly[str(year)] = {
            variant: dict(payload["variants"][variant]["cost_002r"])
            for variant in variants if variant in payload.get("variants", {})
        }

    control = full.get("FIXED20_R1.5", {})
    comparisons = {}
    for variant, metrics in full.items():
        comparisons[variant] = {
            "delta_pf_vs_fixed20_r15": (
                None if control.get("profit_factor") is None or metrics.get("profit_factor") is None
                else float(metrics["profit_factor"]) - float(control["profit_factor"])
            ),
            "delta_expectancy_vs_fixed20_r15": (
                None if control.get("expectancy_r") is None or metrics.get("expectancy_r") is None
                else float(metrics["expectancy_r"]) - float(control["expectancy_r"])
            ),
            "delta_fill_rate_vs_fixed20_r15": (
                None if control.get("fill_rate") is None or metrics.get("fill_rate") is None
                else float(metrics["fill_rate"]) - float(control["fill_rate"])
            ),
        }

    payload = {
        "contract": "XAU_PRESSURE_DEPTH_STRATEGY_V248_FULL_1",
        "research_version": "XAU_PRESSURE_DEPTH_STRATEGY_V248_1",
        "years": [year for year, _ in shards],
        "historical_pressure_source": "CAUSAL_M1_OHLC_PROXY_NOT_DOM",
        "cost_contract": "0.02R_DEDUCTED_PER_FILLED_TRADE",
        "full": full,
        "eras": eras,
        "yearly": yearly,
        "comparisons": comparisons,
        "interpretation": (
            "Episode-level supply/demand first-touch backtest. Entry depth changes with "
            "pre-touch M1 pressure. Stop is distal plus 0.05 ATR buffer. Target is fixed "
            "1.0R or 1.5R. Same-M1 stop/target ambiguity is resolved against the strategy. "
            "Results do not model portfolio overlap or compounded account margin."
        ),
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(f"XAU_PRESSURE_DEPTH_STRATEGY_V248_AGGREGATE years={len(shards)} variants={len(variants)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
