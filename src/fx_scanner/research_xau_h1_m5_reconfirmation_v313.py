from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Sequence

from .demo_xau_supply_demand_micro_refinement_v189 import evaluate_micro_refinement
from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import _validate_bars
from .research_xau_reusable_primary_reversal_v312 import (
    _candidate_pool_for_reaction,
    _episode_state_index,
)
from .research_xau_supply_demand_reaction_v183 import (
    ReactionEpisode,
    ZoneDestination,
    wilson_lower_bound,
)
from .research_xau_zone_transition_ledger_v310 import (
    HANDOFF_GAP_USD,
    HANDOFF_WINDOW_MINUTES,
    build_transition_ledger,
)

RESEARCH_VERSION = "XAU_H1_M5_RECONFIRMATION_V313"
ARTIFACT_CONTRACT = "XAU_H1_M5_RECONFIRMATION_V313_EVIDENCE_1"
POLICY_EFFECT = "RESEARCH_ONLY"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
PROMOTION_AUTHORITY = False

MAX_TOUCH_DELAY_MINUTES = 240
M5_CONFIRM_WINDOW_MINUTES = 90
POST_CONFIRM_HORIZON_MINUTES = 240
REACTION_ATR_MULTIPLE = 0.50
PURGE_HOURS = 24
DEVELOPMENT_FRACTION = 0.60

MIN_HOLDOUT_CONFIRMED = 30
MIN_HOLDOUT_CONFIRM_RATE = 0.10
MIN_POST_CONFIRM_HOLD_RATE = 0.60
MIN_POST_CONFIRM_WILSON = 0.50
MIN_UPLIFT_PP_VS_TOUCH_BASELINE = 7.5
MAX_MEDIAN_CONFIRM_MINUTES = 60.0

POLICIES = (
    "ALL_H1_MICRO_REQUIRED",
    "PRIOR_HOLD_H1_MICRO_REQUIRED",
    "STRUCTURAL_PRIOR_HOLD_H1_MICRO_REQUIRED",
)


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return ensure_utc(value)
    return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _select_micro_candidate(
    candidates: Sequence[dict[str, Any]],
    *,
    policy: str,
) -> dict[str, Any] | None:
    rows: list[dict[str, Any]] = []
    for raw in candidates:
        row = dict(raw)
        lifecycle = dict(row.get("lifecycle") or {})
        if str(row.get("timeframe") or "").upper() != "H1":
            continue
        touches = int(lifecycle.get("touch_count_proxy") or 0)
        if touches <= 0:
            continue
        if not bool(lifecycle.get("fresh_micro_refresh_required")):
            continue
        if policy in {
            "PRIOR_HOLD_H1_MICRO_REQUIRED",
            "STRUCTURAL_PRIOR_HOLD_H1_MICRO_REQUIRED",
        } and str(lifecycle.get("latest_reaction_status") or "") != "HOLD":
            continue
        if (
            policy == "STRUCTURAL_PRIOR_HOLD_H1_MICRO_REQUIRED"
            and str(row.get("zone_class") or "") != "STRUCTURAL"
        ):
            continue
        rows.append(row)

    if not rows:
        return None
    rows.sort(
        key=lambda row: (
            -float(row.get("authority_score") or 0.0),
            float(row.get("gap_usd") or 999.0),
            str(row.get("zone_id") or ""),
        )
    )
    return dict(rows[0])


def _m5_times(rows: Sequence[Bar]) -> tuple[datetime, ...]:
    return tuple(ensure_utc(row.timestamp) for row in rows)


def _first_m5_touch(
    *,
    rows: Sequence[Bar],
    times: Sequence[datetime],
    zone: ZoneDestination,
    eligible_at: datetime,
) -> tuple[int, Bar] | None:
    start = bisect_left(times, ensure_utc(eligible_at))
    deadline = ensure_utc(eligible_at) + timedelta(minutes=MAX_TOUCH_DELAY_MINUTES)
    for index in range(start, len(rows)):
        row = rows[index]
        at = ensure_utc(row.timestamp)
        if at > deadline:
            break
        if float(row.high) >= float(zone.low) and float(row.low) <= float(zone.high):
            return index, row
    return None


def _m5_slice(
    rows: Sequence[Bar],
    times: Sequence[datetime],
    *,
    from_at: datetime,
    to_at: datetime,
) -> tuple[Bar, ...]:
    start = bisect_left(times, ensure_utc(from_at))
    end = bisect_left(times, ensure_utc(to_at) + timedelta(microseconds=1))
    return tuple(rows[start:end])


def _source_dict(zone: ZoneDestination) -> dict[str, Any]:
    direction = str(zone.direction).upper()
    return {
        "zone_id": zone.zone_id,
        "timeframe": zone.timeframe,
        "zone_class": zone.zone_class,
        "pattern": zone.pattern,
        "direction": direction,
        "available_at": ensure_utc(zone.available_at).isoformat(),
        "low": float(zone.low),
        "high": float(zone.high),
        "proximal": float(zone.high if direction == "LONG" else zone.low),
        "distal": float(zone.low if direction == "LONG" else zone.high),
        "lifecycle": {"active": True},
    }


def _micro_confirmation(
    *,
    m5_rows: Sequence[Bar],
    m5_times: Sequence[datetime],
    zone: ZoneDestination,
    eligible_at: datetime,
) -> dict[str, Any]:
    touch = _first_m5_touch(
        rows=m5_rows,
        times=m5_times,
        zone=zone,
        eligible_at=eligible_at,
    )
    if touch is None:
        return {
            "state": "NO_M5_TOUCH_WITHIN_240M",
            "confirmed": False,
            "first_touch_at": None,
        }
    _, touch_bar = touch
    touch_at = ensure_utc(touch_bar.timestamp)
    as_of = touch_at + timedelta(minutes=M5_CONFIRM_WINDOW_MINUTES + 5)
    context_start = touch_at - timedelta(hours=12)
    bounded = _m5_slice(
        m5_rows,
        m5_times,
        from_at=context_start,
        to_at=as_of,
    )
    source = _source_dict(zone)
    result = evaluate_micro_refinement(
        bounded,
        path_map={
            "active_path": {
                "source_zone": source,
                "reaction_direction": zone.direction,
            }
        },
        as_of=as_of,
        parent_source_zone=None,
        not_before=eligible_at,
    )
    displacement_at = result.get("displacement_at")
    confirmed = bool(
        result.get("state") == "M5_REFINEMENT_CONFIRMED_SHADOW"
        and result.get("reclaim_confirmed")
        and result.get("mss_confirmed")
        and result.get("displacement_confirmed")
        and displacement_at
    )
    confirmation_at = None
    if confirmed:
        displacement_bar_at = _dt(displacement_at)
        candidate_confirmation = displacement_bar_at + timedelta(minutes=5)
        if candidate_confirmation <= touch_at + timedelta(minutes=M5_CONFIRM_WINDOW_MINUTES):
            confirmation_at = candidate_confirmation
        else:
            confirmed = False

    return {
        "state": str(result.get("state") or "UNKNOWN"),
        "confirmed": confirmed,
        "first_touch_at": touch_at.isoformat(),
        "confirmation_at": (
            None if confirmation_at is None else confirmation_at.isoformat()
        ),
        "minutes_touch_to_confirmation": (
            None
            if confirmation_at is None
            else (confirmation_at - touch_at).total_seconds() / 60.0
        ),
        "reclaim_confirmed": bool(result.get("reclaim_confirmed")),
        "mss_confirmed": bool(result.get("mss_confirmed")),
        "displacement_confirmed": bool(result.get("displacement_confirmed")),
        "mss_scope": result.get("mss_scope"),
        "refined_entry_pocket": result.get("refined_entry_pocket"),
    }


def _post_anchor_outcome(
    *,
    rows: Sequence[Bar],
    times: Sequence[datetime],
    zone: ZoneDestination,
    anchor_at: datetime,
    anchor_price: float,
) -> dict[str, Any]:
    start = bisect_left(times, ensure_utc(anchor_at))
    deadline = ensure_utc(anchor_at) + timedelta(minutes=POST_CONFIRM_HORIZON_MINUTES)
    target_distance = REACTION_ATR_MULTIPLE * float(zone.atr_points)
    direction = str(zone.direction).upper()

    max_favorable = 0.0
    max_adverse = 0.0
    for index in range(start, len(rows)):
        row = rows[index]
        at = ensure_utc(row.timestamp)
        if at >= deadline:
            break
        if direction == "LONG":
            favorable = max(0.0, float(row.high) - anchor_price)
            adverse = max(0.0, anchor_price - float(row.low))
            broken = float(row.close) < float(zone.low)
        else:
            favorable = max(0.0, anchor_price - float(row.low))
            adverse = max(0.0, float(row.high) - anchor_price)
            broken = float(row.close) > float(zone.high)
        max_favorable = max(max_favorable, favorable)
        max_adverse = max(max_adverse, adverse)

        # Conservative ambiguity contract: distal close break wins the bar.
        if broken:
            return {
                "status": "BREAK",
                "outcome_bar_at": at.isoformat(),
                "outcome_at": (at + timedelta(minutes=5)).isoformat(),
                "max_favorable_atr": max_favorable / float(zone.atr_points),
                "max_adverse_atr": max_adverse / float(zone.atr_points),
            }
        if favorable >= target_distance:
            return {
                "status": "HOLD",
                "outcome_bar_at": at.isoformat(),
                "outcome_at": (at + timedelta(minutes=5)).isoformat(),
                "max_favorable_atr": max_favorable / float(zone.atr_points),
                "max_adverse_atr": max_adverse / float(zone.atr_points),
            }

    return {
        "status": "STALL",
        "outcome_bar_at": None,
        "outcome_at": deadline.isoformat(),
        "max_favorable_atr": max_favorable / float(zone.atr_points),
        "max_adverse_atr": max_adverse / float(zone.atr_points),
    }


def _bar_close_at(
    rows: Sequence[Bar],
    times: Sequence[datetime],
    at: datetime,
) -> float | None:
    target = ensure_utc(at)
    index = bisect_left(times, target)
    if index < len(rows) and times[index] == target:
        return float(rows[index].open)
    if index <= 0:
        return None
    return float(rows[index - 1].close)


def _evaluate_policy(
    *,
    policy: str,
    m15_rows: Sequence[Bar],
    destinations: Sequence[ZoneDestination],
    episodes: Sequence[ReactionEpisode],
    m5_rows: Sequence[Bar],
) -> tuple[dict[str, Any], ...]:
    episode_index = _episode_state_index(m15_rows, episodes, destinations)
    zone_by_id = {zone.zone_id: zone for zone in destinations}
    m15_by_time = {ensure_utc(row.timestamp): row for row in m15_rows}
    m5_times = _m5_times(m5_rows)
    output: list[dict[str, Any]] = []

    m5_start = m5_times[0] if m5_times else None
    m5_end = (
        m5_times[-1] + timedelta(minutes=5)
        if m5_times
        else None
    )

    for episode in episodes:
        if episode.outcome.status != "HOLD" or episode.outcome.outcome_at is None:
            continue
        outcome_bar_at = ensure_utc(episode.outcome.outcome_at)
        reaction_at = outcome_bar_at + timedelta(minutes=15)
        if m5_start is None or m5_end is None:
            continue
        if reaction_at < m5_start or reaction_at >= m5_end:
            continue
        reaction_bar = m15_by_time.get(outcome_bar_at)
        if reaction_bar is None:
            continue
        reaction_price = float(reaction_bar.close)
        candidates = _candidate_pool_for_reaction(
            rows=m15_rows,
            destinations=destinations,
            episode_index=episode_index,
            source_direction=episode.direction,
            reaction_at=reaction_at,
            reaction_price=reaction_price,
            handoff_window_minutes=HANDOFF_WINDOW_MINUTES,
            handoff_gap_usd=HANDOFF_GAP_USD,
        )
        selected = _select_micro_candidate(candidates, policy=policy)
        if selected is None:
            continue
        zone = zone_by_id.get(str(selected["zone_id"]))
        if zone is None:
            continue

        eligible_at = _dt(selected["eligible_at"])
        micro = _micro_confirmation(
            m5_rows=m5_rows,
            m5_times=m5_times,
            zone=zone,
            eligible_at=eligible_at,
        )
        touch_at = micro.get("first_touch_at")
        touch_baseline = None
        if touch_at:
            touch_dt = _dt(touch_at)
            touch_anchor = _bar_close_at(
                m5_rows,
                m5_times,
                touch_dt + timedelta(minutes=5),
            )
            if touch_anchor is not None:
                touch_baseline = _post_anchor_outcome(
                    rows=m5_rows,
                    times=m5_times,
                    zone=zone,
                    anchor_at=touch_dt + timedelta(minutes=5),
                    anchor_price=touch_anchor,
                )

        post_confirm = None
        if micro.get("confirmed") and micro.get("confirmation_at"):
            confirmation_at = _dt(micro["confirmation_at"])
            confirmation_price = _bar_close_at(
                m5_rows,
                m5_times,
                confirmation_at,
            )
            if confirmation_price is not None:
                post_confirm = _post_anchor_outcome(
                    rows=m5_rows,
                    times=m5_times,
                    zone=zone,
                    anchor_at=confirmation_at,
                    anchor_price=confirmation_price,
                )

        lifecycle = dict(selected.get("lifecycle") or {})
        output.append(
            {
                "policy": policy,
                "source_zone_id": episode.zone_id,
                "source_direction": episode.direction,
                "reaction_at": reaction_at.isoformat(),
                "reaction_price": reaction_price,
                "selected_zone_id": zone.zone_id,
                "selected_zone_class": zone.zone_class,
                "selected_timeframe": zone.timeframe,
                "selected_direction": zone.direction,
                "selected_low": float(zone.low),
                "selected_high": float(zone.high),
                "selected_gap_usd": float(selected.get("gap_usd") or 0.0),
                "selected_origin": selected.get("origin"),
                "selected_authority_score": selected.get("authority_score"),
                "lifecycle_state": lifecycle.get("state"),
                "touch_count_proxy": lifecycle.get("touch_count_proxy"),
                "mitigation_depth_proxy": lifecycle.get("mitigation_depth_proxy"),
                "prior_reaction_status": lifecycle.get("latest_reaction_status"),
                "prior_htf_nesting_count": lifecycle.get("latest_htf_nesting_count"),
                "micro": micro,
                "touch_baseline": touch_baseline,
                "post_confirm": post_confirm,
            }
        )

    output.sort(
        key=lambda row: (row["reaction_at"], row["selected_zone_id"])
    )
    return tuple(output)


def _split(rows: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = list(sorted(rows, key=lambda row: _dt(row["reaction_at"])))
    if len(ordered) < 20:
        return [], []
    split_index = max(1, min(len(ordered) - 1, int(len(ordered) * DEVELOPMENT_FRACTION)))
    split_at = _dt(ordered[split_index]["reaction_at"])
    purge = timedelta(hours=PURGE_HOURS)
    development = [
        row for row in ordered if _dt(row["reaction_at"]) < split_at - purge
    ]
    holdout = [
        row for row in ordered if _dt(row["reaction_at"]) >= split_at
    ]
    return development, holdout


def _summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    sample = list(rows)
    touched = [row for row in sample if dict(row.get("micro") or {}).get("first_touch_at")]
    confirmed = [row for row in sample if dict(row.get("micro") or {}).get("confirmed")]
    post_resolved = [
        row
        for row in confirmed
        if dict(row.get("post_confirm") or {}).get("status") in {"HOLD", "BREAK", "STALL"}
    ]
    post_holds = [
        row for row in confirmed
        if dict(row.get("post_confirm") or {}).get("status") == "HOLD"
    ]
    touch_baseline_resolved = [
        row
        for row in sample
        if dict(row.get("touch_baseline") or {}).get("status") in {"HOLD", "BREAK", "STALL"}
    ]
    touch_baseline_holds = [
        row
        for row in sample
        if dict(row.get("touch_baseline") or {}).get("status") == "HOLD"
    ]
    confirm_delays = [
        float(dict(row.get("micro") or {}).get("minutes_touch_to_confirmation"))
        for row in confirmed
        if dict(row.get("micro") or {}).get("minutes_touch_to_confirmation") is not None
    ]

    baseline_rate = (
        len(touch_baseline_holds) / len(touch_baseline_resolved)
        if touch_baseline_resolved else None
    )
    post_rate = (
        len(post_holds) / len(post_resolved)
        if post_resolved else None
    )
    uplift_pp = (
        None
        if baseline_rate is None or post_rate is None
        else (post_rate - baseline_rate) * 100.0
    )

    return {
        "selected_candidates": len(sample),
        "touched_within_240m": len(touched),
        "touch_rate": len(touched) / len(sample) if sample else None,
        "m5_confirmed": len(confirmed),
        "confirmation_rate_of_selected": len(confirmed) / len(sample) if sample else None,
        "confirmation_rate_of_touched": len(confirmed) / len(touched) if touched else None,
        "touch_baseline_resolved": len(touch_baseline_resolved),
        "touch_baseline_holds": len(touch_baseline_holds),
        "touch_baseline_hold_rate": baseline_rate,
        "post_confirm_resolved": len(post_resolved),
        "post_confirm_holds": len(post_holds),
        "post_confirm_hold_rate": post_rate,
        "post_confirm_wilson_lower_95": (
            wilson_lower_bound(len(post_holds), len(post_resolved))
            if post_resolved else None
        ),
        "uplift_pp_vs_touch_baseline": uplift_pp,
        "median_minutes_touch_to_confirmation": (
            median(confirm_delays) if confirm_delays else None
        ),
    }


def _gate(summary: dict[str, Any]) -> dict[str, Any]:
    confirmed = int(summary.get("m5_confirmed") or 0)
    confirm_rate = float(summary.get("confirmation_rate_of_selected") or 0.0)
    hold_rate = float(summary.get("post_confirm_hold_rate") or 0.0)
    wilson = float(summary.get("post_confirm_wilson_lower_95") or 0.0)
    uplift = float(summary.get("uplift_pp_vs_touch_baseline") or 0.0)
    median_confirm = summary.get("median_minutes_touch_to_confirmation")
    median_ok = (
        median_confirm is not None
        and float(median_confirm) <= MAX_MEDIAN_CONFIRM_MINUTES
    )
    passed = bool(
        confirmed >= MIN_HOLDOUT_CONFIRMED
        and confirm_rate >= MIN_HOLDOUT_CONFIRM_RATE
        and hold_rate >= MIN_POST_CONFIRM_HOLD_RATE
        and wilson >= MIN_POST_CONFIRM_WILSON
        and uplift >= MIN_UPLIFT_PP_VS_TOUCH_BASELINE
        and median_ok
    )
    return {
        "min_holdout_confirmed": MIN_HOLDOUT_CONFIRMED,
        "min_confirmation_rate": MIN_HOLDOUT_CONFIRM_RATE,
        "min_post_confirm_hold_rate": MIN_POST_CONFIRM_HOLD_RATE,
        "min_post_confirm_wilson_lower_95": MIN_POST_CONFIRM_WILSON,
        "min_uplift_pp_vs_touch_baseline": MIN_UPLIFT_PP_VS_TOUCH_BASELINE,
        "max_median_confirm_minutes": MAX_MEDIAN_CONFIRM_MINUTES,
        "passed": passed,
    }


def evaluate_h1_m5_reconfirmation(
    m15_bars: Sequence[Bar],
    m5_bars: Sequence[Bar],
) -> dict[str, Any]:
    m15_rows = _validate_bars(m15_bars)
    m5_rows = tuple(sorted(m5_bars, key=lambda row: ensure_utc(row.timestamp)))
    if not m5_rows:
        raise ValueError("V313_M5_HISTORY_REQUIRED")

    destinations, episodes, ledger = build_transition_ledger(m15_rows)
    policies: dict[str, Any] = {}
    for policy in POLICIES:
        rows = _evaluate_policy(
            policy=policy,
            m15_rows=m15_rows,
            destinations=destinations,
            episodes=episodes,
            m5_rows=m5_rows,
        )
        development, holdout = _split(rows)
        development_summary = _summary(development)
        holdout_summary = _summary(holdout)
        policies[policy] = {
            "all": _summary(rows),
            "development": development_summary,
            "holdout": holdout_summary,
            "holdout_gate": _gate(holdout_summary),
            "rows": list(rows),
        }

    primary = policies["STRUCTURAL_PRIOR_HOLD_H1_MICRO_REQUIRED"]
    primary_gate = dict(primary.get("holdout_gate") or {})
    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "closed_m15_bars": len(m15_rows),
        "closed_m5_bars": len(m5_rows),
        "m15_start": ensure_utc(m15_rows[0].timestamp).isoformat(),
        "m15_end": ensure_utc(m15_rows[-1].timestamp).isoformat(),
        "m5_start": ensure_utc(m5_rows[0].timestamp).isoformat(),
        "m5_end": ensure_utc(m5_rows[-1].timestamp).isoformat(),
        "zones": len(destinations),
        "reaction_episodes": len(episodes),
        "ledger_events": len(ledger),
        "method": {
            "candidate_universe": "V312_H1_MICRO_REQUIRED_ONLY",
            "micro_engine": "V189_RECLAIM_MSS_DISPLACEMENT",
            "max_touch_delay_minutes": MAX_TOUCH_DELAY_MINUTES,
            "micro_confirm_window_minutes": M5_CONFIRM_WINDOW_MINUTES,
            "post_confirm_horizon_minutes": POST_CONFIRM_HORIZON_MINUTES,
            "post_confirm_reaction_atr": REACTION_ATR_MULTIPLE,
            "chronological_split": DEVELOPMENT_FRACTION,
            "purge_hours": PURGE_HOURS,
            "primary_policy": "STRUCTURAL_PRIOR_HOLD_H1_MICRO_REQUIRED",
        },
        "policies": policies,
        "primary_holdout_gate": primary_gate,
        "decision": (
            "PRIMARY_HOLDOUT_GATE_PASSED_EXACT_ENTRY_REPLAY_NEXT"
            if bool(primary_gate.get("passed"))
            else "PRIMARY_HOLDOUT_GATE_NOT_PASSED"
        ),
        "limitations": [
            "V313_IS_RECENT_CTRADER_OVERLAP_NOT_FULL_2022_2026_M5_HISTORY",
            "V312_HISTORICAL_LIFECYCLE_USES_M15_MITIGATION_PROXY",
            "V189_MICRO_CONFIRMATION_IS_STRUCTURAL_EVIDENCE_NOT_BROKER_FILL",
            "POST_CONFIRM_HOLD_USES_M5_CONFIRMATION_PRICE_NOT_LIMIT_ORDER_REPLAY",
            "NO_EXECUTION_OR_PROMOTION_AUTHORITY",
        ],
    }
