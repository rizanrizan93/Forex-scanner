from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import os
from statistics import median
from typing import Any, Iterable, Sequence

from .execution.policy import load_execution_policy
from .research_xau_zone_path_v174 import wilson_lower_bound
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_demo_xau_v198_evidence_analytics"
CONTRACT = "XAU_V198_EVIDENCE_ANALYTICS"
EPISODE_TYPE = "V196_SHADOW_POCKET"
STRATEGY_ID = "XAU_BIDIRECTIONAL_M5_PATH_V196"
EXPLORATORY_MIN_RESOLVED_TOUCHES = 30
STATISTICAL_MIN_RESOLVED_TOUCHES = 50
TARGET_RAW_PRECISION = 0.80
TARGET_WILSON_LOWER = 0.70
MAX_ROWS = 5000

PENDING_STATUSES = {"ENROLLED_WAIT_TOUCH", "TOUCHED_PENDING"}
RESOLVED_AFTER_TOUCH = {
    "PROVEN_REACTION_TARGET",
    "PROVEN_TERMINAL_ZONE",
    "INVALIDATED_AFTER_TOUCH",
    "EXPIRED_AFTER_TOUCH",
}


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
        return float(value)
    except (TypeError, ValueError):
        return None


def _minutes(start: Any, end: Any) -> float | None:
    a = _dt(start)
    b = _dt(end)
    if a is None or b is None or b < a:
        return None
    return (b - a).total_seconds() / 60.0


def _median(values: Iterable[float | None]) -> float | None:
    parsed = [float(v) for v in values if v is not None]
    return None if not parsed else float(median(parsed))


def _mean(values: Iterable[float | None]) -> float | None:
    parsed = [float(v) for v in values if v is not None]
    return None if not parsed else sum(parsed) / len(parsed)


def _row_metadata(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row.get("metadata") or {})


def _strict(row: dict[str, Any]) -> bool:
    metadata = _row_metadata(row)
    return bool(
        metadata.get("immutable_forecast_geometry")
        and metadata.get("strict_analytics_eligible")
        and str(metadata.get("evidence_cohort") or "") == "IMMUTABLE_V198"
    )


def _liquidity_bucket(row: dict[str, Any]) -> str:
    source = dict(_row_metadata(row).get("source_zone") or {})
    liquidity = dict(source.get("liquidity") or {})
    n = int(liquidity.get("confluence_count") or 0)
    if n <= 0:
        return "LIQ_0"
    if n == 1:
        return "LIQ_1"
    return "LIQ_2_PLUS"


def _segment_values(row: dict[str, Any]) -> dict[str, str]:
    metadata = _row_metadata(row)
    source = dict(metadata.get("source_zone") or {})
    lifecycle = dict(source.get("lifecycle") or {})
    approach = dict(source.get("approach") or {})
    return {
        "direction": str(row.get("direction") or "UNKNOWN"),
        "pocket_state": str(metadata.get("pocket_state_at_enrollment") or "UNKNOWN"),
        "leg_role": str(metadata.get("leg_role") or "UNKNOWN"),
        "source_role": str(metadata.get("source_role") or "NONE"),
        "freshness": str(lifecycle.get("freshness") or "UNKNOWN"),
        "approach": str(approach.get("state") or "UNKNOWN"),
        "session": str(source.get("session_context") or "UNKNOWN"),
        "liquidity": _liquidity_bucket(row),
    }


def summarize_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    items = list(rows)
    enrolled = len(items)
    touched = [row for row in items if _dt(row.get("first_touch_at")) is not None]
    resolved_touch = [
        row for row in touched if str(row.get("status") or "") in RESOLVED_AFTER_TOUCH
    ]
    reaction = [row for row in touched if bool(row.get("tp1_hit"))]
    terminal = [row for row in touched if bool(row.get("tp2_hit"))]
    invalidated = [
        row for row in items if str(row.get("status") or "").startswith("INVALIDATED")
    ]
    expired = [
        row for row in items if str(row.get("status") or "").startswith("EXPIRED")
    ]

    resolved_reaction = [row for row in resolved_touch if bool(row.get("tp1_hit"))]
    resolved_terminal = [row for row in resolved_touch if bool(row.get("tp2_hit"))]
    resolved_n = len(resolved_touch)
    reaction_precision = (
        None if resolved_n == 0 else len(resolved_reaction) / resolved_n
    )
    terminal_precision = (
        None if resolved_n == 0 else len(resolved_terminal) / resolved_n
    )
    reaction_wilson = (
        None
        if resolved_n == 0
        else wilson_lower_bound(len(resolved_reaction), resolved_n)
    )
    terminal_wilson = (
        None
        if resolved_n == 0
        else wilson_lower_bound(len(resolved_terminal), resolved_n)
    )

    time_to_touch = [
        _minutes(row.get("observed_at"), row.get("first_touch_at")) for row in touched
    ]
    time_to_reaction = []
    time_to_terminal = []
    for row in items:
        metadata = _row_metadata(row)
        if metadata.get("reaction_hit_at"):
            time_to_reaction.append(
                _minutes(row.get("first_touch_at"), metadata.get("reaction_hit_at"))
            )
        if metadata.get("terminal_hit_at"):
            time_to_terminal.append(
                _minutes(row.get("first_touch_at"), metadata.get("terminal_hit_at"))
            )

    sample_state = (
        "STATISTICAL_SAMPLE"
        if resolved_n >= STATISTICAL_MIN_RESOLVED_TOUCHES
        else "EXPLORATORY_SAMPLE"
        if resolved_n >= EXPLORATORY_MIN_RESOLVED_TOUCHES
        else "COLLECTING"
    )
    target_gate = bool(
        resolved_n >= STATISTICAL_MIN_RESOLVED_TOUCHES
        and reaction_precision is not None
        and reaction_precision >= TARGET_RAW_PRECISION
        and reaction_wilson is not None
        and reaction_wilson >= TARGET_WILSON_LOWER
    )
    return {
        "enrolled": enrolled,
        "touched": len(touched),
        "touch_rate": None if enrolled == 0 else len(touched) / enrolled,
        "resolved_after_touch": resolved_n,
        "reaction_hits": len(reaction),
        "pending_after_touch": len(touched) - resolved_n,
        "reaction_precision_given_touch": reaction_precision,
        "reaction_wilson_lower_95": reaction_wilson,
        "terminal_hits": len(terminal),
        "terminal_precision_given_touch": terminal_precision,
        "terminal_wilson_lower_95": terminal_wilson,
        "invalidated": len(invalidated),
        "expired": len(expired),
        "median_time_to_touch_minutes": _median(time_to_touch),
        "median_touch_to_reaction_minutes": _median(time_to_reaction),
        "median_touch_to_terminal_minutes": _median(time_to_terminal),
        "median_mfe_points": _median(_f(row.get("mfe_points")) for row in touched),
        "median_mae_points": _median(_f(row.get("mae_points")) for row in touched),
        "mean_mfe_points": _mean(_f(row.get("mfe_points")) for row in touched),
        "mean_mae_points": _mean(_f(row.get("mae_points")) for row in touched),
        "sample_state": sample_state,
        "target_80pct_gate_met": target_gate,
        "promotion_authority": False,
    }


def segment_summaries(
    rows: Sequence[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for dimension in (
        "direction",
        "pocket_state",
        "leg_role",
        "source_role",
        "freshness",
        "approach",
        "session",
        "liquidity",
    ):
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            groups[_segment_values(row)[dimension]].append(row)
        output[dimension] = [
            {"value": value, **summarize_rows(group)}
            for value, group in sorted(groups.items())
        ]
    return output


def _chain_key(row: dict[str, Any]) -> str:
    metadata = _row_metadata(row)
    explicit = str(metadata.get("forecast_chain_id") or "")
    if explicit:
        return explicit
    observed = _dt(row.get("observed_at"))
    stamp = "UNKNOWN" if observed is None else observed.isoformat()
    return f"V198:{stamp}"


def _failed(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    return str(row.get("status") or "").startswith("INVALIDATED")


def evaluate_full_path_chain(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    current = next(
        (row for row in rows if _row_metadata(row).get("leg_role") == "current_leg"),
        None,
    )
    reverse = next(
        (row for row in rows if _row_metadata(row).get("leg_role") == "next_leg"),
        None,
    )
    if current is None:
        return {
            "stage_score": 0,
            "state": "NO_CURRENT_LEG",
            "current_direction": None,
            "reverse_direction": None,
        }

    current_touch = _dt(current.get("first_touch_at"))
    current_meta = _row_metadata(current)
    current_reaction = _dt(current_meta.get("reaction_hit_at"))
    reverse_touch = None if reverse is None else _dt(reverse.get("first_touch_at"))
    reverse_meta = {} if reverse is None else _row_metadata(reverse)
    reverse_reaction = _dt(reverse_meta.get("reaction_hit_at"))
    reverse_terminal = _dt(reverse_meta.get("terminal_hit_at"))

    stage = 0
    state = "ENROLLED"
    if _failed(current) and current_reaction is None:
        state = "CURRENT_LEG_FAILED"
    elif current_touch is not None:
        stage = 1
        state = "CURRENT_POCKET_TOUCHED"
        if current_reaction is not None:
            stage = 2
            state = "CURRENT_REACTION_PROVEN"
            if (
                reverse_touch is not None
                and reverse_touch >= current_reaction
            ):
                stage = 3
                state = "OPPOSING_POCKET_TOUCHED_IN_SEQUENCE"
                if _failed(reverse) and reverse_reaction is None:
                    state = "REVERSE_LEG_FAILED"
                elif (
                    reverse_reaction is not None
                    and reverse_reaction >= reverse_touch
                ):
                    stage = 4
                    state = "REVERSE_REACTION_PROVEN"
                    if (
                        reverse_terminal is not None
                        and reverse_terminal >= reverse_reaction
                    ):
                        stage = 5
                        state = "REVERSE_TERMINAL_PROVEN"

    return {
        "stage_score": stage,
        "state": state,
        "current_direction": str(current.get("direction") or ""),
        "reverse_direction": None if reverse is None else str(reverse.get("direction") or ""),
        "current_episode": current.get("episode_key"),
        "reverse_episode": None if reverse is None else reverse.get("episode_key"),
        "current_touch_at": None if current_touch is None else current_touch.isoformat(),
        "current_reaction_at": (
            None if current_reaction is None else current_reaction.isoformat()
        ),
        "reverse_touch_at": None if reverse_touch is None else reverse_touch.isoformat(),
        "reverse_reaction_at": (
            None if reverse_reaction is None else reverse_reaction.isoformat()
        ),
        "reverse_terminal_at": (
            None if reverse_terminal is None else reverse_terminal.isoformat()
        ),
        "strict_chain": bool(_strict(current) and reverse is not None and _strict(reverse)),
    }


def full_path_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    orphan_next_leg_episodes = 0
    for row in rows:
        grouped[_chain_key(row)].append(row)

    chains: list[dict[str, Any]] = []
    for key, group in sorted(grouped.items()):
        current_rows = [
            row for row in group if _row_metadata(row).get("leg_role") == "current_leg"
        ]
        next_rows = [
            row for row in group if _row_metadata(row).get("leg_role") == "next_leg"
        ]
        if not current_rows:
            orphan_next_leg_episodes += len(next_rows)
            continue

        current_direction = str(current_rows[0].get("direction") or "").upper()
        valid_reverse = [
            row
            for row in next_rows
            if str(row.get("direction") or "").upper()
            in ({"LONG", "SHORT"} - {current_direction})
        ]
        clean_group = [current_rows[0], *valid_reverse[:1]]
        chains.append({"chain_id": key, **evaluate_full_path_chain(clean_group)})

    stage_counts = {
        str(stage): sum(int(chain["stage_score"]) >= stage for chain in chains)
        for stage in range(1, 6)
    }
    return {
        "chains": len(chains),
        "orphan_next_leg_episodes_excluded": orphan_next_leg_episodes,
        "stage_reached_counts": stage_counts,
        "max_stage_score": max((int(chain["stage_score"]) for chain in chains), default=0),
        "latest_chains": chains[-20:],
        "interpretation": {
            "1": "CURRENT_POCKET_TOUCHED",
            "2": "CURRENT_REACTION_PROVEN",
            "3": "OPPOSING_POCKET_TOUCHED_AFTER_CURRENT_REACTION",
            "4": "REVERSE_REACTION_PROVEN",
            "5": "REVERSE_TERMINAL_PROVEN",
        },
    }


def build_analytics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    all_rows = list(rows)
    strict_rows = [row for row in all_rows if _strict(row)]
    legacy_rows = [row for row in all_rows if not _strict(row)]
    return {
        "contract": CONTRACT,
        "source_episode_type": EPISODE_TYPE,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "sample_policy": {
            "exploratory_min_resolved_touches": EXPLORATORY_MIN_RESOLVED_TOUCHES,
            "statistical_min_resolved_touches": STATISTICAL_MIN_RESOLVED_TOUCHES,
            "target_raw_precision": TARGET_RAW_PRECISION,
            "target_wilson_lower_95": TARGET_WILSON_LOWER,
        },
        "all_evidence": summarize_rows(all_rows),
        "strict_immutable_evidence": summarize_rows(strict_rows),
        "legacy_pre_freeze_evidence": summarize_rows(legacy_rows),
        "strict_segments": segment_summaries(strict_rows),
        "full_path": full_path_summary(all_rows),
        "strict_full_path": full_path_summary(strict_rows),
    }


def _ledger_rows(store: SupabaseOperationalStore) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("xau_outcome_ledger")
        .select(
            "episode_key,episode_type,strategy_id,observed_at,direction,status,"
            "first_touch_at,outcome_at,tp1_hit,tp2_hit,mfe_points,mae_points,metadata"
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
        raise SystemExit("XAU_V198_ANALYTICS_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V198_ANALYTICS_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    error: str | None = None
    rows: tuple[dict[str, Any], ...] = ()
    analytics: dict[str, Any] = {}
    try:
        rows = _ledger_rows(store)
        analytics = build_analytics(rows)
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
    strict = dict(analytics.get("strict_immutable_evidence") or {})
    full_path = dict(analytics.get("strict_full_path") or {})
    print(
        "CTRADER_DEMO_XAU_V198_EVIDENCE_ANALYTICS "
        f"healthy={healthy} ledger_rows={len(rows)} "
        f"strict_enrolled={strict.get('enrolled', 0)} "
        f"strict_touched={strict.get('touched', 0)} "
        f"strict_reaction_hits={strict.get('reaction_hits', 0)} "
        f"strict_full_path_max_stage={full_path.get('max_stage_score', 0)} "
        f"error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
