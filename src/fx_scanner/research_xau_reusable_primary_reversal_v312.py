from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta
from math import isfinite
from statistics import median
from typing import Any, Sequence

from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import _validate_bars
from .research_xau_supply_demand_reaction_v183 import (
    ReactionEpisode,
    ZoneDestination,
    wilson_lower_bound,
)
from .research_xau_zone_transition_ledger_v310 import (
    HANDOFF_GAP_USD,
    HANDOFF_WINDOW_MINUTES,
    _zone_gap,
    build_transition_ledger,
)

RESEARCH_VERSION = "XAU_REUSABLE_PRIMARY_REVERSAL_CYCLE_V312"
ARTIFACT_CONTRACT = "XAU_REUSABLE_PRIMARY_REVERSAL_CYCLE_V312_EVIDENCE_1"
POLICY_EFFECT = "RESEARCH_ONLY"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
PROMOTION_AUTHORITY = False

PARTIAL_MITIGATION_THRESHOLD = 0.35
DEEP_MITIGATION_THRESHOLD = 0.75

# Pre-registered research gate. It is descriptive only and has no production authority.
MIN_REUSABLE_CANDIDATES = 100
MIN_COVERAGE_UPLIFT_PP = 2.0
MIN_SECOND_HOLD_RATE_ALL_ELIGIBLE = 0.55
MIN_SECOND_HOLD_WILSON_RESOLVED = 0.50


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return ensure_utc(value)
    return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _causal_active(zone: ZoneDestination, at: datetime) -> bool:
    cutoff = ensure_utc(at)
    if ensure_utc(zone.available_at) > cutoff:
        return False
    # V183 invalidation is based on M15 close and is only knowable at bar close.
    if (
        zone.invalidated_at is not None
        and ensure_utc(zone.invalidated_at) + timedelta(minutes=15) <= cutoff
    ):
        return False
    if zone.expired_at is not None and ensure_utc(zone.expired_at) <= cutoff:
        return False
    return True


def _touch_depth(zone: ZoneDestination, bar: Bar) -> float:
    width = float(zone.high) - float(zone.low)
    if width <= 0:
        return 1.0
    if zone.direction == "LONG":
        penetration = float(zone.high) - float(bar.low)
    else:
        penetration = float(bar.high) - float(zone.low)
    return max(0.0, min(1.0, penetration / width))


def _episode_state_index(
    rows: Sequence[Bar],
    episodes: Sequence[ReactionEpisode],
    destinations: Sequence[ZoneDestination],
) -> dict[str, list[dict[str, Any]]]:
    """Prepare causal V200-compatible lifecycle evidence from V183 episodes.

    V183 does not persist the live V182 mitigation-depth field. V312 therefore
    uses a documented M15 episode-window penetration proxy. The proxy never reads
    beyond the requested cutoff, and is research-only.
    """
    row_times = [ensure_utc(row.timestamp) for row in rows]
    row_index = {timestamp: idx for idx, timestamp in enumerate(row_times)}
    zone_by_id = {row.zone_id: row for row in destinations}
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for episode in episodes:
        zone = zone_by_id.get(episode.zone_id)
        if zone is None:
            continue
        touch_bar_at = ensure_utc(episode.touch_at)
        touch_idx = row_index.get(touch_bar_at)
        if touch_idx is None:
            continue
        outcome_bar_at = (
            touch_bar_at
            if episode.outcome.outcome_at is None
            else ensure_utc(episode.outcome.outcome_at)
        )
        outcome_idx = row_index.get(outcome_bar_at, touch_idx)
        output[episode.zone_id].append(
            {
                "episode": episode,
                "touch_bar_at": touch_bar_at,
                "touch_known_at": touch_bar_at + timedelta(minutes=15),
                "touch_index": touch_idx,
                "outcome_index": max(touch_idx, outcome_idx),
            }
        )

    for values in output.values():
        values.sort(key=lambda item: item["touch_bar_at"])
    return dict(output)


def _lifecycle_at(
    *,
    zone: ZoneDestination,
    cutoff: datetime,
    rows: Sequence[Bar],
    episode_index: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    at = ensure_utc(cutoff)
    prior = [
        item
        for item in episode_index.get(zone.zone_id, [])
        if item["touch_known_at"] <= at
    ]
    if not prior:
        return {
            "state": "FRESH_PARENT_ZONE",
            "touch_count_proxy": 0,
            "mitigation_depth_proxy": 0.0,
            "fresh_micro_refresh_required": False,
            "reusable_without_new_micro": True,
            "proxy_contract": "V183_EPISODE_M15_PENETRATION_PROXY",
        }

    latest = prior[-1]
    touch_count = max(
        int(item["episode"].touch_ordinal)
        for item in prior
    )
    max_depth = 0.0
    last_completed_bar_at = at - timedelta(minutes=15)
    for item in prior:
        start = int(item["touch_index"])
        stop = int(item["outcome_index"])
        # Do not read an M15 bar whose close was not yet available at cutoff.
        for idx in range(start, min(stop, len(rows) - 1) + 1):
            if ensure_utc(rows[idx].timestamp) > last_completed_bar_at:
                break
            max_depth = max(max_depth, _touch_depth(zone, rows[idx]))

    if max_depth >= DEEP_MITIGATION_THRESHOLD:
        state = "DEEPLY_MITIGATED_REQUIRE_NEW_MICRO"
        refresh = True
        reusable = False
    elif max_depth >= PARTIAL_MITIGATION_THRESHOLD:
        state = "PARTIALLY_MITIGATED_REQUIRE_RECONFIRMATION"
        refresh = True
        reusable = False
    elif touch_count <= 1:
        state = "FIRST_TEST_PARENT_ACTIVE"
        refresh = False
        reusable = True
    elif touch_count == 2:
        state = "SECOND_TEST_CONDITIONAL"
        refresh = True
        reusable = False
    else:
        state = "MULTI_TESTED_REQUIRE_NEW_MICRO"
        refresh = True
        reusable = False

    latest_episode = latest["episode"]
    return {
        "state": state,
        "touch_count_proxy": touch_count,
        "mitigation_depth_proxy": round(max_depth, 6),
        "fresh_micro_refresh_required": refresh,
        "reusable_without_new_micro": reusable,
        "latest_touch_bar_at": latest["touch_bar_at"].isoformat(),
        "latest_touch_known_at": latest["touch_known_at"].isoformat(),
        "latest_touch_bucket": latest_episode.touch_bucket,
        "latest_htf_nesting_count": int(latest_episode.htf_nesting_count),
        "latest_reaction_status": str(latest_episode.outcome.status),
        "proxy_contract": "V183_EPISODE_M15_PENETRATION_PROXY",
    }


def _authority_score(
    *,
    zone: ZoneDestination,
    gap_usd: float,
    lifecycle: dict[str, Any],
) -> float:
    fresh = int(lifecycle.get("touch_count_proxy") or 0) == 0
    freshness_points = 24.0 if fresh else 20.0
    structural_points = 18.0 if zone.zone_class == "STRUCTURAL" else 8.0
    timeframe_points = {"H1": 10.0, "H4": 8.0, "D1": 6.0}.get(
        str(zone.timeframe).upper(),
        0.0,
    )
    nesting = min(
        24.0,
        8.0 * int(lifecycle.get("latest_htf_nesting_count") or 0),
    )
    atr = max(float(zone.atr_points), 1e-9)
    distance_penalty = 3.0 * (float(gap_usd) / atr)
    mitigation = float(lifecycle.get("mitigation_depth_proxy") or 0.0)
    mitigation_penalty = (
        35.0
        if mitigation >= DEEP_MITIGATION_THRESHOLD
        else 12.0
        if mitigation >= PARTIAL_MITIGATION_THRESHOLD
        else 0.0
    )
    return round(
        freshness_points
        + structural_points
        + timeframe_points
        + nesting
        - distance_penalty
        - mitigation_penalty,
        6,
    )


def _candidate_record(
    *,
    zone: ZoneDestination,
    gap_usd: float,
    origin: str,
    eligible_at: datetime,
    lifecycle: dict[str, Any],
) -> dict[str, Any]:
    return {
        "zone_id": zone.zone_id,
        "direction": zone.direction,
        "timeframe": zone.timeframe,
        "zone_class": zone.zone_class,
        "pattern": zone.pattern,
        "low": float(zone.low),
        "high": float(zone.high),
        "atr_points": float(zone.atr_points),
        "gap_usd": float(gap_usd),
        "origin": origin,
        "eligible_at": ensure_utc(eligible_at).isoformat(),
        "lifecycle": dict(lifecycle),
        "authority_score": _authority_score(
            zone=zone,
            gap_usd=gap_usd,
            lifecycle=lifecycle,
        ),
        "authority_contract": "V309_COMPATIBLE_FORWARD_REACHABLE_HISTORICAL_PROXY",
    }


def _select_candidate(
    candidates: Sequence[dict[str, Any]],
    *,
    allow_reuse: bool,
) -> dict[str, Any] | None:
    eligible = []
    for row in candidates:
        lifecycle = dict(row.get("lifecycle") or {})
        touches = int(lifecycle.get("touch_count_proxy") or 0)
        if touches == 0:
            eligible.append(dict(row))
        elif allow_reuse and bool(lifecycle.get("reusable_without_new_micro")):
            eligible.append(dict(row))
    if not eligible:
        return None
    eligible.sort(
        key=lambda row: (
            -float(row.get("authority_score") or 0.0),
            float(row.get("gap_usd") or 999.0),
            0 if str(row.get("timeframe")).upper() == "H1" else 1,
            str(row.get("zone_id") or ""),
        )
    )
    return dict(eligible[0])


def _next_episode(
    episode_index: dict[str, list[dict[str, Any]]],
    *,
    zone_id: str,
    eligible_at: datetime,
) -> ReactionEpisode | None:
    cutoff = ensure_utc(eligible_at)
    for item in episode_index.get(zone_id, []):
        # The actual touch must start at or after the handoff eligibility.
        if item["touch_bar_at"] < cutoff:
            continue
        episode = item["episode"]
        if episode.outcome.status in {"HOLD", "BREAK", "BREAK_TOUCH_BAR", "STALL"}:
            return episode
    return None


def _candidate_pool_for_reaction(
    *,
    rows: Sequence[Bar],
    destinations: Sequence[ZoneDestination],
    episode_index: dict[str, list[dict[str, Any]]],
    source_direction: str,
    reaction_at: datetime,
    reaction_price: float,
    handoff_window_minutes: int,
    handoff_gap_usd: float,
) -> tuple[dict[str, Any], ...]:
    opposite = "SHORT" if source_direction == "LONG" else "LONG"
    deadline = reaction_at + timedelta(minutes=handoff_window_minutes)
    candidates: list[dict[str, Any]] = []

    for zone in destinations:
        if zone.direction != opposite:
            continue
        available = ensure_utc(zone.available_at)

        if available <= reaction_at:
            eligible_at = reaction_at
            if not _causal_active(zone, eligible_at):
                continue
            gap = _zone_gap(reaction_price, zone)
            if gap > handoff_gap_usd:
                continue
            lifecycle = _lifecycle_at(
                zone=zone,
                cutoff=eligible_at,
                rows=rows,
                episode_index=episode_index,
            )
            candidates.append(
                _candidate_record(
                    zone=zone,
                    gap_usd=gap,
                    origin="ACTIVE_AT_REACTION",
                    eligible_at=eligible_at,
                    lifecycle=lifecycle,
                )
            )
            continue

        if reaction_at < available <= deadline:
            gap = _zone_gap(reaction_price, zone)
            if gap > handoff_gap_usd:
                continue
            lifecycle = _lifecycle_at(
                zone=zone,
                cutoff=available,
                rows=rows,
                episode_index=episode_index,
            )
            candidates.append(
                _candidate_record(
                    zone=zone,
                    gap_usd=gap,
                    origin="NEW_WITHIN_WINDOW",
                    eligible_at=available,
                    lifecycle=lifecycle,
                )
            )

    return tuple(candidates)


def _evaluate_selected(
    *,
    selected: dict[str, Any] | None,
    episode_index: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    if not selected:
        return {
            "selected": False,
            "second_reaction_status": None,
            "second_hold": False,
            "resolved": False,
        }
    eligible_at = _dt(selected["eligible_at"])
    second = _next_episode(
        episode_index,
        zone_id=str(selected["zone_id"]),
        eligible_at=eligible_at,
    )
    base = {
        "selected": True,
        "selected_zone_id": selected["zone_id"],
        "selected_timeframe": selected["timeframe"],
        "selected_zone_class": selected["zone_class"],
        "selected_pattern": selected["pattern"],
        "selected_low": selected["low"],
        "selected_high": selected["high"],
        "selected_gap_usd": selected["gap_usd"],
        "selected_origin": selected["origin"],
        "selected_authority_score": selected["authority_score"],
        "selected_lifecycle": selected["lifecycle"],
        "eligible_at": selected["eligible_at"],
    }
    if second is None:
        return {
            **base,
            "second_reaction_status": None,
            "second_hold": False,
            "resolved": False,
        }
    outcome_bar_at = (
        None
        if second.outcome.outcome_at is None
        else ensure_utc(second.outcome.outcome_at)
    )
    outcome_known_at = (
        None
        if outcome_bar_at is None
        else outcome_bar_at + timedelta(minutes=15)
    )
    status = str(second.outcome.status)
    return {
        **base,
        "second_touch_bar_at": ensure_utc(second.touch_at).isoformat(),
        "second_touch_known_at": (
            ensure_utc(second.touch_at) + timedelta(minutes=15)
        ).isoformat(),
        "second_touch_ordinal": int(second.touch_ordinal),
        "second_touch_bucket": second.touch_bucket,
        "second_reaction_status": status,
        "second_reaction_bar_at": (
            None if outcome_bar_at is None else outcome_bar_at.isoformat()
        ),
        "second_reaction_at": (
            None if outcome_known_at is None else outcome_known_at.isoformat()
        ),
        "second_mfe_atr": float(second.outcome.max_favorable_excursion_atr),
        "second_mae_atr": float(second.outcome.max_adverse_excursion_atr),
        "second_hold": status == "HOLD",
        "resolved": True,
    }


def _policy_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    sample = list(rows)
    n = len(sample)
    selected = [row for row in sample if row.get("selected")]
    resolved = [row for row in selected if row.get("resolved")]
    holds = [row for row in selected if row.get("second_hold")]
    reused = [
        row
        for row in selected
        if int(dict(row.get("selected_lifecycle") or {}).get("touch_count_proxy") or 0) > 0
    ]
    fresh = [row for row in selected if row not in reused]
    gaps = [
        float(row["selected_gap_usd"])
        for row in selected
        if row.get("selected_gap_usd") is not None
    ]
    delays_touch = []
    delays_outcome = []
    for row in resolved:
        eligible_at = _dt(row["eligible_at"])
        touch_at = _dt(row["second_touch_bar_at"])
        delays_touch.append((touch_at - eligible_at).total_seconds() / 60.0)
        if row.get("second_reaction_at"):
            outcome_at = _dt(row["second_reaction_at"])
            delays_outcome.append((outcome_at - eligible_at).total_seconds() / 60.0)

    by_lifecycle: dict[str, dict[str, Any]] = {}
    for state in sorted({
        str(dict(row.get("selected_lifecycle") or {}).get("state") or "")
        for row in selected
    }):
        cohort = [
            row for row in selected
            if str(dict(row.get("selected_lifecycle") or {}).get("state") or "") == state
        ]
        cohort_resolved = [row for row in cohort if row.get("resolved")]
        cohort_holds = [row for row in cohort if row.get("second_hold")]
        by_lifecycle[state] = {
            "n": len(cohort),
            "resolved": len(cohort_resolved),
            "second_hold": len(cohort_holds),
            "second_hold_rate_all_selected": (
                len(cohort_holds) / len(cohort) if cohort else None
            ),
            "second_hold_rate_resolved": (
                len(cohort_holds) / len(cohort_resolved)
                if cohort_resolved else None
            ),
        }

    by_year: dict[str, dict[str, Any]] = {}
    for year in sorted({str(row.get("reaction_at"))[:4] for row in sample}):
        cohort_all = [row for row in sample if str(row.get("reaction_at")).startswith(year)]
        cohort = [row for row in cohort_all if row.get("selected")]
        cohort_holds = [row for row in cohort if row.get("second_hold")]
        cohort_reused = [
            row
            for row in cohort
            if int(dict(row.get("selected_lifecycle") or {}).get("touch_count_proxy") or 0) > 0
        ]
        by_year[year] = {
            "first_reactions": len(cohort_all),
            "selected": len(cohort),
            "coverage_rate": len(cohort) / len(cohort_all) if cohort_all else None,
            "reused_selected": len(cohort_reused),
            "second_hold": len(cohort_holds),
            "second_hold_rate_all_selected": (
                len(cohort_holds) / len(cohort) if cohort else None
            ),
        }

    return {
        "first_reactions": n,
        "selected": len(selected),
        "coverage_rate": len(selected) / n if n else None,
        "resolved": len(resolved),
        "second_hold": len(holds),
        "second_hold_rate_all_selected": (
            len(holds) / len(selected) if selected else None
        ),
        "second_hold_rate_resolved": (
            len(holds) / len(resolved) if resolved else None
        ),
        "second_hold_wilson_lower_95_resolved": (
            wilson_lower_bound(len(holds), len(resolved)) if resolved else None
        ),
        "full_cycle_completion_rate": len(holds) / n if n else None,
        "fresh_selected": len(fresh),
        "reused_selected": len(reused),
        "reuse_share_of_selected": len(reused) / len(selected) if selected else None,
        "median_gap_usd": median(gaps) if gaps else None,
        "median_minutes_eligible_to_second_touch": (
            median(delays_touch) if delays_touch else None
        ),
        "median_minutes_eligible_to_second_outcome": (
            median(delays_outcome) if delays_outcome else None
        ),
        "by_lifecycle": by_lifecycle,
        "by_year": by_year,
    }


def evaluate_reusable_primary_reversal_cycles(
    bars: Sequence[Bar],
) -> dict[str, Any]:
    rows = _validate_bars(bars)
    destinations, episodes, ledger = build_transition_ledger(rows)
    episode_index = _episode_state_index(rows, episodes, destinations)
    bar_by_time = {ensure_utc(row.timestamp): row for row in rows}

    fresh_rows: list[dict[str, Any]] = []
    reusable_rows: list[dict[str, Any]] = []
    raw_nearby_counts = 0
    micro_required_nearby = 0

    for episode in episodes:
        if episode.outcome.status != "HOLD" or episode.outcome.outcome_at is None:
            continue
        outcome_bar_at = ensure_utc(episode.outcome.outcome_at)
        reaction_at = outcome_bar_at + timedelta(minutes=15)
        bar = bar_by_time.get(outcome_bar_at)
        if bar is None:
            continue
        reaction_price = float(bar.close)

        candidates = _candidate_pool_for_reaction(
            rows=rows,
            destinations=destinations,
            episode_index=episode_index,
            source_direction=episode.direction,
            reaction_at=reaction_at,
            reaction_price=reaction_price,
            handoff_window_minutes=HANDOFF_WINDOW_MINUTES,
            handoff_gap_usd=HANDOFF_GAP_USD,
        )
        raw_nearby_counts += int(bool(candidates))
        if any(
            int(dict(row.get("lifecycle") or {}).get("touch_count_proxy") or 0) > 0
            and not bool(dict(row.get("lifecycle") or {}).get("reusable_without_new_micro"))
            for row in candidates
        ):
            micro_required_nearby += 1

        fresh_selected = _select_candidate(candidates, allow_reuse=False)
        reusable_selected = _select_candidate(candidates, allow_reuse=True)

        common = {
            "source_zone_id": episode.zone_id,
            "source_direction": episode.direction,
            "source_timeframe": episode.timeframe,
            "reaction_bar_at": outcome_bar_at.isoformat(),
            "reaction_at": reaction_at.isoformat(),
            "reaction_price_close": reaction_price,
        }
        fresh_rows.append({
            **common,
            **_evaluate_selected(
                selected=fresh_selected,
                episode_index=episode_index,
            ),
        })
        reusable_rows.append({
            **common,
            **_evaluate_selected(
                selected=reusable_selected,
                episode_index=episode_index,
            ),
        })

    fresh_summary = _policy_summary(fresh_rows)
    reusable_summary = _policy_summary(reusable_rows)
    fresh_rate = float(fresh_summary.get("coverage_rate") or 0.0)
    reusable_rate = float(reusable_summary.get("coverage_rate") or 0.0)
    uplift_pp = (reusable_rate - fresh_rate) * 100.0
    reusable_n = int(reusable_summary.get("selected") or 0)
    reusable_hold_all = float(
        reusable_summary.get("second_hold_rate_all_selected") or 0.0
    )
    reusable_wilson = float(
        reusable_summary.get("second_hold_wilson_lower_95_resolved") or 0.0
    )
    gate_pass = bool(
        reusable_n >= MIN_REUSABLE_CANDIDATES
        and uplift_pp >= MIN_COVERAGE_UPLIFT_PP
        and reusable_hold_all >= MIN_SECOND_HOLD_RATE_ALL_ELIGIBLE
        and reusable_wilson >= MIN_SECOND_HOLD_WILSON_RESOLVED
    )

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "closed_m15_bars": len(rows),
        "data_start": ensure_utc(rows[0].timestamp).isoformat(),
        "data_end": ensure_utc(rows[-1].timestamp).isoformat(),
        "zones": len(destinations),
        "reaction_episodes": len(episodes),
        "ledger_events": len(ledger),
        "lifecycle_contract": {
            "production_reference": "XAU_ZONE_REUSE_CONTROLLER_V200",
            "historical_proxy": "V183_TOUCH_ORDINAL_PLUS_CAUSAL_M15_EPISODE_PENETRATION",
            "fresh": "0_PRIOR_CAUSALLY_KNOWN_TOUCHES",
            "reusable_without_new_micro": (
                "ONE_PRIOR_TOUCH_AND_MITIGATION_PROXY_BELOW_0.35"
            ),
            "partial_or_deep_or_multi_touch": "MICRO_RECONFIRMATION_REQUIRED_NOT_PROMOTED",
            "blind_reuse_allowed": False,
        },
        "authority_contract": (
            "V309_COMPATIBLE_FORWARD_REACHABLE_HISTORICAL_PROXY_WITHIN_5_USD"
        ),
        "fresh_only": fresh_summary,
        "fresh_plus_v200_reusable": reusable_summary,
        "comparison": {
            "coverage_uplift_percentage_points": uplift_pp,
            "additional_selected": (
                int(reusable_summary.get("selected") or 0)
                - int(fresh_summary.get("selected") or 0)
            ),
            "additional_second_holds": (
                int(reusable_summary.get("second_hold") or 0)
                - int(fresh_summary.get("second_hold") or 0)
            ),
            "raw_nearby_opposite_reaction_count": raw_nearby_counts,
            "micro_required_nearby_reaction_count": micro_required_nearby,
        },
        "pre_registered_research_gate": {
            "min_reusable_candidates": MIN_REUSABLE_CANDIDATES,
            "min_coverage_uplift_pp": MIN_COVERAGE_UPLIFT_PP,
            "min_second_hold_rate_all_eligible": MIN_SECOND_HOLD_RATE_ALL_ELIGIBLE,
            "min_second_hold_wilson_resolved": MIN_SECOND_HOLD_WILSON_RESOLVED,
            "passed": gate_pass,
            "interpretation": (
                "A pass only warrants deeper exact-entry research. It does not "
                "authorize production or DEMO execution changes."
            ),
        },
        "rows": {
            "fresh_only": fresh_rows,
            "fresh_plus_v200_reusable": reusable_rows,
        },
        "limitations": [
            "V200_LIVE_MITIGATION_DEPTH_NOT_PERSISTED_HISTORICALLY",
            "M15_EPISODE_PENETRATION_IS_A_CAUSAL_PROXY_NOT_PRODUCTION_PARITY",
            "NO_HISTORICAL_M5_MICRO_RECONFIRMATION_SO_REFRESH_REQUIRED_ZONES_ARE_EXCLUDED",
            "STRUCTURAL_REACTION_HOLD_IS_NOT_BROKER_TP_OR_FILL",
            "NO_EXECUTION_OR_PROMOTION_AUTHORITY",
        ],
    }
