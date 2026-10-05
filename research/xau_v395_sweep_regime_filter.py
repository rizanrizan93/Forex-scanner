from __future__ import annotations

"""V395 causal regime-filter discovery over frozen V394 SWEEP_RECLAIM_M5 trades.

Purpose
-------
V394 showed an overall positive SWEEP_RECLAIM_M5 edge that was not stable across
2025 H1/H2. V395 does NOT change entry, stop, target, costs, or fills. It only
asks whether a small predeclared set of attributes already known at entry can
separate a stable subset.

Candidate filters are fixed before results and are deliberately one-dimensional
to limit overfit:
- zone timeframe: H1 or H4
- reversal direction: LONG or SHORT
- UTC session bucket: ASIA, LONDON, NEW_YORK, LATE_US
- zone width / ATR: <=0.50, (0.50,1.00], >1.00
- entry delay after touch: <=15m, (15m,60m], >60m

Promotion gate: >=50 total trades, >=20 trades in each 2025 half, expectancy
>+0.05R and PF>1.15 in EACH half. A passing candidate is then frozen for a
separate untouched 2026 holdout. Research only; no execution authority.
"""

import argparse
import glob
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable

SCHEMA = "XAU_V395_SWEEP_REGIME_FILTER_V1"
BASE_POLICY = "SWEEP_RECLAIM_M5"
MIN_TOTAL_TRADES = 50
MIN_HALF_TRADES = 20
MIN_HALF_EXPECTANCY_R = 0.05
MIN_HALF_PF = 1.15


def _dt(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _session(row: dict[str, Any]) -> str:
    h = _dt(row["entry_at"]).hour
    if 0 <= h < 7:
        return "ASIA"
    if 7 <= h < 13:
        return "LONDON"
    if 13 <= h < 21:
        return "NEW_YORK"
    return "LATE_US"


def _width_atr(row: dict[str, Any]) -> float | None:
    lo = _f(row.get("zone_low")); hi = _f(row.get("zone_high")); atr = _f(row.get("zone_atr"))
    if lo is None or hi is None or atr is None or atr <= 0:
        return None
    return abs(hi - lo) / atr


def _delay_minutes(row: dict[str, Any]) -> float:
    return max(0.0, (_dt(row["entry_at"]) - _dt(row["touch_at"])).total_seconds() / 60.0)


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0; peak = 0.0; dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dd


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted(rows, key=lambda x: str(x.get("entry_at") or ""))
    r = [float(x["r_multiple"]) for x in rows]
    wins = [x for x in r if x > 0]; losses = [x for x in r if x < 0]
    gp = sum(wins); gl = abs(sum(losses))
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
        "median_delay_minutes": None if not rows else median(_delay_minutes(x) for x in rows),
        "session_counts": dict(Counter(_session(x) for x in rows)),
        "zone_timeframe_counts": dict(Counter(str(x.get("zone_timeframe") or "") for x in rows)),
        "direction_counts": dict(Counter(str(x.get("direction") or "") for x in rows)),
    }


def _pf_pass(m: dict[str, Any]) -> bool:
    pf = m.get("profit_factor_r")
    if pf is None:
        return int(m.get("losses") or 0) == 0 and int(m.get("wins") or 0) > 0
    return float(pf) > MIN_HALF_PF


def _always(_: dict[str, Any]) -> bool: return True

FILTERS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "ALL": _always,
    "ZONE_H1": lambda r: str(r.get("zone_timeframe") or "").upper() == "H1",
    "ZONE_H4": lambda r: str(r.get("zone_timeframe") or "").upper() == "H4",
    "LONG_ONLY": lambda r: str(r.get("direction") or "").upper() == "LONG",
    "SHORT_ONLY": lambda r: str(r.get("direction") or "").upper() == "SHORT",
    "SESSION_ASIA": lambda r: _session(r) == "ASIA",
    "SESSION_LONDON": lambda r: _session(r) == "LONDON",
    "SESSION_NEW_YORK": lambda r: _session(r) == "NEW_YORK",
    "SESSION_LATE_US": lambda r: _session(r) == "LATE_US",
    "WIDTH_ATR_LE_0P50": lambda r: (_width_atr(r) is not None and _width_atr(r) <= 0.50),
    "WIDTH_ATR_0P50_1P00": lambda r: (_width_atr(r) is not None and 0.50 < _width_atr(r) <= 1.00),
    "WIDTH_ATR_GT_1P00": lambda r: (_width_atr(r) is not None and _width_atr(r) > 1.00),
    "DELAY_LE_15M": lambda r: _delay_minutes(r) <= 15.0,
    "DELAY_15_60M": lambda r: 15.0 < _delay_minutes(r) <= 60.0,
    "DELAY_GT_60M": lambda r: _delay_minutes(r) > 60.0,
}


def run(inputs: str, output: Path) -> dict[str, Any]:
    files = sorted(Path(p) for p in glob.glob(inputs))
    if not files:
        raise RuntimeError(f"No V394 shard files matched {inputs}")
    rows: list[dict[str, Any]] = []
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.extend(dict(x) for x in list(dict(payload.get("trades") or {}).get(BASE_POLICY) or []))
    rows.sort(key=lambda x: str(x.get("entry_at") or ""))

    results: dict[str, Any] = {}
    promotable: list[dict[str, Any]] = []
    for name, predicate in FILTERS.items():
        selected = [r for r in rows if predicate(r)]
        h1 = [r for r in selected if _dt(r["entry_at"]) < datetime(2025, 7, 1, tzinfo=timezone.utc)]
        h2 = [r for r in selected if _dt(r["entry_at"]) >= datetime(2025, 7, 1, tzinfo=timezone.utc)]
        overall_m = _metrics(selected); h1_m = _metrics(h1); h2_m = _metrics(h2)
        checks = {
            "min_total": overall_m["trades"] >= MIN_TOTAL_TRADES,
            "min_h1": h1_m["trades"] >= MIN_HALF_TRADES,
            "min_h2": h2_m["trades"] >= MIN_HALF_TRADES,
            "h1_expectancy": h1_m["expectancy_r"] is not None and h1_m["expectancy_r"] > MIN_HALF_EXPECTANCY_R,
            "h2_expectancy": h2_m["expectancy_r"] is not None and h2_m["expectancy_r"] > MIN_HALF_EXPECTANCY_R,
            "h1_pf": _pf_pass(h1_m),
            "h2_pf": _pf_pass(h2_m),
        }
        passed = all(checks.values())
        row = {"filter": name, "overall": overall_m, "H1": h1_m, "H2": h2_m, "checks": checks, "passed": passed}
        results[name] = row
        if passed:
            promotable.append(row)

    def rank(row: dict[str, Any]) -> tuple[float, float, float, float]:
        h1 = row["H1"]; h2 = row["H2"]; overall = row["overall"]
        min_exp = min(float(h1["expectancy_r"]), float(h2["expectancy_r"]))
        min_pf = min(float(h1["profit_factor_r"] or 999.0), float(h2["profit_factor_r"] or 999.0))
        return (min_exp, min_pf, float(overall["expectancy_r"]), -float(overall["max_drawdown_r"]))

    champion = max(promotable, key=rank)["filter"] if promotable else None
    payload = {
        "schema": SCHEMA,
        "source_policy": BASE_POLICY,
        "source_shards": len(files),
        "source_trades": len(rows),
        "predeclared_filters": list(FILTERS),
        "selection_gate": {
            "min_total_trades": MIN_TOTAL_TRADES,
            "min_half_trades": MIN_HALF_TRADES,
            "min_half_expectancy_r_strict_gt": MIN_HALF_EXPECTANCY_R,
            "min_half_pf_strict_gt": MIN_HALF_PF,
        },
        "results": results,
        "champion": champion,
        "decision": "FREEZE_V395_FILTER_FOR_2026_HOLDOUT" if champion else "REJECT_ALL_V395_FILTERS",
        "execution_authority": False,
        "demo_auto_execution": False,
        "live_execution_enabled": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("V395_SELECTION=" + json.dumps(payload, sort_keys=True), flush=True)
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
