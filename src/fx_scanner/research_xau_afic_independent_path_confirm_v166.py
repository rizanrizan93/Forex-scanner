from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from types import SimpleNamespace
from typing import Any, Sequence

from .models import Bar, ensure_utc
from .research_xau_afic_displacement_origin_v154 import (
    OriginZone,
    _h1_origin_zones,
    _published_round_target,
    _zone_stop,
)
from .research_xau_afic_h4_map_selector_v161 import (
    PRIMARY_SELECTOR,
    WINDOWS,
    _selected,
)
from .research_xau_afic_h4_selector_diagnostic_v160 import (
    _features,
    _h4_feature_table,
)
from .research_xau_afic_m15_confirm_semantics_v165 import (
    CONTROL_RULE,
    _directional_rejection,
)
from .research_xau_afic_planb_remap_v159 import (
    CONFIRM_WINDOW_M15,
    FIRST_LEG_HORIZON_M15,
    SECOND_LEG_HORIZON_M15,
    PathScenario,
    _bar_times,
    _choose_reaction_zone,
    _index_at_or_after,
    _second_leg_outcome,
    _touch,
    _zone_invalidated,
)
from .research_xau_afic_public_path_state_v155 import _m15_engulfing_rejection

RESEARCH_VERSION = "XAU_AFIC_INDEPENDENT_PATH_CONFIRM_V166"
ARTIFACT_CONTRACT = "XAU_AFIC_INDEPENDENT_PATH_CONFIRM_V166_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

CANDIDATE_RULE = "DIRECTIONAL_REJECTION"
RULES = (CONTROL_RULE, CANDIDATE_RULE)


@dataclass(frozen=True)
class MapDecision:
    map_at: datetime
    had_zone: bool
    selector_pass: bool
    blocked: bool


def _confirmation_fires(
    rows: Sequence[Bar],
    i: int,
    zone: OriginZone,
    rule: str,
) -> bool:
    if rule == CONTROL_RULE:
        return bool(_m15_engulfing_rejection(rows, i, zone))
    if rule == CANDIDATE_RULE:
        return bool(_directional_rejection(rows, i, zone))
    raise ValueError(f"V166_UNKNOWN_RULE:{rule}")


def _map_stub(
    *,
    map_at: datetime,
    continuation: str,
    zone: OriginZone,
    price: float,
) -> Any:
    return SimpleNamespace(
        map_at=ensure_utc(map_at),
        continuation_direction=continuation,
        zone=zone,
        map_price=float(price),
    )


def _build_selected_one(
    *,
    bars: Sequence[Bar],
    times: Sequence[datetime],
    zone: OriginZone,
    map_at: datetime,
    price: float,
    continuation: str,
    rule: str,
    remap_parent_at: datetime | None,
) -> PathScenario | None:
    first_leg = "SHORT" if continuation == "LONG" else "LONG"
    start_i = _index_at_or_after(times, map_at)
    if start_i >= len(bars):
        return None
    end_i = min(len(bars) - 1, start_i + FIRST_LEG_HORIZON_M15)

    touch_i = None
    invalid_i = None
    for i in range(start_i, end_i + 1):
        row = bars[i]
        if _zone_invalidated(row, zone):
            invalid_i = i
            break
        if _touch(row, zone):
            touch_i = i
            break

    if touch_i is None:
        failure_i = invalid_i if invalid_i is not None else end_i
        return PathScenario(
            ensure_utc(map_at),
            continuation,
            first_leg,
            zone,
            float(price),
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "FAILED",
            ensure_utc(bars[failure_i].timestamp),
            "ZONE_INVALIDATED" if invalid_i is not None else "FIRST_LEG_TIMEOUT",
            remap_parent_at,
        )

    confirm_i = None
    c_end = min(len(bars) - 2, int(touch_i) + CONFIRM_WINDOW_M15)
    for i in range(int(touch_i), c_end + 1):
        if _zone_invalidated(bars[i], zone):
            invalid_i = i
            break
        if _confirmation_fires(bars, i, zone, rule):
            confirm_i = i
            break

    if confirm_i is None:
        failure_i = invalid_i if invalid_i is not None else c_end
        return PathScenario(
            ensure_utc(map_at),
            continuation,
            first_leg,
            zone,
            float(price),
            ensure_utc(bars[touch_i].timestamp),
            int(touch_i),
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "ZONE_HIT_NO_CONFIRM",
            ensure_utc(bars[failure_i].timestamp),
            "ZONE_INVALIDATED_AFTER_TOUCH"
            if invalid_i is not None
            else "CONFIRM_TIMEOUT",
            remap_parent_at,
        )

    entry_i = int(confirm_i) + 1
    if entry_i >= len(bars):
        return None
    entry = float(bars[entry_i].open)
    stop = float(_zone_stop(zone))
    target = _published_round_target(entry, stop, continuation)
    if target is None:
        return PathScenario(
            ensure_utc(map_at),
            continuation,
            first_leg,
            zone,
            float(price),
            ensure_utc(bars[touch_i].timestamp),
            int(touch_i),
            ensure_utc(bars[confirm_i].timestamp),
            int(confirm_i),
            ensure_utc(bars[entry_i].timestamp),
            entry,
            stop,
            None,
            None,
            "CONFIRMED_NO_TARGET_GEOMETRY",
            ensure_utc(bars[entry_i].timestamp),
            "NO_PUBLISHED_TARGET_GEOMETRY",
            remap_parent_at,
        )

    _, terminal, ladder = target
    return PathScenario(
        ensure_utc(map_at),
        continuation,
        first_leg,
        zone,
        float(price),
        ensure_utc(bars[touch_i].timestamp),
        int(touch_i),
        ensure_utc(bars[confirm_i].timestamp),
        int(confirm_i),
        ensure_utc(bars[entry_i].timestamp),
        entry,
        stop,
        float(ladder[0]),
        float(terminal),
        "CONFIRMED",
        None,
        None,
        remap_parent_at,
    )


def build_independent_rule_path(
    rows: Sequence[Bar],
    *,
    evaluation_end: datetime,
    rule: str,
) -> tuple[tuple[PathScenario, ...], tuple[MapDecision, ...]]:
    if rule not in RULES:
        raise ValueError(f"V166_UNKNOWN_RULE:{rule}")

    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    times = _bar_times(bars)
    zones = _h1_origin_zones(bars)
    h4 = _h4_feature_table(bars)
    end = ensure_utc(evaluation_end)

    scenarios: list[PathScenario] = []
    decisions: list[MapDecision] = []
    blocked_until: datetime | None = None
    remap_parent: datetime | None = None

    for hi, (_, row) in enumerate(h4.iterrows()):
        map_at = ensure_utc(
            row["time"].to_pydatetime()
            if hasattr(row["time"], "to_pydatetime")
            else row["time"]
        )
        if map_at >= end:
            break
        if hi < 1:
            continue

        if blocked_until is not None and map_at < blocked_until:
            decisions.append(
                MapDecision(
                    map_at=map_at,
                    had_zone=False,
                    selector_pass=False,
                    blocked=True,
                )
            )
            continue

        o = float(row["open"])
        c = float(row["close"])
        if c == o:
            decisions.append(
                MapDecision(
                    map_at=map_at,
                    had_zone=False,
                    selector_pass=False,
                    blocked=False,
                )
            )
            continue

        continuation = "LONG" if c > o else "SHORT"
        price = c
        zone = _choose_reaction_zone(
            zones,
            timestamp=map_at,
            price=price,
            h4_direction=continuation,
        )
        if zone is None:
            decisions.append(
                MapDecision(
                    map_at=map_at,
                    had_zone=False,
                    selector_pass=False,
                    blocked=False,
                )
            )
            continue

        stub = _map_stub(
            map_at=map_at,
            continuation=continuation,
            zone=zone,
            price=price,
        )
        feats = _features(h4, hi, stub)
        selected = bool(_selected(feats, PRIMARY_SELECTOR))
        decisions.append(
            MapDecision(
                map_at=map_at,
                had_zone=True,
                selector_pass=selected,
                blocked=False,
            )
        )
        if not selected:
            # Selector-rejected H4 maps are not AFIC path states and must not
            # consume the blocking/remap clock.
            continue

        scenario = _build_selected_one(
            bars=bars,
            times=times,
            zone=zone,
            map_at=map_at,
            price=price,
            continuation=continuation,
            rule=rule,
            remap_parent_at=remap_parent,
        )
        if scenario is None:
            continue
        scenarios.append(scenario)

        if scenario.primary_status == "CONFIRMED" and scenario.confirm_index is not None:
            blocked_i = min(
                len(bars) - 1,
                int(scenario.confirm_index) + 1 + SECOND_LEG_HORIZON_M15,
            )
            blocked_until = ensure_utc(bars[blocked_i].timestamp)
            remap_parent = None
        else:
            failure = scenario.failure_at or map_at
            blocked_until = ensure_utc(failure)
            remap_parent = scenario.map_at

    return tuple(scenarios), tuple(decisions)


def _window_summary(
    bars: Sequence[Bar],
    scenarios: Sequence[PathScenario],
    decisions: Sequence[MapDecision],
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    start = ensure_utc(start)
    end = ensure_utc(end)
    ss = tuple(s for s in scenarios if start <= ensure_utc(s.map_at) < end)
    dd = tuple(d for d in decisions if start <= ensure_utc(d.map_at) < end)

    unblocked = tuple(d for d in dd if not d.blocked)
    with_zone = tuple(d for d in unblocked if d.had_zone)
    selected = tuple(d for d in with_zone if d.selector_pass)

    first_hit = tuple(s for s in ss if s.first_touch_index is not None)
    raw_confirm = tuple(s for s in ss if s.confirm_index is not None)
    feasible = tuple(s for s in ss if s.primary_status == "CONFIRMED")
    infeasible = tuple(
        s for s in ss if s.primary_status == "CONFIRMED_NO_TARGET_GEOMETRY"
    )

    outcomes = tuple(
        _second_leg_outcome(
            f=s,
            bars=bars,
            confirm_index=int(s.confirm_index),
        )
        for s in feasible
        if s.confirm_index is not None
    )
    delays = [
        int(s.confirm_index) - int(s.first_touch_index)
        for s in raw_confirm
        if s.confirm_index is not None and s.first_touch_index is not None
    ]

    remaps = tuple(s for s in ss if s.remap_parent_at is not None)
    remap_first = tuple(s for s in remaps if s.first_touch_index is not None)
    remap_confirm = tuple(s for s in remaps if s.confirm_index is not None)
    remap_feasible = tuple(s for s in remaps if s.primary_status == "CONFIRMED")

    return {
        "h4_map_checks": len(dd),
        "blocked_h4_closes": sum(d.blocked for d in dd),
        "unblocked_h4_map_checks": len(unblocked),
        "reaction_zone_candidates": len(with_zone),
        "selector_pass_count": len(selected),
        "selector_pass_rate_given_zone": None
        if not with_zone
        else len(selected) / len(with_zone),
        "scenarios": len(ss),
        "first_leg_zone_hits": len(first_hit),
        "first_leg_zone_hit_rate": None if not ss else len(first_hit) / len(ss),
        "raw_confirmation_count": len(raw_confirm),
        "confirmation_rate_given_hit": None
        if not first_hit
        else len(raw_confirm) / len(first_hit),
        "geometry_feasible_count": len(feasible),
        "geometry_infeasible_count": len(infeasible),
        "geometry_feasible_rate_given_raw_confirm": None
        if not raw_confirm
        else len(feasible) / len(raw_confirm),
        "tp1_rate_given_feasible": None
        if not outcomes
        else sum(bool(x["tp1_hit"]) for x in outcomes) / len(outcomes),
        "terminal_rate_given_feasible": None
        if not outcomes
        else sum(bool(x["terminal_hit"]) for x in outcomes) / len(outcomes),
        "stop_rate_given_feasible": None
        if not outcomes
        else sum(bool(x["stop_hit"]) for x in outcomes) / len(outcomes),
        "median_confirmation_delay_bars": None
        if not delays
        else float(median(delays)),
        "remap_count": len(remaps),
        "remap_first_leg_recovery_rate": None
        if not remaps
        else len(remap_first) / len(remaps),
        "remap_raw_confirm_recovery_rate": None
        if not remaps
        else len(remap_confirm) / len(remaps),
        "remap_feasible_recovery_rate": None
        if not remaps
        else len(remap_feasible) / len(remaps),
        "direction_counts": {
            "CONT_LONG": sum(s.continuation_direction == "LONG" for s in ss),
            "CONT_SHORT": sum(s.continuation_direction == "SHORT" for s in ss),
        },
        "status_counts": {
            k: sum(s.primary_status == k for s in ss)
            for k in sorted({s.primary_status for s in ss})
        },
    }


def evaluate_v166(
    rows: Sequence[Bar],
    *,
    evaluation_end: datetime,
) -> dict[str, Any]:
    end = ensure_utc(evaluation_end)
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))

    rule_paths: dict[str, tuple[tuple[PathScenario, ...], tuple[MapDecision, ...]]] = {}
    for rule in RULES:
        rule_paths[rule] = build_independent_rule_path(
            bars,
            evaluation_end=end,
            rule=rule,
        )

    full_start = datetime(2012, 1, 1, tzinfo=timezone.utc)
    full = {
        rule: _window_summary(
            bars,
            rule_paths[rule][0],
            rule_paths[rule][1],
            full_start,
            end,
        )
        for rule in RULES
    }

    windows: dict[str, Any] = {}
    for label, start, stop in WINDOWS:
        bounded_stop = min(ensure_utc(stop), end)
        if ensure_utc(start) >= bounded_stop:
            continue
        windows[label] = {
            rule: _window_summary(
                bars,
                rule_paths[rule][0],
                rule_paths[rule][1],
                start,
                bounded_stop,
            )
            for rule in RULES
        }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "rules": list(RULES),
        "primary_selector": PRIMARY_SELECTOR,
        "selector_contract": {
            "zone_distance_atr_max": 0.75,
            "h4_directional_close_location_max": 0.65,
            "selector_applied_before_path_blocking": True,
            "selector_rejected_map_does_not_block": True,
            "unchanged_from_v161": True,
        },
        "path_contract": {
            "rule_specific_independent_blocking": True,
            "rule_specific_independent_remap": True,
            "first_leg_horizon_m15": FIRST_LEG_HORIZON_M15,
            "confirmation_window_m15": CONFIRM_WINDOW_M15,
            "second_leg_horizon_m15": SECOND_LEG_HORIZON_M15,
            "stop_geometry": "V154_H1_ORIGIN_DISTAL",
            "target_geometry": "V154_PSYCHOLOGICAL_LIQUIDITY_LADDER",
            "same_bar_ambiguity": "STOP_DOMINATES",
            "entry": "NEXT_M15_OPEN_HISTORICAL_COMPARISON_ONLY",
        },
        "evidence_contract": {
            CONTROL_RULE: "PUBLIC_EXAMPLE_STRONG_CONFIRMATION_CONTROL",
            CANDIDATE_RULE: "PUBLIC_REJECTION_WORDING_DIAGNOSTIC",
            "candidate_preregistered_from_v165": True,
            "sweep_reclaim_excluded_from_v166": True,
            "sweep_exclusion_reason": (
                "V165 negative control: materially worse TP1/stop profile; "
                "exclude to reduce multiple testing rather than retune it."
            ),
            "no_threshold_grid": True,
            "no_same_sample_promotion": True,
        },
        "full": full,
        "windows": windows,
        "note": (
            "V166 removes V165 matched-map path blocking bias by letting strict "
            "engulf/rejection and directional rejection form their own selector-first "
            "scenario/remap clocks. It remains research-only and cannot change DEMO "
            "or LIVE execution."
        ),
    }
