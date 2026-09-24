from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import hashlib
import os
from math import isfinite
from typing import Any, Iterable, Sequence

from .execution.policy import load_execution_policy
from .research_xau_zone_path_v174 import wilson_lower_bound
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_demo_xau_v201_reaction_ladder"
CONTRACT = "XAU_V201_REACTION_LADDER_AND_LATENCY"
EPISODE_TYPE = "V196_SHADOW_POCKET"
STRATEGY_ID = "XAU_BIDIRECTIONAL_M5_PATH_V196"
MAX_ROWS = 5000
ATR_RUNGS = (0.25, 0.50, 0.75, 1.00)

RESOLVED_PREFIXES = ("PROVEN_", "INVALIDATED_", "EXPIRED_")


def _dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row.get("metadata") or {})


def _physical_key(row: dict[str, Any]) -> str:
    meta = _metadata(row)
    source = dict(meta.get("source_zone") or {})
    direction = str(row.get("direction") or "").upper()
    low = _f(meta.get("pocket_low"))
    high = _f(meta.get("pocket_high"))
    origin = str(meta.get("pocket_origin_at") or "")
    source_zone_id = str(source.get("zone_id") or "")
    raw = "|".join(
        (
            direction,
            source_zone_id,
            origin,
            "NA" if low is None else f"{low:.8f}",
            "NA" if high is None else f"{high:.8f}",
        )
    )
    return "V201:PHYSICAL:" + hashlib.sha256(raw.encode()).hexdigest()[:28]


def _minutes(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None or end < start:
        return None
    return (end - start).total_seconds() / 60.0


def _is_resolved(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "")
    return status.startswith(RESOLVED_PREFIXES)


def _target_version(row: dict[str, Any]) -> dict[str, Any]:
    meta = _metadata(row)
    return {
        "episode_key": row.get("episode_key"),
        "role": meta.get("leg_role"),
        "mapped_at": row.get("observed_at"),
        "reaction_target": _f(meta.get("reaction_target") or row.get("tp1_price")),
        "terminal_target": _f(row.get("tp2_price")),
        "reaction_hit": bool(row.get("tp1_hit")),
        "terminal_hit": bool(row.get("tp2_hit")),
        "status": row.get("status"),
    }


def collapse_physical_pockets(
    rows: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_physical_key(row)].append(dict(row))

    output: list[dict[str, Any]] = []
    for key, group in grouped.items():
        group.sort(key=lambda row: _dt(row.get("observed_at")) or datetime.max.replace(tzinfo=UTC))
        first = group[0]
        first_meta = _metadata(first)
        source = dict(first_meta.get("source_zone") or {})
        direction = str(first.get("direction") or "").upper()
        low = _f(first_meta.get("pocket_low"))
        high = _f(first_meta.get("pocket_high"))
        if direction not in {"LONG", "SHORT"} or low is None or high is None:
            continue

        first_seen = _dt(first.get("observed_at"))
        touches = [
            _dt(row.get("first_touch_at"))
            for row in group
            if _dt(row.get("first_touch_at")) is not None
        ]
        first_touch = min(touches) if touches else None

        role_timeline: list[dict[str, Any]] = []
        seen_role_events: set[tuple[str, str]] = set()
        for row in group:
            meta = _metadata(row)
            role = str(meta.get("leg_role") or "UNKNOWN")
            observed = _dt(row.get("observed_at"))
            stamp = "" if observed is None else observed.isoformat()
            token = (role, stamp)
            if token in seen_role_events:
                continue
            seen_role_events.add(token)
            role_timeline.append({"role": role, "observed_at": stamp or None})

        current_times = [
            _dt(row.get("observed_at"))
            for row in group
            if str(_metadata(row).get("leg_role") or "") == "current_leg"
            and _dt(row.get("observed_at")) is not None
        ]
        first_current = min(current_times) if current_times else None

        mfe = max((_f(row.get("mfe_points")) or 0.0 for row in group), default=0.0)
        mae = max((_f(row.get("mae_points")) or 0.0 for row in group), default=0.0)
        atr = _f(source.get("atr_points"))
        midpoint = (low + high) / 2.0
        rung_results: list[dict[str, Any]] = []
        for multiple in ATR_RUNGS:
            points = None if atr is None else multiple * atr
            price = None
            hit = False
            if points is not None:
                price = midpoint + points if direction == "LONG" else midpoint - points
                hit = mfe >= points
            rung_results.append(
                {
                    "atr_multiple": multiple,
                    "points": points,
                    "price": price,
                    "hit": hit,
                }
            )

        resolved_rows = [row for row in group if _is_resolved(row)]
        resolved = bool(resolved_rows)
        if resolved_rows:
            resolved_rows.sort(
                key=lambda row: _dt(row.get("outcome_at"))
                or _dt(row.get("observed_at"))
                or datetime.max.replace(tzinfo=UTC)
            )
            physical_status = str(resolved_rows[0].get("status") or "RESOLVED")
            outcome_at = _dt(resolved_rows[0].get("outcome_at"))
        else:
            latest = group[-1]
            physical_status = str(latest.get("status") or "PENDING")
            outcome_at = None

        output.append(
            {
                "physical_key": key,
                "direction": direction,
                "pocket_low": low,
                "pocket_high": high,
                "pocket_mid": midpoint,
                "pocket_origin_at": first_meta.get("pocket_origin_at"),
                "source_zone_id": source.get("zone_id"),
                "source_timeframe": source.get("timeframe"),
                "source_atr_points": atr,
                "first_seen_at": None if first_seen is None else first_seen.isoformat(),
                "first_seen_role": (
                    None if not role_timeline else role_timeline[0].get("role")
                ),
                "first_current_leg_at": (
                    None if first_current is None else first_current.isoformat()
                ),
                "first_touch_at": None if first_touch is None else first_touch.isoformat(),
                "premap_lead_minutes": _minutes(first_seen, first_touch),
                "current_leg_lead_minutes": _minutes(first_current, first_touch),
                "premapped_before_touch": bool(
                    first_seen is not None
                    and first_touch is not None
                    and first_seen < first_touch
                ),
                "role_transition_before_touch": bool(
                    first_current is not None
                    and first_touch is not None
                    and first_current < first_touch
                ),
                "role_timeline": role_timeline,
                "episode_keys": [row.get("episode_key") for row in group],
                "target_versions": [_target_version(row) for row in group],
                "status": physical_status,
                "resolved": resolved,
                "outcome_at": None if outcome_at is None else outcome_at.isoformat(),
                "mfe_points": mfe,
                "mae_points": mae,
                "reaction_ladder": rung_results,
                "strict_immutable": any(
                    bool(_metadata(row).get("strict_analytics_eligible"))
                    and str(_metadata(row).get("evidence_cohort") or "") == "IMMUTABLE_V198"
                    for row in group
                ),
            }
        )

    output.sort(
        key=lambda item: _dt(item.get("first_seen_at"))
        or datetime.min.replace(tzinfo=UTC)
    )
    return tuple(output)


def _rung_summary(
    pockets: Sequence[dict[str, Any]],
    *,
    multiple: float,
) -> dict[str, Any]:
    touched = [p for p in pockets if _dt(p.get("first_touch_at")) is not None]
    hits = [
        p
        for p in touched
        if next(
            (
                bool(rung.get("hit"))
                for rung in list(p.get("reaction_ladder") or [])
                if float(rung.get("atr_multiple") or -1.0) == float(multiple)
            ),
            False,
        )
    ]
    resolved_misses = [
        p
        for p in touched
        if bool(p.get("resolved"))
        and p not in hits
    ]
    decisive_n = len(hits) + len(resolved_misses)
    pending_censored = len(touched) - decisive_n
    precision = None if decisive_n == 0 else len(hits) / decisive_n
    wilson = None if decisive_n == 0 else wilson_lower_bound(len(hits), decisive_n)
    return {
        "atr_multiple": multiple,
        "touched": len(touched),
        "confirmed_hits": len(hits),
        "resolved_misses": len(resolved_misses),
        "pending_censored": pending_censored,
        "decisive_n": decisive_n,
        "precision_decisive": precision,
        "wilson_lower_95": wilson,
    }


def build_reaction_ladder_analytics(
    rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    pockets = collapse_physical_pockets(rows)
    strict = tuple(p for p in pockets if bool(p.get("strict_immutable")))
    touched = [p for p in pockets if _dt(p.get("first_touch_at")) is not None]
    premapped = [p for p in touched if bool(p.get("premapped_before_touch"))]

    lead_values = [
        float(p["premap_lead_minutes"])
        for p in premapped
        if p.get("premap_lead_minutes") is not None
    ]
    lead_values.sort()
    median_lead = (
        None
        if not lead_values
        else lead_values[len(lead_values) // 2]
        if len(lead_values) % 2 == 1
        else (lead_values[len(lead_values) // 2 - 1] + lead_values[len(lead_values) // 2]) / 2.0
    )

    return {
        "contract": CONTRACT,
        "physical_pockets": len(pockets),
        "strict_physical_pockets": len(strict),
        "touched_physical_pockets": len(touched),
        "premapped_before_touch": len(premapped),
        "premap_rate_given_touch": None if not touched else len(premapped) / len(touched),
        "median_premap_lead_minutes": median_lead,
        "all_ladder": [_rung_summary(pockets, multiple=x) for x in ATR_RUNGS],
        "strict_ladder": [_rung_summary(strict, multiple=x) for x in ATR_RUNGS],
        "latest_physical_pockets": list(pockets[-12:]),
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "interpretation": (
            "V201 separates zone localization from reaction magnitude. A pocket can be a "
            "valid local-reaction zone even if the mapped path target later fails. "
            "Physical-pocket deduplication also tracks next-leg to current-leg role changes "
            "so pre-mapped pockets are not mistaken for late discoveries."
        ),
    }


def _ledger_rows(store: SupabaseOperationalStore) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("xau_outcome_ledger")
        .select(
            "episode_key,episode_type,strategy_id,observed_at,direction,status,"
            "first_touch_at,outcome_at,tp1_price,tp2_price,tp1_hit,tp2_hit,"
            "mfe_points,mae_points,metadata"
        )
        .eq("episode_type", EPISODE_TYPE)
        .eq("strategy_id", STRATEGY_ID)
        .order("observed_at", desc=False)
        .limit(MAX_ROWS)
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V201_REACTION_LADDER_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V201_REACTION_LADDER_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    rows: tuple[dict[str, Any], ...] = ()
    analytics: dict[str, Any] = {}
    error: str | None = None
    try:
        rows = _ledger_rows(store)
        analytics = build_reaction_ladder_analytics(rows)
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"

    healthy = error is None
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            **analytics,
            "environment": "DEMO",
            "ledger_rows": len(rows),
            "error": error,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
        },
    )
    print(
        "CTRADER_DEMO_XAU_V201_REACTION_LADDER "
        f"healthy={healthy} rows={len(rows)} "
        f"physical={analytics.get('physical_pockets', 0)} "
        f"touched={analytics.get('touched_physical_pockets', 0)} "
        f"premapped={analytics.get('premapped_before_touch', 0)} "
        f"error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
