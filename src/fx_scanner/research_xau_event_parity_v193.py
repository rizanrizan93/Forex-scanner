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
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_xau_event_parity_v193"
CONTRACT = "XAU_EVENT_REACTION_PARITY_V193_1"
SYMBOL = "XAUUSD"
MAX_EVENTS = 60


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


def _atr14(rows: tuple[Bar, ...], event_at: datetime) -> float | None:
    before = [row for row in rows if row.timestamp < event_at]
    if len(before) < 15:
        return None
    sample = before[-15:]
    trs = []
    for i in range(1, len(sample)):
        row = sample[i]
        prev = sample[i - 1]
        tr = max(
            float(row.high) - float(row.low),
            abs(float(row.high) - float(prev.close)),
            abs(float(row.low) - float(prev.close)),
        )
        trs.append(tr)
    if len(trs) < 14:
        return None
    atr = sum(trs[-14:]) / 14.0
    return atr if atr > 0 else None


def _reaction(rows: tuple[Bar, ...], event_at: datetime) -> dict[str, float | None]:
    ordered = tuple(sorted(rows, key=lambda row: row.timestamp))
    before = [row for row in ordered if row.timestamp < event_at]
    if not before:
        return {}
    p0 = float(before[-1].close)
    atr = _atr14(ordered, event_at)
    out: dict[str, float | None] = {}
    for minutes in (5, 15, 30, 60):
        target = event_at + timedelta(minutes=minutes)
        post = next((row for row in ordered if row.timestamp >= target), None)
        if post is None:
            out[f"r{minutes}m_atr"] = None
            continue
        change = float(post.close) - p0
        out[f"r{minutes}m_atr"] = None if atr is None else change / atr
    return out


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


def _compare(rows: list[dict[str, Any]], feed) -> dict[str, Any]:
    attempted = 0
    available = 0
    missing = 0
    horizons = {
        5: {"agree": 0, "n": 0, "diffs": []},
        15: {"agree": 0, "n": 0, "diffs": []},
        30: {"agree": 0, "n": 0, "diffs": []},
        60: {"agree": 0, "n": 0, "diffs": []},
    }
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
                    "M5",
                    from_time=event_at - timedelta(hours=6),
                    to_time=event_at + timedelta(hours=2),
                    count=300,
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

        sample = {
            "scheduled_at": event_at.isoformat(),
            "family": row.get("family"),
            "dukascopy": {},
            "ctrader": {},
        }
        for minutes in (5, 15, 30, 60):
            key = f"r{minutes}m_atr"
            d = _f(row.get(key))
            c = _f(ctrader.get(key))
            sample["dukascopy"][key] = d
            sample["ctrader"][key] = c
            if d is None or c is None:
                continue
            stats = horizons[minutes]
            stats["n"] += 1
            stats["agree"] += int(_sign(d) == _sign(c))
            stats["diffs"].append(abs(d - c))
        samples.append(sample)

    horizon_stats = {}
    for minutes, stats in horizons.items():
        diffs = list(stats["diffs"])
        n = int(stats["n"])
        horizon_stats[f"{minutes}m"] = {
            "n": n,
            "directional_agreement": None if n == 0 else stats["agree"] / n,
            "median_abs_atr_difference": None if not diffs else median(diffs),
        }

    return {
        "attempted": attempted,
        "available": available,
        "missing": missing,
        "coverage": None if attempted == 0 else available / attempted,
        "horizons": horizon_stats,
        "samples": samples[:20],
        "decision": (
            "PARITY_DESCRIPTIVE_AVAILABLE"
            if available >= 30
            else "PARITY_INSUFFICIENT"
        ),
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
        "result": result,
        "policy_effect": "RESEARCH_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    healthy = result["decision"] == "PARITY_DESCRIPTIVE_AVAILABLE"
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
