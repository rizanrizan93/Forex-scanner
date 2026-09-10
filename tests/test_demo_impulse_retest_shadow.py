from types import SimpleNamespace

from fx_scanner.demo_strategy_lab import StrategyFamily, build_strategy_lab_hypotheses


def _feature(direction="BULLISH", valid=True):
    return SimpleNamespace(direction=direction, valid=valid)


def _snapshot(*, trend="BULLISH", bos=None, displacement=None, fvg=None, sweep=None):
    return SimpleNamespace(
        trend=trend,
        bos=bos,
        mss=None,
        displacement=displacement,
        fvg=fvg,
        sweep=sweep,
    )


def _ema_row(*, aligned=True, opposite=False, spread="EXPANDING"):
    return {
        "available": True,
        "directional_aligned": aligned,
        "opposite_aligned": opposite,
        "directional_slopes": aligned,
        "spread_state": spread,
        "pullback_near_fast_cluster": False,
    }


def _candidate(*, regime="TRANSITION", impulse=True, h1="BULLISH", m15="BULLISH", m5="BULLISH"):
    bullish = _feature()
    analysis = SimpleNamespace(
        direction="LONG",
        h1=_snapshot(trend=h1, bos=None),
        m15=_snapshot(
            trend=m15,
            bos="BULLISH",
            displacement=bullish if impulse else None,
            fvg=bullish,
        ),
        m5=_snapshot(
            trend=m5,
            bos="BULLISH",
            displacement=bullish if impulse else None,
            fvg=bullish,
        ),
    )
    rows = {
        row.family: row
        for row in build_strategy_lab_hypotheses(
            analysis=analysis,
            regime=regime,
            session="LONDON",
            geometry_payload={
                "entry_mode": "HL_PULLBACK",
                "confirmation": "M5_STRUCTURE_BREAK",
                "pullback_atr": 0.55,
            },
            ema_evidence={
                "profile": "SCALP_9_20_34_50",
                "periods": [9, 20, 34, 50],
                "brochure_periods_confirmed": False,
                "available_timeframes": 3,
                "mature_timeframes": 0,
                "directional_confluence": 3,
                "h1": _ema_row(),
                "m15": _ema_row(),
                "m5": _ema_row(),
            },
        )
    }
    return rows[StrategyFamily.IMPULSE_RETEST]


def test_impulse_retest_activates_only_as_observation_hypothesis():
    candidate = _candidate()

    assert candidate.active is True
    assert candidate.score >= 60.0
    assert candidate.policy_effect == "OBSERVATION_ONLY"
    assert candidate.evidence["impulse_present"] is True
    assert candidate.evidence["controlled_retest"] is True
    assert candidate.evidence["design_basis"] == "IMPULSE_ACCEPTANCE_THEN_FIRST_CONTROLLED_RETEST"


def test_bare_structure_break_without_impulse_is_penalized():
    candidate = _candidate(impulse=False)

    assert candidate.evidence["directional_structure"] is True
    assert candidate.evidence["impulse_present"] is False
    assert candidate.active is False
    assert candidate.score < 60.0


def test_range_regime_is_penalized_even_with_directional_context():
    transition = _candidate(regime="TRANSITION")
    ranging = _candidate(regime="RANGE")

    assert ranging.score < transition.score
    assert ranging.evidence["regime"] == "RANGE"
