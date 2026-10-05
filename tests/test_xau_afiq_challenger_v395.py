from __future__ import annotations

from copy import deepcopy

from fx_scanner.xau_afiq_challenger_v395 import evaluate_afiq_challenger_v395


def _oct5_like_context(price: float = 4142.0) -> dict:
    return {
        "price_now": price,
        "effective_zones": [
            {
                "zone_id": "H4_DEMAND_EFFECTIVE",
                "direction": "LONG",
                "timeframe": "H4",
                "low": 4110.0,
                "high": 4144.0,
                "role": "MAIN_REVERSAL_DEMAND",
                "condition": "ACTIVE",
                "strength": 2.0,
                "structural_invalidation": 4110.0,
                "validation_level": 4200.0,
                "targets": [4218.0, 4240.0, 4280.0],
            },
            {
                "zone_id": "MINOR_REACTION",
                "direction": "LONG",
                "timeframe": "M30",
                "low": 4138.0,
                "high": 4145.0,
                "role": "MINOR_REACTION",
                "condition": "ACTIVE",
                "strength": 0.5,
                "structural_invalidation": 4135.0,
                "targets": [4160.0],
            },
        ],
        "liquidity_candidates": [
            {"side": "SELL_SIDE", "price": 4132.0},
            {"side": "SELL_SIDE", "price": 4127.0},
        ],
    }


def _shift_context(context: dict, offset: float) -> dict:
    shifted = deepcopy(context)
    shifted["price_now"] += offset
    for zone in shifted["effective_zones"]:
        for key in ("low", "high", "structural_invalidation", "validation_level"):
            if zone.get(key) is not None:
                zone[key] += offset
        zone["targets"] = [value + offset for value in zone.get("targets", [])]
    for row in shifted.get("liquidity_candidates", []):
        row["price"] += offset
    if shifted.get("acceptance_closes"):
        shifted["acceptance_closes"] = [value + offset for value in shifted["acceptance_closes"]]
    return shifted


def test_v395_oct5_pattern_allows_early_take_risk_before_reclaim() -> None:
    result = evaluate_afiq_challenger_v395(_oct5_like_context())
    assert result["state"] == "EARLY_TAKE_RISK"
    assert result["direction"] == "LONG"
    assert result["effective_zone"]["zone_id"] == "H4_DEMAND_EFFECTIVE"
    assert result["reclaim_confirmed"] is False
    assert result["effective_score"] >= result["min_effective_score"]
    assert result["rr_first_target"] >= result["min_rr"]
    assert result["paths"]["primary"]["validation_level"] == 4200.0


def test_v395_reclaim_is_confidence_upgrade_not_required_initial_trigger() -> None:
    context = _oct5_like_context(price=4204.0)
    context["acceptance_closes"] = [4196.0, 4203.0]
    result = evaluate_afiq_challenger_v395(context)
    assert result["state"] == "CONFIRMED"
    assert result["direction"] == "LONG"
    assert result["reclaim_confirmed"] is True


def test_v395_wick_beyond_floor_does_not_invalidate_without_acceptance() -> None:
    context = _oct5_like_context(price=4132.0)
    context["session_low"] = 4106.0
    context["acceptance_closes"] = [4113.0, 4115.0]
    result = evaluate_afiq_challenger_v395(context)
    assert result["structurally_invalidated"] is False
    assert result["state"] == "EARLY_TAKE_RISK"


def test_v395_two_closes_beyond_structural_floor_invalidates() -> None:
    context = _oct5_like_context(price=4108.0)
    context["acceptance_closes"] = [4109.5, 4108.0]
    result = evaluate_afiq_challenger_v395(context)
    assert result["state"] == "INVALIDATED"
    assert result["structurally_invalidated"] is True
    assert result["paths"]["invalidation"]["level"] == 4110.0


def test_v395_high_impact_news_veto_overrides_early_entry() -> None:
    context = _oct5_like_context()
    event = {"impact": "HIGH", "minutes_to_event": 25}
    result = evaluate_afiq_challenger_v395(context, event_risk=event)
    assert result["state"] == "BLOCKED_EVENT"
    assert result["event"]["blocked"] is True


def test_v395_selects_effective_main_zone_over_minor_reaction_zone() -> None:
    result = evaluate_afiq_challenger_v395(_oct5_like_context())
    assert result["effective_zone"]["zone_id"] == "H4_DEMAND_EFFECTIVE"
    ids = [row["zone_id"] for row in result["candidates"]]
    assert "MINOR_REACTION" in ids


def test_v395_is_price_translation_invariant_not_hardcoded_to_afiq_levels() -> None:
    original = _oct5_like_context()
    shifted = _shift_context(original, 1000.0)
    a = evaluate_afiq_challenger_v395(original)
    b = evaluate_afiq_challenger_v395(shifted)
    assert a["state"] == b["state"] == "EARLY_TAKE_RISK"
    assert a["direction"] == b["direction"] == "LONG"
    assert a["effective_score"] == b["effective_score"]
    assert a["rr_first_target"] == b["rr_first_target"]


def test_v395_short_side_is_symmetric() -> None:
    context = {
        "price_now": 4208.0,
        "effective_zones": [
            {
                "zone_id": "H1_SUPPLY_EFFECTIVE",
                "direction": "SHORT",
                "timeframe": "H1",
                "low": 4200.0,
                "high": 4212.0,
                "role": "MAIN_REVERSAL_SUPPLY",
                "condition": "ACTIVE",
                "strength": 2.0,
                "structural_invalidation": 4214.0,
                "validation_level": 4184.0,
                "targets": [4160.0, 4132.0],
            }
        ],
        "liquidity_candidates": [{"side": "BUY_SIDE", "price": 4210.0}],
    }
    result = evaluate_afiq_challenger_v395(context)
    assert result["state"] == "EARLY_TAKE_RISK"
    assert result["direction"] == "SHORT"
    assert result["rr_first_target"] >= 1.5


def test_v395_has_no_execution_authority_and_reference_is_calibration_only() -> None:
    result = evaluate_afiq_challenger_v395(_oct5_like_context())
    assert result["execution_authority"] is False
    assert result["demo_auto_execution"] is False
    assert result["live_execution_enabled"] is False
    assert result["live_execution_influence"] is False
    assert result["provenance_guard"]["afiq_prices_used_as_runtime_inputs"] is False
    assert result["provenance_guard"]["reference_data_role"] == "CALIBRATION_AND_REGRESSION_ONLY"
