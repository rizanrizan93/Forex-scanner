from __future__ import annotations

from collections import defaultdict
from math import isfinite, log, sqrt
from typing import Any, Iterable, Sequence


RESEARCH_VERSION = "XAU_DEPTH_COMPETING_RISK_V281_1"
ARTIFACT_CONTRACT = "XAU_DEPTH_COMPETING_RISK_V281_1_EVIDENCE_1"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
PROMOTION_AUTHORITY = False
MIN_CELL_N = 50
Z_95 = 1.959963984540054


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _wilson_interval(successes: int, total: int) -> tuple[float | None, float | None]:
    if total <= 0:
        return None, None
    p = successes / total
    z2 = Z_95 * Z_95
    denom = 1.0 + z2 / total
    center = (p + z2 / (2.0 * total)) / denom
    margin = (
        Z_95
        * sqrt((p * (1.0 - p) / total) + z2 / (4.0 * total * total))
        / denom
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _band_name(index: int) -> str:
    return f"{index * 10:02d}-{(index + 1) * 10:02d}%"


def _era(year: int) -> str:
    if year <= 2018:
        return "2012_2018"
    if year <= 2024:
        return "2019_2024"
    return "2025_2026"


def fit_volatility_thresholds(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, float]]:
    by_tf: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if int(row.get("year") or 0) > 2024:
            continue
        atr = _f(row.get("atr_points"))
        tf = str(row.get("timeframe") or "").upper()
        if atr is not None and atr > 0 and tf:
            by_tf[tf].append(atr)

    out: dict[str, dict[str, float]] = {}
    for tf, values in by_tf.items():
        values = sorted(values)
        if not values:
            continue

        def q(frac: float) -> float:
            pos = frac * (len(values) - 1)
            lo = int(pos)
            hi = min(len(values) - 1, lo + 1)
            w = pos - lo
            return values[lo] * (1.0 - w) + values[hi] * w

        out[tf] = {"low_cut": q(1.0 / 3.0), "high_cut": q(2.0 / 3.0)}
    return out


def volatility_bucket(
    row: dict[str, Any],
    thresholds: dict[str, dict[str, float]],
) -> str:
    tf = str(row.get("timeframe") or "").upper()
    atr = _f(row.get("atr_points"))
    cuts = dict(thresholds.get(tf) or {})
    low = _f(cuts.get("low_cut"))
    high = _f(cuts.get("high_cut"))
    if atr is None or low is None or high is None:
        return "UNKNOWN"
    if atr <= low:
        return "LOW"
    if atr >= high:
        return "HIGH"
    return "MID"


def pressure_bucket(row: dict[str, Any]) -> str:
    state = str(row.get("transition_state") or "UNAVAILABLE").upper()
    if state in {"STRONG_FADE", "FADE", "BALANCE_OR_CONTROL_FLIP", "REACCELERATION", "STABLE"}:
        return state
    return "UNAVAILABLE"


def _resolved_outcome(row: dict[str, Any]) -> str:
    reaction = bool(row.get("reaction_hit"))
    broken = bool(row.get("break_hit"))
    if reaction and not broken:
        return "REVERSAL_050"
    if broken:
        return "BREAK_INVALID"
    return "STALL_UNRESOLVED"


def band_competing_risk(
    rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    episodes = [dict(row) for row in rows]
    result: list[dict[str, Any]] = []
    for index in range(10):
        lower = index / 10.0
        upper = (index + 1) / 10.0
        at_risk = [
            row
            for row in episodes
            if (_f(row.get("max_depth_reached")) or 0.0) + 1e-12 >= lower
        ]
        n = len(at_risk)
        reversals = sum(_resolved_outcome(row) == "REVERSAL_050" for row in at_risk)
        breaks = sum(_resolved_outcome(row) == "BREAK_INVALID" for row in at_risk)
        stalls = n - reversals - breaks
        rev_lo, rev_hi = _wilson_interval(reversals, n)
        brk_lo, brk_hi = _wilson_interval(breaks, n)
        resolved = reversals + breaks
        result.append(
            {
                "band": _band_name(index),
                "band_index": index,
                "lower_depth": lower,
                "upper_depth": upper,
                "at_risk": n,
                "reversal_050": reversals,
                "break_invalid": breaks,
                "stall_unresolved": stalls,
                "p_reversal_given_reached_band": None if n == 0 else reversals / n,
                "p_break_given_reached_band": None if n == 0 else breaks / n,
                "p_stall_given_reached_band": None if n == 0 else stalls / n,
                "reversal_wilson_95": [rev_lo, rev_hi],
                "break_wilson_95": [brk_lo, brk_hi],
                "resolved_n": resolved,
                "break_share_of_resolved": (
                    None if resolved == 0 else breaks / resolved
                ),
                "reversal_share_of_resolved": (
                    None if resolved == 0 else reversals / resolved
                ),
            }
        )
    return result


def _filter(rows: Iterable[dict[str, Any]], **criteria: str) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        ok = True
        for key, expected in criteria.items():
            if str(row.get(key) or "") != expected:
                ok = False
                break
        if ok:
            out.append(dict(row))
    return out


def grouped_competing_risk(
    rows: Sequence[dict[str, Any]],
    *,
    volatility_thresholds: dict[str, dict[str, float]],
) -> dict[str, Any]:
    enriched = []
    for raw in rows:
        row = dict(raw)
        row["era"] = _era(int(row.get("year") or 0))
        row["volatility_bucket"] = volatility_bucket(row, volatility_thresholds)
        row["pressure_bucket"] = pressure_bucket(row)
        row["touch_scope"] = "FIRST_TOUCH"
        enriched.append(row)

    output: dict[str, Any] = {
        "ALL": band_competing_risk(enriched),
        "touch_scope": {
            "FIRST_TOUCH": {
                "n": len(enriched),
                "bands": band_competing_risk(enriched),
            },
            "RETEST": {
                "n": 0,
                "bands": [],
                "status": "NOT_MEASURED_BY_V225_V250_FIRST_TOUCH_DATASET",
            },
        },
        "timeframe_direction": {},
        "era": {},
        "session": {},
        "volatility": {},
        "pressure": {},
    }
    for tf in ("H4", "H1", "M15"):
        output["timeframe_direction"][tf] = {}
        tf_rows = [row for row in enriched if str(row.get("timeframe") or "").upper() == tf]
        for direction in ("ALL", "LONG", "SHORT"):
            subset = tf_rows if direction == "ALL" else [
                row for row in tf_rows if str(row.get("direction") or "").upper() == direction
            ]
            output["timeframe_direction"][tf][direction] = {
                "n": len(subset),
                "bands": band_competing_risk(subset),
            }

    for name in ("2012_2018", "2019_2024", "2025_2026"):
        subset = [row for row in enriched if row["era"] == name]
        output["era"][name] = {"n": len(subset), "bands": band_competing_risk(subset)}

    for name in sorted({str(row.get("session") or "UNAVAILABLE") for row in enriched}):
        subset = [row for row in enriched if str(row.get("session") or "UNAVAILABLE") == name]
        output["session"][name] = {"n": len(subset), "bands": band_competing_risk(subset)}

    for name in ("LOW", "MID", "HIGH", "UNKNOWN"):
        subset = [row for row in enriched if row["volatility_bucket"] == name]
        output["volatility"][name] = {"n": len(subset), "bands": band_competing_risk(subset)}

    for name in ("STRONG_FADE", "FADE", "BALANCE_OR_CONTROL_FLIP", "REACCELERATION", "STABLE", "UNAVAILABLE"):
        subset = [row for row in enriched if row["pressure_bucket"] == name]
        output["pressure"][name] = {"n": len(subset), "bands": band_competing_risk(subset)}

    return output


def _train_cell_key(row: dict[str, Any], band_index: int) -> tuple[str, ...]:
    return (
        str(row.get("timeframe") or "").upper(),
        str(row.get("direction") or "").upper(),
        str(row.get("session") or "UNAVAILABLE"),
        str(row.get("volatility_bucket") or "UNKNOWN"),
        str(row.get("pressure_bucket") or "UNAVAILABLE"),
        str(band_index),
    )


def _fallback_key(row: dict[str, Any], band_index: int) -> tuple[str, ...]:
    return (
        str(row.get("timeframe") or "").upper(),
        str(row.get("direction") or "").upper(),
        str(band_index),
    )


def _probability_table(rows: Sequence[dict[str, Any]], key_fn) -> dict[tuple[str, ...], dict[str, float]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        max_depth = _f(row.get("max_depth_reached")) or 0.0
        for band_index in range(10):
            if max_depth + 1e-12 < band_index / 10.0:
                break
            groups[key_fn(row, band_index)].append(row)

    out: dict[tuple[str, ...], dict[str, float]] = {}
    for key, values in groups.items():
        n = len(values)
        rev = sum(_resolved_outcome(row) == "REVERSAL_050" for row in values)
        brk = sum(_resolved_outcome(row) == "BREAK_INVALID" for row in values)
        out[key] = {
            "n": float(n),
            "p_reversal": rev / n if n else 0.0,
            "p_break": brk / n if n else 0.0,
        }
    return out


def _binary_metrics(y: list[int], p: list[float]) -> dict[str, Any]:
    if not y:
        return {"n": 0, "brier": None, "log_loss": None}
    eps = 1e-9
    brier = sum((yy - pp) ** 2 for yy, pp in zip(y, p)) / len(y)
    loss = -sum(
        yy * log(max(eps, min(1.0 - eps, pp)))
        + (1 - yy) * log(max(eps, min(1.0 - eps, 1.0 - pp)))
        for yy, pp in zip(y, p)
    ) / len(y)
    return {"n": len(y), "brier": brier, "log_loss": loss}


def evaluate_oos(
    rows: Sequence[dict[str, Any]],
    *,
    volatility_thresholds: dict[str, dict[str, float]],
) -> dict[str, Any]:
    enriched = []
    for raw in rows:
        row = dict(raw)
        row["volatility_bucket"] = volatility_bucket(row, volatility_thresholds)
        row["pressure_bucket"] = pressure_bucket(row)
        enriched.append(row)

    train = [row for row in enriched if int(row.get("year") or 0) <= 2024]
    test = [row for row in enriched if int(row.get("year") or 0) >= 2025]
    exact = _probability_table(train, _train_cell_key)
    fallback = _probability_table(train, _fallback_key)

    exposures: list[dict[str, Any]] = []
    for row in test:
        outcome = _resolved_outcome(row)
        max_depth = _f(row.get("max_depth_reached")) or 0.0
        for band_index in range(10):
            lower = band_index / 10.0
            if max_depth + 1e-12 < lower:
                break
            cell = exact.get(_train_cell_key(row, band_index))
            source = "EXACT_TF_DIR_SESSION_VOL_PRESSURE"
            if cell is None or int(cell.get("n") or 0) < MIN_CELL_N:
                cell = fallback.get(_fallback_key(row, band_index))
                source = "FALLBACK_TF_DIR"
            if cell is None or int(cell.get("n") or 0) < MIN_CELL_N:
                continue
            p_rev = float(cell["p_reversal"])
            p_brk = float(cell["p_break"])
            exposures.append(
                {
                    "band_index": band_index,
                    "band": _band_name(band_index),
                    "outcome": outcome,
                    "p_reversal": p_rev,
                    "p_break": p_brk,
                    "training_n": int(cell["n"]),
                    "source": source,
                }
            )

    resolved = [x for x in exposures if x["outcome"] in {"REVERSAL_050", "BREAK_INVALID"}]
    correct = sum(
        (
            x["p_break"] > x["p_reversal"]
            and x["outcome"] == "BREAK_INVALID"
        )
        or (
            x["p_reversal"] >= x["p_break"]
            and x["outcome"] == "REVERSAL_050"
        )
        for x in resolved
    )
    break_y = [1 if x["outcome"] == "BREAK_INVALID" else 0 for x in resolved]
    break_p = [float(x["p_break"]) for x in resolved]
    rev_y = [1 if x["outcome"] == "REVERSAL_050" else 0 for x in resolved]
    rev_p = [float(x["p_reversal"]) for x in resolved]

    per_band: dict[str, Any] = {}
    for band_index in range(10):
        band_rows = [x for x in resolved if int(x["band_index"]) == band_index]
        if not band_rows:
            per_band[_band_name(band_index)] = {"n": 0, "accuracy": None}
            continue
        band_correct = sum(
            (
                x["p_break"] > x["p_reversal"]
                and x["outcome"] == "BREAK_INVALID"
            )
            or (
                x["p_reversal"] >= x["p_break"]
                and x["outcome"] == "REVERSAL_050"
            )
            for x in band_rows
        )
        per_band[_band_name(band_index)] = {
            "n": len(band_rows),
            "accuracy": band_correct / len(band_rows),
            "break_metrics": _binary_metrics(
                [1 if x["outcome"] == "BREAK_INVALID" else 0 for x in band_rows],
                [float(x["p_break"]) for x in band_rows],
            ),
        }

    return {
        "train_years": "2012-2024",
        "test_years": "2025-2026",
        "train_episode_count": len(train),
        "test_episode_count": len(test),
        "test_band_exposures": len(exposures),
        "resolved_exposures": len(resolved),
        "classification_accuracy_resolved_exposures": (
            None if not resolved else correct / len(resolved)
        ),
        "break_probability_metrics": _binary_metrics(break_y, break_p),
        "reversal_probability_metrics": _binary_metrics(rev_y, rev_p),
        "per_band": per_band,
        "minimum_training_cell_n": MIN_CELL_N,
        "note": (
            "Band exposures from the same episode are correlated and are not trade counts. "
            "This OOS test evaluates conditional event forecasts only, not strategy PnL."
        ),
    }
