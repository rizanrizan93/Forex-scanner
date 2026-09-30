from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import timedelta
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
    _evaluate_reaction_handoffs_from_dataset,
    build_transition_ledger,
)

RESEARCH_VERSION = "XAU_STRUCTURAL_CYCLE_V311"
ARTIFACT_CONTRACT = "XAU_STRUCTURAL_CYCLE_V311_EVIDENCE_1"
POLICY_EFFECT = "RESEARCH_ONLY"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
PROMOTION_AUTHORITY = False


def _next_episode(
    episodes_by_zone: dict[str, list[ReactionEpisode]],
    *,
    zone_id: str,
    eligible_at,
) -> ReactionEpisode | None:
    cutoff = ensure_utc(eligible_at)
    for episode in episodes_by_zone.get(zone_id, []):
        touch_at = ensure_utc(episode.touch_at)
        if touch_at < cutoff:
            continue
        if episode.outcome.status in {"HOLD", "BREAK", "BREAK_TOUCH_BAR", "STALL"}:
            return episode
    return None


def _evaluate_cycles_from_dataset(
    *,
    destinations: Sequence[ZoneDestination],
    episodes: Sequence[ReactionEpisode],
    handoffs: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    by_zone = {row.zone_id: row for row in destinations}
    episodes_by_zone: dict[str, list[ReactionEpisode]] = defaultdict(list)
    for episode in episodes:
        episodes_by_zone[episode.zone_id].append(episode)
    for rows in episodes_by_zone.values():
        rows.sort(key=lambda row: ensure_utc(row.touch_at))

    output: list[dict[str, Any]] = []
    for handoff in handoffs:
        reaction_at = ensure_utc(handoff["reaction_at"])
        selected_id = str(handoff.get("selected_zone_id") or "")
        origin = handoff.get("selected_origin")
        if not selected_id:
            output.append({
                **dict(handoff),
                "cycle_state": "NO_OPPOSITE_ZONE",
                "clean_opposite_entry_candidate": False,
                "second_reaction_status": None,
                "structural_cycle_success": False,
            })
            continue

        zone = by_zone.get(selected_id)
        if zone is None:
            output.append({
                **dict(handoff),
                "cycle_state": "SELECTED_ZONE_MISSING",
                "clean_opposite_entry_candidate": False,
                "second_reaction_status": None,
                "structural_cycle_success": False,
            })
            continue

        already_touched = bool(handoff.get("selected_already_touched"))
        if already_touched:
            output.append({
                **dict(handoff),
                "cycle_state": "OPPOSITE_ALREADY_TOUCHED",
                "clean_opposite_entry_candidate": False,
                "selected_zone_class": zone.zone_class,
                "selected_zone_pattern": zone.pattern,
                "second_reaction_status": None,
                "structural_cycle_success": False,
            })
            continue

        eligible_at = reaction_at
        if origin == "NEW_WITHIN_WINDOW":
            eligible_at = max(reaction_at, ensure_utc(zone.available_at))

        second = _next_episode(
            episodes_by_zone,
            zone_id=selected_id,
            eligible_at=eligible_at,
        )
        if second is None:
            output.append({
                **dict(handoff),
                "cycle_state": "CLEAN_OPPOSITE_NO_RESOLVED_REACTION",
                "clean_opposite_entry_candidate": True,
                "selected_zone_class": zone.zone_class,
                "selected_zone_pattern": zone.pattern,
                "selected_zone_available_at": ensure_utc(zone.available_at).isoformat(),
                "eligible_at": ensure_utc(eligible_at).isoformat(),
                "second_reaction_status": None,
                "structural_cycle_success": False,
            })
            continue

        touch_at = ensure_utc(second.touch_at)
        outcome_bar_at = (
            None if second.outcome.outcome_at is None
            else ensure_utc(second.outcome.outcome_at)
        )
        outcome_known_at = (
            None if outcome_bar_at is None
            else outcome_bar_at + timedelta(minutes=15)
        )
        status = str(second.outcome.status)
        success = status == "HOLD"

        output.append({
            **dict(handoff),
            "cycle_state": (
                "SECOND_REACTION_HOLD"
                if success
                else "SECOND_REACTION_BREAK"
                if status in {"BREAK", "BREAK_TOUCH_BAR"}
                else "SECOND_REACTION_STALL"
            ),
            "clean_opposite_entry_candidate": True,
            "selected_zone_class": zone.zone_class,
            "selected_zone_pattern": zone.pattern,
            "selected_zone_available_at": ensure_utc(zone.available_at).isoformat(),
            "eligible_at": ensure_utc(eligible_at).isoformat(),
            "second_touch_bar_at": touch_at.isoformat(),
            "second_touch_known_at": (touch_at + timedelta(minutes=15)).isoformat(),
            "second_reaction_status": status,
            "second_reaction_bar_at": (
                None if outcome_bar_at is None else outcome_bar_at.isoformat()
            ),
            "second_reaction_at": (
                None if outcome_known_at is None else outcome_known_at.isoformat()
            ),
            "minutes_reaction_to_second_touch": (
                touch_at - reaction_at
            ).total_seconds() / 60.0,
            "minutes_reaction_to_second_outcome": (
                None
                if outcome_known_at is None
                else (outcome_known_at - reaction_at).total_seconds() / 60.0
            ),
            "second_touch_bucket": second.touch_bucket,
            "second_session_context": second.session_context,
            "second_htf_nesting_count": int(second.htf_nesting_count),
            "second_mfe_atr": float(second.outcome.max_favorable_excursion_atr),
            "second_mae_atr": float(second.outcome.max_adverse_excursion_atr),
            "structural_cycle_success": success,
        })

    output.sort(key=lambda row: (str(row.get("reaction_at")), str(row.get("source_zone_id"))))
    return tuple(output)


def _summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    all_rows = list(rows)
    first_n = len(all_rows)
    selected = [row for row in all_rows if row.get("selected_zone_id")]
    clean = [row for row in all_rows if row.get("clean_opposite_entry_candidate")]
    resolved = [row for row in clean if row.get("second_reaction_status")]
    success = [row for row in clean if row.get("structural_cycle_success")]
    breaks = [
        row for row in clean
        if row.get("second_reaction_status") in {"BREAK", "BREAK_TOUCH_BAR"}
    ]
    stalls = [row for row in clean if row.get("second_reaction_status") == "STALL"]

    delays_touch = [
        float(row["minutes_reaction_to_second_touch"])
        for row in resolved
        if row.get("minutes_reaction_to_second_touch") is not None
    ]
    delays_outcome = [
        float(row["minutes_reaction_to_second_outcome"])
        for row in resolved
        if row.get("minutes_reaction_to_second_outcome") is not None
    ]

    by_origin: dict[str, dict[str, Any]] = {}
    for origin in ("ACTIVE_AT_REACTION", "NEW_WITHIN_WINDOW"):
        cohort = [row for row in clean if row.get("selected_origin") == origin]
        cohort_resolved = [row for row in cohort if row.get("second_reaction_status")]
        cohort_success = [row for row in cohort if row.get("structural_cycle_success")]
        by_origin[origin] = {
            "n": len(cohort),
            "resolved": len(cohort_resolved),
            "second_hold": len(cohort_success),
            "second_hold_rate_all_clean": (
                len(cohort_success) / len(cohort) if cohort else None
            ),
            "second_hold_rate_resolved": (
                len(cohort_success) / len(cohort_resolved)
                if cohort_resolved else None
            ),
        }

    by_zone_type: dict[str, dict[str, Any]] = {}
    keys = sorted({
        f"{row.get('selected_zone_class')}|{row.get('selected_zone_timeframe')}"
        for row in clean
    })
    for key in keys:
        zone_class, timeframe = key.split("|", 1)
        cohort = [
            row for row in clean
            if str(row.get("selected_zone_class")) == zone_class
            and str(row.get("selected_zone_timeframe")) == timeframe
        ]
        cohort_resolved = [row for row in cohort if row.get("second_reaction_status")]
        cohort_success = [row for row in cohort if row.get("structural_cycle_success")]
        by_zone_type[key] = {
            "n": len(cohort),
            "resolved": len(cohort_resolved),
            "second_hold": len(cohort_success),
            "second_hold_rate_all_clean": (
                len(cohort_success) / len(cohort) if cohort else None
            ),
        }

    by_year: dict[str, dict[str, Any]] = {}
    for year in sorted({str(row.get("reaction_at"))[:4] for row in all_rows}):
        cohort_all = [row for row in all_rows if str(row.get("reaction_at")).startswith(year)]
        cohort_clean = [row for row in cohort_all if row.get("clean_opposite_entry_candidate")]
        cohort_success = [row for row in cohort_clean if row.get("structural_cycle_success")]
        by_year[year] = {
            "first_reaction_milestones": len(cohort_all),
            "clean_opposite_candidates": len(cohort_clean),
            "clean_candidate_rate": (
                len(cohort_clean) / len(cohort_all) if cohort_all else None
            ),
            "second_hold": len(cohort_success),
            "second_hold_rate_all_clean": (
                len(cohort_success) / len(cohort_clean) if cohort_clean else None
            ),
        }

    return {
        "first_reaction_milestones": first_n,
        "selected_opposite_any": len(selected),
        "selected_opposite_rate": len(selected) / first_n if first_n else None,
        "clean_opposite_candidates": len(clean),
        "clean_candidate_rate_of_first_reactions": (
            len(clean) / first_n if first_n else None
        ),
        "resolved_clean_cycles": len(resolved),
        "second_hold": len(success),
        "second_break": len(breaks),
        "second_stall": len(stalls),
        "unresolved_clean_cycles": len(clean) - len(resolved),
        "second_hold_rate_all_clean": (
            len(success) / len(clean) if clean else None
        ),
        "second_hold_rate_resolved": (
            len(success) / len(resolved) if resolved else None
        ),
        "second_hold_wilson_lower_95_resolved": (
            wilson_lower_bound(len(success), len(resolved))
            if resolved else None
        ),
        "structural_cycle_completion_rate_of_first_reactions": (
            len(success) / first_n if first_n else None
        ),
        "median_minutes_reaction_to_second_touch": (
            median(delays_touch) if delays_touch else None
        ),
        "median_minutes_reaction_to_second_outcome": (
            median(delays_outcome) if delays_outcome else None
        ),
        "by_origin": by_origin,
        "by_selected_zone_type": by_zone_type,
        "by_year": by_year,
    }


def evaluate_structural_cycles(bars: Sequence[Bar]) -> dict[str, Any]:
    rows = _validate_bars(bars)
    destinations, episodes, ledger = build_transition_ledger(rows)
    handoffs = _evaluate_reaction_handoffs_from_dataset(
        rows,
        destinations=destinations,
        episodes=episodes,
        handoff_window_minutes=HANDOFF_WINDOW_MINUTES,
        handoff_gap_usd=HANDOFF_GAP_USD,
    )
    cycles = _evaluate_cycles_from_dataset(
        destinations=destinations,
        episodes=episodes,
        handoffs=handoffs,
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
        "summary": _summary(cycles),
        "cycles": list(cycles),
        "interpretation": (
            "V311 tests a structural analogue of reaction -> opposite-zone -> reaction. "
            "A first or second HOLD means >=0.50 ATR V183 reaction, not an executed trade TP. "
            "Only previously untouched opposite zones count as clean next-entry candidates. "
            "Results are research evidence and cannot alter DEMO execution."
        ),
    }
