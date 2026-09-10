from fx_scanner.demo_xau_expansion_challenger import RULE_VERSION, classify_snapshot


def _snapshot():
    return {
        "symbol": "XAUUSD",
        "direction": "LONG",
        "regime": "TRANSITION",
        "session": "LONDON_NY_OVERLAP",
        "entry_mode": "HL_PULLBACK",
        "pullback_atr": 0.55,
        "structure_m5": {
            "bos": "BULLISH",
            "mss": None,
            "displacement_valid": True,
            "displacement_direction": "BULLISH",
            "displacement_range_atr_ratio": 1.60,
            "displacement_body_ratio": 1.05,
        },
        "structure_m15": {
            "bos": "BULLISH",
            "mss": None,
            "displacement_valid": False,
            "displacement_direction": "BULLISH",
            "displacement_range_atr_ratio": 0.70,
            "displacement_body_ratio": 0.40,
        },
        "ema4_m5": {
            "directional_aligned": True,
            "spread_state": "EXPANDING",
        },
        "ema4_m15": {
            "directional_aligned": True,
            "spread_state": "STABLE",
        },
    }


def test_strong_impulse_retest_with_expansion_is_active_shadow_only():
    decision = classify_snapshot(_snapshot())
    assert decision.active is True
    assert decision.score >= 80
    assert decision.evidence["rule_version"] == RULE_VERSION
    assert decision.evidence["policy_effect"] == "OBSERVATION_ONLY"
    assert decision.evidence["execution_influence"] is False
    assert decision.evidence["quality_impulse"] is True
    assert decision.evidence["expansion_confirmed"] is True


def test_bare_structure_break_without_directional_impulse_is_inactive():
    payload = _snapshot()
    payload["structure_m5"] = dict(payload["structure_m5"], displacement_valid=False)
    decision = classify_snapshot(payload)
    assert decision.active is False
    assert decision.evidence["impulse_present"] is False
    assert decision.evidence["base_required"] is False


def test_retest_outside_preregistered_atr_band_is_inactive():
    payload = _snapshot()
    payload["pullback_atr"] = 1.40
    decision = classify_snapshot(payload)
    assert decision.active is False
    assert decision.evidence["controlled_retest"] is False


def test_expansion_confirmation_can_come_from_dual_timeframe_impulse_without_ema():
    payload = _snapshot()
    payload["ema4_m5"] = {"directional_aligned": False, "spread_state": "COMPRESSING"}
    payload["ema4_m15"] = {"directional_aligned": False, "spread_state": "COMPRESSING"}
    payload["structure_m15"] = {
        "bos": "BULLISH",
        "mss": None,
        "displacement_valid": True,
        "displacement_direction": "BULLISH",
        "displacement_range_atr_ratio": 1.30,
        "displacement_body_ratio": 0.90,
    }
    decision = classify_snapshot(payload)
    assert decision.active is True
    assert decision.evidence["ema_release"] is False
    assert decision.evidence["dual_tf_impulse"] is True


def test_session_and_regime_are_context_not_hard_filters():
    payload = _snapshot()
    payload["session"] = "OFF_SESSION"
    payload["regime"] = "RANGE"
    decision = classify_snapshot(payload)
    assert decision.active is True
    assert decision.evidence["liquid_session"] is False
    assert decision.evidence["regime"] == "RANGE"
