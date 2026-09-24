from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from statistics import median
from typing import Any

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar
from .research_xau_event_reaction_v193 import reaction_metrics_from_bars
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_xau_event_parity_v193"
CONTRACT = "XAU_EVENT_REACTION_PARITY_V193_1"
SYMBOL = "XAUUSD"
MAX_EVENTS = 60
MIN_PARITY_EVENTS = 50
MIN_PARITY_COVERAGE = 0.90
MIN_DIRECTIONAL_AGREEMENT = {
    "5m": 0.75,
    "15m": 0.80,
    "30m": 0.80,
}
MAX_MEDIAN_ABS_ATR_DIFFERENCE_15M = 1.0


def _f(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if isfinite(x) else None


def _sign(value: float | None) -> str | None:
    if value is None:
        return None
    if value > 0:
        return "UP"
    if value < 0:
        return "DOWN"
    return "FLAT"


def _reaction(rows: tuple[Bar, ...], event_at: datetime) -> dict[str, Any]:
    metrics = reaction_metrics_from_bars(rows, event_at=event_at)
    if metrics is None:
        return {}
    pre_context = dict(metrics.get("pre_context") or {})
    wanted = {
        "reference_price",
        "bar_interval_minutes",
        "r5m_points",
        "r5m_atr",
        "r15m_points",
        "r15m_atr",
        "r30m_points",
        "r30m_atr",
        "r60m_points",
        "r60m_atr",
    }
    output = {
        key: value
        for key, value in metrics.items()
        if key in wanted
    }
    output["atr14"] = _f(pre_context.get("atr14"))
    output["pre_last_close"] = _f(pre_context.get("last_close"))
    return output


def _load_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text())
    rows = list(payload.get("reactions") or [])
    selected = []
    for row in rows:
        raw_at = row.get("scheduled_at")
        if not raw_at:
            continue
        try:
            at = datetime.fromisoformat(str(raw_at).replace("Z", "+00:00"))
        except ValueError:
            continue
        if at.tzinfo is None:
            continue
        if at.year < 2024:
            continue
        if str(row.get("family") or "") == "MULTI_EVENT_CLUSTER":
            continue
        selected.append(dict(row))
    selected.sort(key=lambda row: str(row.get("scheduled_at") or ""), reverse=True)
    return selected[:MAX_EVENTS]


def parity_validation(
    *,
    attempted: int,
    available: int,
    horizon_stats: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    coverage = None if attempted == 0 else available / attempted
    gate_checks = {
        "minimum_events": available >= MIN_PARITY_EVENTS,
        "minimum_coverage": (
            coverage is not None and coverage >= MIN_PARITY_COVERAGE
        ),
        "agreement_5m": (
            horizon_stats["5m"]["directional_agreement"] is not None
            and horizon_stats["5m"]["directional_agreement"]
            >= MIN_DIRECTIONAL_AGREEMENT["5m"]
        ),
        "agreement_15m": (
            horizon_stats["15m"]["directional_agreement"] is not None
            and horizon_stats["15m"]["directional_agreement"]
            >= MIN_DIRECTIONAL_AGREEMENT["15m"]
        ),
        "agreement_30m": (
            horizon_stats["30m"]["directional_agreement"] is not None
            and horizon_stats["30m"]["directional_agreement"]
            >= MIN_DIRECTIONAL_AGREEMENT["30m"]
        ),
        "atr_difference_15m": (
            horizon_stats["15m"]["median_abs_atr_difference"] is not None
            and horizon_stats["15m"]["median_abs_atr_difference"]
            <= MAX_MEDIAN_ABS_ATR_DIFFERENCE_15M
        ),
    }
    passed = all(gate_checks.values())
    descriptive_available = (
        available >= MIN_PARITY_EVENTS
        and coverage is not None
        and coverage >= MIN_PARITY_COVERAGE
    )
    decision = (
        "PARITY_VALIDATED"
        if passed
        else "PARITY_DESCRIPTIVE_AVAILABLE"
        if descriptive_available
        else "PARITY_INSUFFICIENT"
    )
    return {
        "passed": passed,
        "decision": decision,
        "coverage": coverage,
        "checks": gate_checks,
        "thresholds": {
            "minimum_events": MIN_PARITY_EVENTS,
            "minimum_coverage": MIN_PARITY_COVERAGE,
            "minimum_directional_agreement": MIN_DIRECTIONAL_AGREEMENT,
            "maximum_median_abs_atr_difference_15m": (
                MAX_MEDIAN_ABS_ATR_DIFFERENCE_15M
            ),
        },
    }


def _compare(rows: list[dict[str, Any]], feed) -> dict[str, Any]:
    attempted = 0
    available = 0
    missing = 0
    horizons = {
        5: {
            "agree": 0,
            "n": 0,
            "diffs": [],
            "point_agree": 0,
            "point_n": 0,
            "point_diffs": [],
        },
        15: {
            "agree": 0,
            "n": 0,
            "diffs": [],
            "point_agree": 0,
            "point_n": 0,
            "point_diffs": [],
        },
        30: {
            "agree": 0,
            "n": 0,
            "diffs": [],
            "point_agree": 0,
            "point_n": 0,
            "point_diffs": [],
        },
        60: {
            "agree": 0,
            "n": 0,
            "diffs": [],
            "point_agree": 0,
            "point_n": 0,
            "point_diffs": [],
        },
    }
    atr_ratios: list[float] = []
    reference_price_diffs: list[float] = []
    bar_interval_pairs = 0
    bar_interval_mismatches = 0
    samples: list[dict[str, Any]] = []

    for row in rows:
        attempted += 1
        event_at = datetime.fromisoformat(
            str(row["scheduled_at"]).replace("Z", "+00:00")
        ).astimezone(UTC)
        try:
            bars = tuple(
                feed.historical_bars(
                    SYMBOL,
                    "M1",
                    from_time=event_at - timedelta(hours=6),
                    to_time=event_at + timedelta(hours=2),
                    count=800,
                )
            )
        except Exception:
            missing += 1
            continue
        ctrader = _reaction(bars, event_at)
        if not ctrader:
            missing += 1
            continue
        available += 1

        reference_context = dict(row.get("pre_context") or {})
        reference_price = _f(row.get("reference_price"))
        ctrader_price = _f(ctrader.get("reference_price"))
        reference_atr14 = _f(reference_context.get("atr14"))
        ctrader_atr14 = _f(ctrader.get("atr14"))
        reference_interval = _f(row.get("bar_interval_minutes"))
        ctrader_interval = _f(ctrader.get("bar_interval_minutes"))

        if reference_price is not None and ctrader_price is not None:
            reference_price_diffs.append(abs(ctrader_price - reference_price))
        if (
            reference_atr14 is not None
            and ctrader_atr14 is not None
            and reference_atr14 > 0
            and ctrader_atr14 > 0
        ):
            atr_ratios.append(ctrader_atr14 / reference_atr14)
        if reference_interval is not None and ctrader_interval is not None:
            bar_interval_pairs += 1
            bar_interval_mismatches += int(
                abs(reference_interval - ctrader_interval) > 1e-9
            )

        sample = {
            "scheduled_at": event_at.isoformat(),
            "family": row.get("family"),
            "attribution": row.get("attribution"),
            "reference_source": row.get("price_source"),
            "reference_price": reference_price,
            "ctrader_price": ctrader_price,
            "reference_atr14": reference_atr14,
            "ctrader_atr14": ctrader_atr14,
            "reference_bar_interval_minutes": reference_interval,
            "ctrader_bar_interval_minutes": ctrader_interval,
            "reference": {},
            "ctrader": {},
        }
        for minutes in (5, 15, 30, 60):
            atr_key = f"r{minutes}m_atr"
            points_key = f"r{minutes}m_points"
            reference_value = _f(row.get(atr_key))
            ctrader_value = _f(ctrader.get(atr_key))
            reference_points = _f(row.get(points_key))
            ctrader_points = _f(ctrader.get(points_key))
            sample["reference"][atr_key] = reference_value
            sample["ctrader"][atr_key] = ctrader_value
            sample["reference"][points_key] = reference_points
            sample["ctrader"][points_key] = ctrader_points

            stats = horizons[minutes]
            if reference_points is not None and ctrader_points is not None:
                stats["point_n"] += 1
                stats["point_agree"] += int(
                    _sign(reference_points) == _sign(ctrader_points)
                )
                stats["point_diffs"].append(
                    abs(reference_points - ctrader_points)
                )

            if reference_value is None or ctrader_value is None:
                continue
            stats["n"] += 1
            stats["agree"] += int(_sign(reference_value) == _sign(ctrader_value))
            stats["diffs"].append(abs(reference_value - ctrader_value))
        samples.append(sample)

    horizon_stats = {}
    for minutes, stats in horizons.items():
        diffs = list(stats["diffs"])
        n = int(stats["n"])
        point_diffs = list(stats["point_diffs"])
        point_n = int(stats["point_n"])
        horizon_stats[f"{minutes}m"] = {
            "n": n,
            "directional_agreement": None if n == 0 else stats["agree"] / n,
            "median_abs_atr_difference": None if not diffs else median(diffs),
            "point_n": point_n,
            "point_directional_agreement": (
                None if point_n == 0 else stats["point_agree"] / point_n
            ),
            "median_abs_point_difference": (
                None if not point_diffs else median(point_diffs)
            ),
            "point_sign_reversals": (
                None if point_n == 0 else point_n - int(stats["point_agree"])
            ),
        }

    forensic_summary = {
        "median_abs_reference_price_difference": (
            None if not reference_price_diffs else median(reference_price_diffs)
        ),
        "median_ctrader_to_reference_atr14_ratio": (
            None if not atr_ratios else median(atr_ratios)
        ),
        "bar_interval_pairs": bar_interval_pairs,
        "bar_interval_mismatches": bar_interval_mismatches,
        "interpretation": (
            "Diagnostics only: separate raw-point, ATR-denominator, price-level, "
            "and bar-interval mismatches without changing preregistered parity gates."
        ),
    }

    validation = parity_validation(
        attempted=attempted,
        available=available,
        horizon_stats=horizon_stats,
    )
    return {
        "attempted": attempted,
        "available": available,
        "missing": missing,
        "coverage": validation["coverage"],
        "horizons": horizon_stats,
        "forensics": forensic_summary,
        "samples": samples[:20],
        "validation_gate": {
            "passed": validation["passed"],
            "checks": validation["checks"],
            "thresholds": validation["thresholds"],
        },
        "decision": validation["decision"],
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def run() -> int:
    raw = os.getenv(
        "XAU_V193_FULL_ARTIFACT",
        "artifacts/xau-event-reaction-v193-full.json",
    ).strip()
    path = Path(raw)
    if not path.exists():
        raise SystemExit(f"XAU_V193_FULL_ARTIFACT_NOT_FOUND:{path}")

    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V193_PARITY_DEMO_ONLY")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_V193_PARITY_SYMBOL_NOT_CONFIGURED")

    source_rows = _load_rows(path)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        result = _compare(source_rows, feed)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    details = {
        "contract": CONTRACT,
        "observed_at": datetime.now(tz=UTC).isoformat(),
        "source_artifact": str(path),
        "source_rows": len(source_rows),
        "reference_sources": sorted(
            {
                str(row.get("price_source") or "UNKNOWN")
                for row in source_rows
            }
        ),
        "result": result,
        "policy_effect": "RESEARCH_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    healthy = result["decision"] in {
        "PARITY_DESCRIPTIVE_AVAILABLE",
        "PARITY_VALIDATED",
    }
    SupabaseOperationalStore.from_env().write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details=details,
    )
    print(
        "XAU_EVENT_PARITY_V193 "
        f"attempted={result['attempted']} available={result['available']} "
        f"coverage={result['coverage']} decision={result['decision']} "
        "execution_authority=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
