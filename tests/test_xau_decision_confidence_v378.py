from datetime import UTC, datetime, timedelta

from fx_scanner.xau_decision_confidence_v378 import build_decision_confidence
from fx_scanner.xau_intraday_yield_v367 import evaluate_intraday_yield_pressure
from fx_scanner.xau_yield_regime_view_v372 import classify_intraday_us10y


def test_v378_continuous_intraday_yield_up_is_gold_headwind():
    now = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    points = [
        {"observed_at": now - timedelta(minutes=90), "yield_pct": 4.00},
        {"observed_at": now - timedelta(minutes=30), "yield_pct": 4.02},
        {"observed_at": now - timedelta(minutes=2), "yield_pct": 4.04},
    ]
    out = evaluate_intraday_yield_pressure(points, now=now, window_minutes=120)
    assert out["available"] is True
    assert out["state"] == "INTRADAY_YIELD_UP"
    assert out["gold_implication"] == "GOLD_HEADWIND"
    assert round(out["net_bps"], 3) == 4.0


def test_v378_stale_intraday_keeps_last_numeric_value_visible():
    now = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    points = [{"observed_at": now - timedelta(hours=2), "yield_pct": 4.11}]
    out = evaluate_intraday_yield_pressure(points, now=now, max_age_seconds=900)
    assert out["available"] is False
    assert out["state"] == "INTRADAY_YIELD_STALE"
    assert out["current"] == 4.11
    assert out["age_seconds"] > 900


def test_v378_yield_view_understands_continuous_intraday_state():
    macro = {
        "intraday_yield_context": {
            "available": True,
            "state": "INTRADAY_YIELD_DOWN",
            "current": 4.12,
            "reference": 4.16,
            "net_bps": -4.0,
            "gold_implication": "GOLD_SUPPORT",
            "source": "YAHOO_FINANCE_TNX_INTRADAY_PROXY",
        }
    }
    out = classify_intraday_us10y(macro)
    assert out["gold_bias"] == "BULLISH_XAU"
    assert out["net_bps"] == -4.0


def test_v378_decision_confidence_rewards_aligned_structure_behavior_micro_and_yield():
    sd = {
        "main_reversal_zone": {"condition": "ACTIVE", "direction": "LONG"},
        "market_structure": {
            "H4": {"state": "BULLISH_BREAK"},
            "H1": {"state": "BULLISH"},
        },
    }
    behavior = {
        "active_zone_role": {"role": "MAIN_REVERSAL"},
        "acceptance_rejection": {"state": "REJECTION_CONFIRMED"},
        "m30_aligned": True,
        "m30_conflict": False,
        "response_timer": {"state": "FOLLOW_THROUGH_CONFIRMED"},
        "demo_entry_gate": "ALLOW_WITH_EXISTING_GATES",
    }
    micro = {"confirmed": True, "stage": "CONFIRMED"}
    macro = {
        "broader_bias": "BULLISH_XAU",
        "yield": {
            "daily": {"gold_bias": "BULLISH_XAU"},
            "intraday": {"gold_bias": "BULLISH_XAU"},
            "alignment": "ALIGNED",
        },
    }
    event = {
        "data_confidence": "HIGH",
        "direction_confidence": "MEDIUM",
        "numeric_coverage": "POST_RELEASE_READY",
        "gold_bias": "BULLISH_XAU",
    }
    out = build_decision_confidence(
        direction="LONG",
        sd=sd,
        behavior=behavior,
        micro=micro,
        reaction={},
        macro_summary=macro,
        latest_event=event,
    )
    assert out["evidence_score"] >= 80
    assert out["confidence_band"] == "HIGH"
    assert out["coverage_pct"] == 100


def test_v378_schedule_only_event_does_not_fake_directional_confidence():
    out = build_decision_confidence(
        direction="LONG",
        sd={
            "main_reversal_zone": {"condition": "ACTIVE", "direction": "LONG"},
            "market_structure": {},
        },
        behavior={},
        micro={},
        reaction={},
        macro_summary={},
        latest_event={
            "data_confidence": "LOW",
            "direction_confidence": "UNAVAILABLE",
            "numeric_coverage": "SCHEDULE_ONLY",
            "gold_bias": "NEUTRAL_UNKNOWN",
        },
    )
    event_component = next(row for row in out["components"] if row["name"] == "EVENT")
    assert event_component["available"] is False
    assert event_component["contribution"] == 0
    assert "EVENT" in out["missing_evidence"]


def test_v378_behavioral_failure_caps_confidence_component():
    out = build_decision_confidence(
        direction="SHORT",
        sd={
            "main_reversal_zone": {"condition": "ACTIVE", "direction": "SHORT"},
            "market_structure": {
                "H4": {"state": "BEARISH"},
                "H1": {"state": "BEARISH"},
            },
        },
        behavior={
            "active_zone_role": {"role": "MAIN_REVERSAL"},
            "acceptance_rejection": {"state": "ACCEPTANCE_AGAINST_THESIS"},
            "m30_aligned": False,
            "m30_conflict": True,
            "response_timer": {"state": "REACTION_FAILED"},
            "demo_entry_gate": "BLOCK_BEHAVIORAL_FAILURE",
        },
        micro={"confirmed": True},
        reaction={},
        macro_summary={},
        latest_event={},
    )
    behavior_component = next(row for row in out["components"] if row["name"] == "BEHAVIORAL_CONTEXT")
    assert behavior_component["score"] <= 10
    assert out["confidence_band"] != "HIGH"
