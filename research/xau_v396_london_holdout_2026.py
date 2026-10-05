from __future__ import annotations

"""V396 untouched-2026 holdout for the frozen V395 profitability candidate.

Frozen candidate (selected using 2025 only):
- base entry policy: SWEEP_RECLAIM_M5
- session filter: UTC hour >= 07 and < 13 (V395 SESSION_LONDON bucket)
- execution geometry/cost model: exactly V394

No parameters are selected or tuned on 2026. 2026 is partial through the data
available when the workflow runs. The candidate passes only if the predeclared
overall gate and both temporal subperiod checks pass.

Research only. DEMO/LIVE authority remains false regardless of result.
"""

import argparse
import glob
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

SCHEMA = "XAU_V396_LONDON_SWEEP_HOLDOUT_2026_V1"
BASE_POLICY = "SWEEP_RECLAIM_M5"
SESSION_UTC_START = 7
SESSION_UTC_END = 13
MAX_OPEN_POSITIONS = 10

MIN_TOTAL_TRADES = 30
MIN_PF = 1.15
MIN_EXPECTANCY_R = 0.05
MAX_DRAWDOWN_R = 15.0
MIN_SUBPERIOD_TRADES = 12
MIN_SUBPERIOD_PF = 1.0
MIN_SUBPERIOD_EXPECTANCY_R = 0.0


def _dt(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _is_london(row: dict[str, Any]) -> bool:
    hour = _dt(row["entry_at"]).hour
    return SESSION_UTC_START <= hour < SESSION_UTC_END


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dd


def _apply_max10(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    accepted: list[dict[str, Any]] = []
    active_exits: list[datetime] = []
    rejected = 0
    for row in sorted(rows, key=lambda x: str(x.get("entry_at") or "")):
        entry_at = _dt(row["entry_at"])
        active_exits = [x for x in active_exits if x > entry_at]
        if len(active_exits) >= MAX_OPEN_POSITIONS:
            rejected += 1
            continue
        accepted.append(row)
        active_exits.append(_dt(row["exit_at"]))
    return accepted, rejected


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted(rows, key=lambda x: str(x.get("entry_at") or ""))
    r = [float(x["r_multiple"]) for x in rows]
    wins = [x for x in r if x > 0]
    losses = [x for x in r if x < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    pf = None if gl <= 1e-12 else gp / gl
    return {
        "trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": None if not r else len(wins) / len(r),
        "profit_factor_r": pf,
        "expectancy_r": None if not r else sum(r) / len(r),
        "total_r": sum(r),
        "max_drawdown_r": _max_drawdown(r),
        "median_mae_r": None if not rows else median(float(x["mae_r"]) for x in rows),
        "median_mfe_r": None if not rows else median(float(x["mfe_r"]) for x in rows),
        "median_duration_hours": None if not rows else median(float(x["duration_hours"]) for x in rows),
        "long_count": sum(str(x.get("direction") or "").upper() == "LONG" for x in rows),
        "short_count": sum(str(x.get("direction") or "").upper() == "SHORT" for x in rows),
        "h1_zone_count": sum(str(x.get("zone_timeframe") or "").upper() == "H1" for x in rows),
        "h4_zone_count": sum(str(x.get("zone_timeframe") or "").upper() == "H4" for x in rows),
    }


def _pf_gt(value: Any, floor: float, metrics: dict[str, Any]) -> bool:
    if value is None:
        return int(metrics.get("losses") or 0) == 0 and int(metrics.get("wins") or 0) > 0
    return float(value) > floor


def run(inputs: str, output: Path) -> dict[str, Any]:
    files = sorted(Path(p) for p in glob.glob(inputs))
    if not files:
        raise RuntimeError(f"No V396 source shards matched {inputs}")

    raw: list[dict[str, Any]] = []
    for path in files:
        p = json.loads(path.read_text(encoding="utf-8"))
        if int(p.get("year") or 0) != 2026:
            raise RuntimeError(f"Non-2026 shard in holdout: {path}")
        raw.extend(dict(x) for x in list(dict(p.get("trades") or {}).get(BASE_POLICY) or []))

    london = [x for x in raw if _is_london(x)]
    accepted, overlap_rejects = _apply_max10(london)
    split = datetime(2026, 7, 1, tzinfo=timezone.utc)
    h1_rows = [x for x in accepted if _dt(x["entry_at"]) < split]
    h2_rows = [x for x in accepted if _dt(x["entry_at"]) >= split]

    overall = _metrics(accepted)
    h1 = _metrics(h1_rows)
    h2 = _metrics(h2_rows)

    checks = {
        "overall_min_trades": overall["trades"] >= MIN_TOTAL_TRADES,
        "overall_pf": _pf_gt(overall["profit_factor_r"], MIN_PF, overall),
        "overall_expectancy": overall["expectancy_r"] is not None and float(overall["expectancy_r"]) > MIN_EXPECTANCY_R,
        "overall_max_drawdown": float(overall["max_drawdown_r"]) <= MAX_DRAWDOWN_R,
        "h1_min_trades": h1["trades"] >= MIN_SUBPERIOD_TRADES,
        "h1_pf": _pf_gt(h1["profit_factor_r"], MIN_SUBPERIOD_PF, h1),
        "h1_expectancy": h1["expectancy_r"] is not None and float(h1["expectancy_r"]) > MIN_SUBPERIOD_EXPECTANCY_R,
        "h2_min_trades": h2["trades"] >= MIN_SUBPERIOD_TRADES,
        "h2_pf": _pf_gt(h2["profit_factor_r"], MIN_SUBPERIOD_PF, h2),
        "h2_expectancy": h2["expectancy_r"] is not None and float(h2["expectancy_r"]) > MIN_SUBPERIOD_EXPECTANCY_R,
    }
    passed = all(checks.values())
    payload = {
        "schema": SCHEMA,
        "year": 2026,
        "holdout": True,
        "selection_data_used": "2025_ONLY",
        "frozen_candidate": {
            "entry_policy": BASE_POLICY,
            "session_filter": "UTC_07_00_TO_12_59",
            "session_wib": "14:00_TO_19:59_WIB",
            "source_selection": "V395_SESSION_LONDON",
            "execution_geometry": "V394_UNCHANGED",
        },
        "source_shards": len(files),
        "raw_sweep_trades": len(raw),
        "raw_london_trades": len(london),
        "max10_overlap_rejects": overlap_rejects,
        "overall": overall,
        "H1_2026": h1,
        "H2_2026_TO_DATE": h2,
        "gate": {
            "min_total_trades": MIN_TOTAL_TRADES,
            "min_pf_strict_gt": MIN_PF,
            "min_expectancy_r_strict_gt": MIN_EXPECTANCY_R,
            "max_drawdown_r_lte": MAX_DRAWDOWN_R,
            "min_subperiod_trades": MIN_SUBPERIOD_TRADES,
            "min_subperiod_pf_strict_gt": MIN_SUBPERIOD_PF,
            "min_subperiod_expectancy_r_strict_gt": MIN_SUBPERIOD_EXPECTANCY_R,
        },
        "checks": checks,
        "passed": passed,
        "decision": "V396_HOLDOUT_PASS_CANDIDATE_FOR_DEMO_SHADOW" if passed else "V396_HOLDOUT_REJECT",
        "execution_authority": False,
        "demo_auto_execution": False,
        "live_execution_enabled": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("V396_HOLDOUT=" + json.dumps(payload, sort_keys=True), flush=True)
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--inputs", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    run(args.inputs, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
