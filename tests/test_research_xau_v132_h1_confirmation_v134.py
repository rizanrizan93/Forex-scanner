from fx_scanner.research_xau_v132_h1_confirmation_v134 import (
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    _h1_permission,
)


def _row():
    return {
        "close": 210.0,
        "ema20": 205.0,
        "ema50": 200.0,
        "ema200": 190.0,
        "ema20_slope5": 2.0,
        "adx14": 16.0,
        "plus_di14": 25.0,
        "minus_di14": 15.0,
    }


def test_v134_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v134_reuses_frozen_v35_h1_semantics():
    row = _row()
    assert _h1_permission(row, side="LONG", mode="SOFT") is True
    assert _h1_permission(row, side="LONG", mode="NORMAL") is True
    assert _h1_permission(row, side="LONG", mode="STRICT") is True

    assert _h1_permission({**row, "close": 185.0}, side="LONG", mode="SOFT") is False
    assert _h1_permission({**row, "ema20": 195.0}, side="LONG", mode="NORMAL") is False
    assert _h1_permission({**row, "adx14": 14.99}, side="LONG", mode="STRICT") is False
    assert _h1_permission({**row, "plus_di14": 10.0}, side="LONG", mode="STRICT") is False


def test_v134_baseline_has_no_h1_filter():
    assert _h1_permission(None, side="LONG", mode="BASELINE") is True
