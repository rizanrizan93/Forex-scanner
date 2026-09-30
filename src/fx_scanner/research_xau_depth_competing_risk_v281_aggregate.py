from __future__ import annotations

import json
import os
from pathlib import Path

from .research_xau_depth_competing_risk_v281 import (
    ARTIFACT_CONTRACT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    PROMOTION_AUTHORITY,
    RESEARCH_VERSION,
    evaluate_oos,
    fit_volatility_thresholds,
    grouped_competing_risk,
)


def _load_rows(root: Path) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(root.rglob("xau-depth-competing-risk-v281-*.json")):
        payload = json.loads(path.read_text())
        if "year" not in payload:
            continue
        rows.extend(dict(item) for item in payload.get("episodes", []))
    return rows


def run() -> int:
    root = Path(os.getenv("XAU_V281_SHARD_DIR", "/tmp/v281-shards"))
    output = Path(
        os.getenv(
            "XAU_V281_FULL_OUTPUT",
            "artifacts/xau-depth-competing-risk-v281-full.json",
        )
    )
    rows = _load_rows(root)
    if not rows:
        raise SystemExit("XAU_V281_NO_ROWS")

    thresholds = fit_volatility_thresholds(rows)
    report = grouped_competing_risk(rows, volatility_thresholds=thresholds)
    oos = evaluate_oos(rows, volatility_thresholds=thresholds)
    years = sorted({int(row.get("year") or 0) for row in rows if int(row.get("year") or 0)})

    payload = {
        "artifact_contract": ARTIFACT_CONTRACT,
        "research_version": RESEARCH_VERSION,
        "years": years,
        "year_count": len(years),
        "episode_count": len(rows),
        "touch_scope": {
            "measured": "FIRST_TOUCH_ONLY",
            "retest": "NOT_MEASURED_BY_V225_V250_FIRST_TOUCH_DATASET",
        },
        "historical_pressure_source": "CAUSAL_M1_OHLC_TRANSITION_PROXY_NOT_DOM",
        "live_pressure_source": "CTRADER_LEVEL_II_DOM_SEPARATE_RUNTIME_SIGNAL",
        "volatility_thresholds_fit_on": "2012-2024_ONLY",
        "volatility_thresholds": thresholds,
        "competing_risk": report,
        "oos_2025_2026": oos,
        "label_contract": {
            "denominator": (
                "ALL_FIRST_TOUCH_EPISODES_WITH_MAX_DEPTH_REACHED_AT_OR_BEYOND_"
                "THE_BAND_LOWER_BOUND"
            ),
            "reversal": "REACTION_GE_0_50_ATR_BEFORE_BREAK",
            "break": "CLOSE_BEYOND_DISTAL_BEFORE_REACTION",
            "stall": "NEITHER_EVENT_WITHIN_TIMEFRAME_HORIZON",
            "probabilities": "HISTORICAL_CONDITIONAL_FREQUENCIES_NOT_LIVE_CALIBRATED_PROBABILITIES",
        },
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "promotion_gate": {
            "status": "BLOCKED_RESEARCH_ONLY",
            "minimum_250_trade_oos": "NOT_A_TRADE_BACKTEST",
            "win_rate_55pct": "NOT_EVALUATED_HERE",
            "profit_factor_1_30": "NOT_EVALUATED_HERE",
            "expectancy_plus_0_15R": "NOT_EVALUATED_HERE",
            "forward_demo_required": True,
        },
        "interpretation": (
            "V281 estimates competing first-touch outcomes conditional on reaching each "
            "depth band. Session and pressure conditioning use causal OHLC-derived V250 "
            "features, never historical DOM. Retest probabilities remain unmeasured. "
            "The OOS section evaluates event forecasting, not a tradable strategy or PnL."
        ),
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        f"XAU_DEPTH_COMPETING_RISK_V281 years={len(years)} episodes={len(rows)} "
        f"oos_exposures={oos['test_band_exposures']} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
