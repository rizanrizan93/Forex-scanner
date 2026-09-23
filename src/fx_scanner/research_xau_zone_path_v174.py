from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from itertools import product
from math import isfinite, sqrt
from typing import Any, Sequence

from .demo_xau_afic_path_shadow_observer import (
    ZONE_MAX_AGE_HOURS,
    OriginZone,
    _h4_features,
    _origin_zones,
    _resample_completed,
    _stable_zone_id,
)
from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import _validate_bars

RESEARCH_VERSION = "XAU_ZONE_PATH_PRECISION_V174"
ARTIFACT_CONTRACT = "XAU_ZONE_PATH_PRECISION_V174_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

TOUCH_HORIZON_M15 = 64
REACTION_HORIZON_M15 = 8
REACTION_ATR_MULTIPLE = 0.75
ROUND_STEP_USD = 10.0
MIN_RULE_COVERAGE = 0.05
MIN_TRAIN_PER_DIRECTION = 40
MIN_CALIBRATION_PER_DIRECTION = 20
MIN_CLAIM_PER_DIRECTION = 100
CLAIM_PRECISION = 0.80
SPLIT_PURGE_HOURS = 18


@dataclass(frozen=True, slots=True)
class ZonePathOutcome:
    status: str
    touched: bool
    reversed_after_touch: bool
    touch_at: datetime | None
    outcome_at: datetime | None
    invalidated_at: datetime | None
    bars_to_touch: int | None
    bars_touch_to_reversal: int | None
    reaction_target: float
    max_reaction_points: float


@dataclass(frozen=True, slots=True)
class ZoneScenario:
    map_at: datetime
    zone_id: str
    direction: str
    zone_low: float
    zone_high: float
    map_price: float
    zone_distance_atr: float
    h4_directional_close_location: float
    zone_age_hours: float
    origin_displacement_range_atr: float
    origin_displacement_body_fraction: float
    zone_width_atr: float
    round_distance_atr: float
    prior_touch_count: int
    approach_efficiency: float
    approach_range_atr: float
    outcome: ZonePathOutcome


@dataclass(frozen=True, slots=True)
class Rule:
    distance_max: float
    close_location_max: float
    age_hours_max: float
    displacement_min: float
    body_fraction_min: float
    width_atr_max: float
    prior_touches_max: int

    @property
    def key(self) -> str:
        return (
            f"d{self.distance_max:.2f}_c{self.close_location_max:.2f}_"
            f"a{self.age_hours_max:.0f}_x{self.displacement_min:.2f}_"
            f"b{self.body_fraction_min:.2f}_w{self.width_atr_max:.2f}_"
            f"t{self.prior_touches_max}"
        )


def _touch(row: Bar, *, low: float, high: float) -> bool:
    return float(row.low) <= high and float(row.high) >= low


def _invalidated(row: Bar, *, low: float, high: float, direction: str) -> bool:
    if direction == "SHORT":
        return float(row.close) > high
    return float(row.close) < low


def evaluate_zone_path(
    bars: Sequence[Bar],
    *,
    forecast_at: datetime,
    direction: str,
    zone_low: float,
    zone_high: float,
    atr_points: float,
    touch_horizon_m15: int = TOUCH_HORIZON_M15,
    reaction_horizon_m15: int = REACTION_HORIZON_M15,
    reaction_atr_multiple: float = REACTION_ATR_MULTIPLE,
) -> ZonePathOutcome:
    """Label a causal zone forecast using conservative OHLC ordering.

    A forecast is made before the zone touch. A touch and invalidation in the
    same M15 candle is a failure. A reaction on the touch candle is ignored
    because OHLC cannot prove that the reaction happened after the touch.
    """
    normalized = str(direction).upper().strip()
    if normalized not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    low = float(zone_low)
    high = float(zone_high)
    atr = float(atr_points)
    if not (isfinite(low) and isfinite(high) and low < high):
        raise ValueError("zone bounds must be finite and ordered")
    if not isfinite(atr) or atr <= 0:
        raise ValueError("atr_points must be positive and finite")
    if touch_horizon_m15 <= 0 or reaction_horizon_m15 <= 0:
        raise ValueError("horizons must be positive")
    if reaction_atr_multiple <= 0:
        raise ValueError("reaction_atr_multiple must be positive")

    start = ensure_utc(forecast_at)
    rows = tuple(
        row
        for row in sorted(bars, key=lambda value: ensure_utc(value.timestamp))
        if ensure_utc(row.timestamp) >= start
    )
    reaction_points = atr * float(reaction_atr_multiple)
    target = high + reaction_points if normalized == "LONG" else low - reaction_points
    touch_index: int | None = None

    for index, row in enumerate(rows[:touch_horizon_m15]):
        invalid = _invalidated(
            row, low=low, high=high, direction=normalized
        )
        touched = _touch(row, low=low, high=high)
        if invalid:
            stamp = ensure_utc(row.timestamp)
            return ZonePathOutcome(
                status="INVALIDATED_BEFORE_TOUCH" if not touched else "TOUCH_INVALIDATED_SAME_BAR",
                touched=touched,
                reversed_after_touch=False,
                touch_at=stamp if touched else None,
                outcome_at=stamp,
                invalidated_at=stamp,
                bars_to_touch=index if touched else None,
                bars_touch_to_reversal=None,
                reaction_target=target,
                max_reaction_points=0.0,
            )
        if touched:
            touch_index = index
            break

    if touch_index is None:
        resolved = len(rows) >= touch_horizon_m15
        return ZonePathOutcome(
            status="TOUCH_TIMEOUT" if resolved else "PENDING_TOUCH",
            touched=False,
            reversed_after_touch=False,
            touch_at=None,
            outcome_at=(
                ensure_utc(rows[touch_horizon_m15 - 1].timestamp)
                if resolved
                else None
            ),
            invalidated_at=None,
            bars_to_touch=None,
            bars_touch_to_reversal=None,
            reaction_target=target,
            max_reaction_points=0.0,
        )

    touch_row = rows[touch_index]
    touch_at = ensure_utc(touch_row.timestamp)
    max_reaction = 0.0
    # Start on the next bar: the touch candle has unknowable intrabar ordering.
    reaction_rows = rows[
        touch_index + 1 : touch_index + 1 + reaction_horizon_m15
    ]
    for offset, row in enumerate(reaction_rows, start=1):
        invalid = _invalidated(
            row, low=low, high=high, direction=normalized
        )
        if normalized == "LONG":
            excursion = max(0.0, float(row.high) - high)
            reacted = float(row.high) >= target
        else:
            excursion = max(0.0, low - float(row.low))
            reacted = float(row.low) <= target
        max_reaction = max(max_reaction, excursion)
        # Conservative same-bar ambiguity: invalidation wins.
        if invalid:
            stamp = ensure_utc(row.timestamp)
            return ZonePathOutcome(
                status="INVALIDATED_AFTER_TOUCH",
                touched=True,
                reversed_after_touch=False,
                touch_at=touch_at,
                outcome_at=stamp,
                invalidated_at=stamp,
                bars_to_touch=touch_index,
                bars_touch_to_reversal=None,
                reaction_target=target,
                max_reaction_points=max_reaction,
            )
        if reacted:
            stamp = ensure_utc(row.timestamp)
            return ZonePathOutcome(
                status="TOUCH_REVERSED",
                touched=True,
                reversed_after_touch=True,
                touch_at=touch_at,
                outcome_at=stamp,
                invalidated_at=None,
                bars_to_touch=touch_index,
                bars_touch_to_reversal=offset,
                reaction_target=target,
                max_reaction_points=max_reaction,
            )

    resolved = len(reaction_rows) >= reaction_horizon_m15
    return ZonePathOutcome(
        status="REACTION_TIMEOUT" if resolved else "PENDING_REACTION",
        touched=True,
        reversed_after_touch=False,
        touch_at=touch_at,
        outcome_at=(
            ensure_utc(reaction_rows[-1].timestamp)
            if resolved and reaction_rows
            else None
        ),
        invalidated_at=None,
        bars_to_touch=touch_index,
        bars_touch_to_reversal=None,
        reaction_target=target,
        max_reaction_points=max_reaction,
    )


def wilson_lower_bound(successes: int, total: int, *, z: float = 1.959963984540054) -> float | None:
    if total <= 0:
        return None
    if successes < 0 or successes > total:
        raise ValueError("successes must be between zero and total")
    p = successes / total
    denominator = 1.0 + (z * z / total)
    center = p + (z * z / (2.0 * total))
    margin = z * sqrt((p * (1.0 - p) / total) + (z * z / (4.0 * total * total)))
    return max(0.0, (center - margin) / denominator)


def _resolved(scenario: ZoneScenario) -> bool:
    return scenario.outcome.status not in {"PENDING_TOUCH", "PENDING_REACTION"}


def _matches(rule: Rule, scenario: ZoneScenario) -> bool:
    return bool(
        scenario.zone_distance_atr <= rule.distance_max
        and scenario.h4_directional_close_location <= rule.close_location_max
        and scenario.zone_age_hours <= rule.age_hours_max
        and scenario.origin_displacement_range_atr >= rule.displacement_min
        and scenario.origin_displacement_body_fraction >= rule.body_fraction_min
        and scenario.zone_width_atr <= rule.width_atr_max
        and scenario.prior_touch_count <= rule.prior_touches_max
    )


def _direction_metrics(rows: Sequence[ZoneScenario], direction: str) -> dict[str, Any]:
    selected = [row for row in rows if row.direction == direction and _resolved(row)]
    touched = [row for row in selected if row.outcome.touched]
    path_hits = sum(row.outcome.reversed_after_touch for row in selected)
    touch_hits = len(touched)
    reaction_hits = sum(row.outcome.reversed_after_touch for row in touched)
    return {
        "resolved": len(selected),
        "touch_hits": touch_hits,
        "touch_precision": None if not selected else touch_hits / len(selected),
        "touch_wilson_lower_95": wilson_lower_bound(touch_hits, len(selected)),
        "reaction_population": len(touched),
        "reaction_hits": reaction_hits,
        "conditional_reaction_precision": None if not touched else reaction_hits / len(touched),
        "conditional_reaction_wilson_lower_95": wilson_lower_bound(reaction_hits, len(touched)),
        "path_hits": path_hits,
        "path_precision": None if not selected else path_hits / len(selected),
        "path_wilson_lower_95": wilson_lower_bound(path_hits, len(selected)),
    }


def precision_report(
    rows: Sequence[ZoneScenario], *, universe_size: int | None = None
) -> dict[str, Any]:
    resolved = [row for row in rows if _resolved(row)]
    base = len(resolved) if universe_size is None else int(universe_size)
    directions = {
        direction: _direction_metrics(resolved, direction)
        for direction in ("LONG", "SHORT")
    }
    claim_ready = all(
        metrics["resolved"] >= MIN_CLAIM_PER_DIRECTION
        and (metrics["path_precision"] or 0.0) >= CLAIM_PRECISION
        and (metrics["path_wilson_lower_95"] or 0.0) >= CLAIM_PRECISION
        for metrics in directions.values()
    )
    return {
        "selected_resolved": len(resolved),
        "coverage": None if base <= 0 else len(resolved) / base,
        "directions": directions,
        "claim_gate": {
            "target_precision": CLAIM_PRECISION,
            "minimum_resolved_per_direction": MIN_CLAIM_PER_DIRECTION,
            "requires_wilson_lower_95_at_target": True,
            "passed": claim_ready,
        },
    }


def candidate_rules() -> tuple[Rule, ...]:
    return tuple(
        Rule(*values)
        for values in product(
            (0.20, 0.30, 0.36, 0.50, 0.75, 1.00),
            (0.35, 0.50, 0.65, 0.80, 1.00),
            (4.0, 8.0, 12.0, 24.0),
            (1.00, 1.25, 1.50, 2.00),
            (0.50, 0.60, 0.70),
            (0.50, 1.00, 1.50),
            (0, 1),
        )
    )


def _bar_invalidated_at(zone: OriginZone, bars: Sequence[Bar]) -> datetime | None:
    for row in bars:
        stamp = ensure_utc(row.timestamp)
        if stamp < ensure_utc(zone.available_at):
            continue
        if _invalidated(
            row,
            low=float(zone.low),
            high=float(zone.high),
            direction=zone.direction,
        ):
            return stamp
    return None


def _prior_touches(zone: OriginZone, bars: Sequence[Bar], *, map_at: datetime) -> int:
    start = ensure_utc(zone.available_at)
    end = ensure_utc(map_at)
    return sum(
        _touch(row, low=float(zone.low), high=float(zone.high))
        for row in bars
        if start <= ensure_utc(row.timestamp) < end
    )


def _approach_features(
    bars: Sequence[Bar], *, map_at: datetime, zone: OriginZone
) -> tuple[float, float]:
    prior = [row for row in bars if ensure_utc(row.timestamp) < ensure_utc(map_at)][-8:]
    if len(prior) < 2 or not isfinite(float(zone.h1_atr)) or zone.h1_atr <= 0:
        return 0.0, 0.0
    closes = [float(row.close) for row in prior]
    total_path = sum(abs(right - left) for left, right in zip(closes, closes[1:]))
    if zone.direction == "SHORT":
        directional_net = closes[-1] - closes[0]
    else:
        directional_net = closes[0] - closes[-1]
    efficiency = 0.0 if total_path <= 0 else max(0.0, directional_net) / total_path
    approach_range = (max(float(row.high) for row in prior) - min(float(row.low) for row in prior)) / float(zone.h1_atr)
    return float(efficiency), float(approach_range)


def build_zone_scenarios(bars: Sequence[Bar]) -> tuple[ZoneScenario, ...]:
    rows = _validate_bars(bars)
    if len(rows) < 400:
        return ()
    last_closed_at = ensure_utc(rows[-1].timestamp) + timedelta(minutes=15)
    h4 = _resample_completed(rows, "4h", as_of=last_closed_at)
    zones = _origin_zones(rows, as_of=last_closed_at)
    invalidated_at = {
        _stable_zone_id(zone): _bar_invalidated_at(zone, rows)
        for zone in zones
    }
    scenarios: list[ZoneScenario] = []
    seen_zone_ids: set[str] = set()

    for index in range(20, len(h4)):
        map_row = h4.iloc[index]
        map_at = ensure_utc(map_row["time"].to_pydatetime())
        map_price = float(map_row["close"])
        open_price = float(map_row["open"])
        if map_price == open_price:
            continue
        direction = "LONG" if map_price > open_price else "SHORT"
        candidates = []
        for zone in zones:
            available_at = ensure_utc(zone.available_at)
            if available_at > map_at:
                continue
            if map_at - available_at > timedelta(hours=ZONE_MAX_AGE_HOURS):
                continue
            if zone.direction != direction:
                continue
            invalid_at = invalidated_at[_stable_zone_id(zone)]
            if invalid_at is not None and invalid_at < map_at:
                continue
            if direction == "SHORT" and float(zone.low) <= map_price:
                continue
            if direction == "LONG" and float(zone.high) >= map_price:
                continue
            candidates.append(zone)
        if not candidates:
            continue
        if direction == "SHORT":
            zone = min(candidates, key=lambda value: float(value.low) - map_price)
        else:
            zone = min(candidates, key=lambda value: map_price - float(value.high))
        zone_id = _stable_zone_id(zone)
        # One independent forecast episode per structural origin. Counting the
        # same zone on every H4 remap would inflate sample size and leak a zone
        # across chronological splits.
        if zone_id in seen_zone_ids:
            continue
        seen_zone_ids.add(zone_id)

        features = _h4_features(
            h4,
            index,
            continuation=direction,
            zone=zone,
            map_price=map_price,
        )
        distance = features.get("zone_distance_atr")
        close_location = features.get("h4_directional_close_location")
        if distance is None or close_location is None:
            continue
        future = [row for row in rows if ensure_utc(row.timestamp) >= map_at]
        outcome = evaluate_zone_path(
            future,
            forecast_at=map_at,
            direction=direction,
            zone_low=float(zone.low),
            zone_high=float(zone.high),
            atr_points=float(zone.h1_atr),
        )
        boundary = float(zone.low) if direction == "SHORT" else float(zone.high)
        round_distance = abs(boundary - round(boundary / ROUND_STEP_USD) * ROUND_STEP_USD)
        approach_efficiency, approach_range = _approach_features(
            rows, map_at=map_at, zone=zone
        )
        scenarios.append(
            ZoneScenario(
                map_at=map_at,
                zone_id=zone_id,
                direction=direction,
                zone_low=float(zone.low),
                zone_high=float(zone.high),
                map_price=map_price,
                zone_distance_atr=float(distance),
                h4_directional_close_location=float(close_location),
                zone_age_hours=float(features["zone_age_hours"]),
                origin_displacement_range_atr=float(zone.displacement_range_atr),
                origin_displacement_body_fraction=float(zone.displacement_body_fraction),
                zone_width_atr=(float(zone.high) - float(zone.low)) / float(zone.h1_atr),
                round_distance_atr=round_distance / float(zone.h1_atr),
                prior_touch_count=_prior_touches(zone, rows, map_at=map_at),
                approach_efficiency=approach_efficiency,
                approach_range_atr=approach_range,
                outcome=outcome,
            )
        )
    return tuple(scenarios)


def _split(rows: Sequence[ZoneScenario]) -> tuple[tuple[ZoneScenario, ...], ...]:
    ordered = tuple(sorted(rows, key=lambda row: row.map_at))
    train_end = int(len(ordered) * 0.60)
    calibration_end = int(len(ordered) * 0.80)
    if train_end >= len(ordered) or calibration_end >= len(ordered):
        return ordered[:train_end], ordered[train_end:calibration_end], ordered[calibration_end:]
    calibration_start = ordered[train_end].map_at
    test_start = ordered[calibration_end].map_at
    purge = timedelta(hours=SPLIT_PURGE_HOURS)
    return (
        tuple(row for row in ordered[:train_end] if row.map_at + purge < calibration_start),
        tuple(
            row
            for row in ordered[train_end:calibration_end]
            if row.map_at + purge < test_start
        ),
        ordered[calibration_end:],
    )


def _eligible_rule_report(
    rule: Rule,
    rows: Sequence[ZoneScenario],
    *,
    min_per_direction: int,
) -> tuple[float, dict[str, Any]] | None:
    selected = [row for row in rows if _matches(rule, row)]
    report = precision_report(selected, universe_size=len(rows))
    direction_rows = report["directions"]
    if report["coverage"] is None or report["coverage"] < MIN_RULE_COVERAGE:
        return None
    if any(
        direction_rows[direction]["resolved"] < min_per_direction
        for direction in ("LONG", "SHORT")
    ):
        return None
    score = min(
        float(direction_rows[direction]["path_wilson_lower_95"] or 0.0)
        for direction in ("LONG", "SHORT")
    )
    return score, report


def select_rule(
    train: Sequence[ZoneScenario], calibration: Sequence[ZoneScenario]
) -> tuple[Rule | None, dict[str, Any]]:
    train_ranked: list[tuple[float, Rule, dict[str, Any]]] = []
    for rule in candidate_rules():
        evaluated = _eligible_rule_report(
            rule, train, min_per_direction=MIN_TRAIN_PER_DIRECTION
        )
        if evaluated is not None:
            score, report = evaluated
            train_ranked.append((score, rule, report))
    train_ranked.sort(key=lambda item: (item[0], item[2]["coverage"]), reverse=True)

    calibration_ranked: list[tuple[float, Rule, dict[str, Any], dict[str, Any]]] = []
    for _, rule, train_report in train_ranked[:50]:
        evaluated = _eligible_rule_report(
            rule,
            calibration,
            min_per_direction=MIN_CALIBRATION_PER_DIRECTION,
        )
        if evaluated is None:
            continue
        score, calibration_report = evaluated
        calibration_ranked.append((score, rule, train_report, calibration_report))
    calibration_ranked.sort(
        key=lambda item: (item[0], item[3]["coverage"]), reverse=True
    )
    if not calibration_ranked:
        return None, {
            "candidate_rules": len(candidate_rules()),
            "train_eligible": len(train_ranked),
            "calibration_eligible": 0,
            "reason": "NO_RULE_SURVIVED_CAUSAL_SELECTION",
        }
    _, rule, train_report, calibration_report = calibration_ranked[0]
    return rule, {
        "candidate_rules": len(candidate_rules()),
        "train_eligible": len(train_ranked),
        "calibration_eligible": len(calibration_ranked),
        "selected_rule": asdict(rule) | {"key": rule.key},
        "train": train_report,
        "calibration": calibration_report,
    }


def evaluate_zone_path_research(bars: Sequence[Bar]) -> dict[str, Any]:
    scenarios = build_zone_scenarios(bars)
    resolved = tuple(row for row in scenarios if _resolved(row))
    train, calibration, test = _split(resolved)
    rule, selection = select_rule(train, calibration)
    if rule is None:
        test_report = precision_report((), universe_size=len(test))
        decision = "REJECT_NO_CAUSAL_RULE"
    else:
        selected_test = tuple(row for row in test if _matches(rule, row))
        test_report = precision_report(selected_test, universe_size=len(test))
        decision = (
            "RESEARCH_TARGET_MET"
            if test_report["claim_gate"]["passed"]
            else "REJECT_80_PERCENT_NOT_PROVEN"
        )
    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "label_contract": {
            "touch_horizon_m15": TOUCH_HORIZON_M15,
            "reaction_horizon_m15": REACTION_HORIZON_M15,
            "reaction_atr_multiple": REACTION_ATR_MULTIPLE,
            "same_bar_ambiguity": "INVALIDATION_WINS_AND_TOUCH_BAR_REACTION_IGNORED",
        },
        "scenarios": len(scenarios),
        "resolved_scenarios": len(resolved),
        "split": {
            "train": len(train),
            "calibration": len(calibration),
            "test": len(test),
            "purge_hours": SPLIT_PURGE_HOURS,
            "unique_zone_episode": True,
        },
        "selection": selection,
        "untouched_test": test_report,
        "decision": decision,
        "notes": [
            "The 80% target is tested on the full touch-then-reversal path, not only after-touch confirmation.",
            "BUY/LONG and SELL/SHORT must each pass the sample-size and Wilson lower-bound gate.",
            "V174 is research-only and cannot alter AFIC admission or broker execution.",
        ],
    }
