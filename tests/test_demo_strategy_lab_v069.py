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


def _analysis(*, h1, m15, m5, direction="LONG"):
    return SimpleNamespace(direction=direction, h1=h1, m15=m15, m5=m5)


def _by_family(rows):
    return {row.family: row for row in rows}


def test_trend_momentum_and_session_breakout_activate_in_aligned_liquid_session():
    bullish = _feature()
    analysis = _analysis(
        h1=_snapshot(trend="BULLISH", bos="BULLISH"),
        m15=_snapshot(trend="BULLISH", bos="BULLISH", displacement=bullish),
        m5=_snapshot(trend="BULLISH", bos="BULLISH", displacement=bullish),
    )
    rows = _by_family(build_strategy_lab_hypotheses(
        analysis=analysis,
        regime="TREND_STRONG",
        session="LONDON",
        geometry_payload={"entry_mode": "MARKET", "confirmation": "M5_STRUCTURE_BREAK"},
    ))

    assert rows[StrategyFamily.TREND_MOMENTUM].active is True
    assert rows[StrategyFamily.TREND_MOMENTUM].score >= 80
    assert rows[StrategyFamily.SESSION_BREAKOUT].active is True
    assert rows[StrategyFamily.SESSION_BREAKOUT].score >= 75
    assert all(row.policy_effect == "OBSERVATION_ONLY" for row in rows.values())


def test_pullback_arm_uses_geometry_without_becoming_execution_policy():
    bullish = _feature()
    analysis = _analysis(
        h1=_snapshot(trend="BULLISH"),
        m15=_snapshot(trend="BULLISH", fvg=bullish),
        m5=_snapshot(trend="BULLISH", fvg=bullish),
    )
    rows = _by_family(build_strategy_lab_hypotheses(
        analysis=analysis,
        regime="TREND_WEAK",
        session="ASIA",
        geometry_payload={
            "entry_mode": "HL_PULLBACK",
            "confirmation": "PULLBACK_RECLAIM",
            "pullback_atr": 0.40,
        },
    ))

    pullback = rows[StrategyFamily.PULLBACK_TREND]
    assert pullback.active is True
    assert pullback.evidence["pullback_atr"] == 0.40
    assert pullback.policy_effect == "OBSERVATION_ONLY"


def test_mean_reversion_activates_only_from_range_exhaustion_context():
    bullish_sweep = _feature()
    analysis = _analysis(
        h1=_snapshot(trend="RANGE"),
        m15=_snapshot(trend="RANGE", sweep=bullish_sweep),
        m5=_snapshot(trend="RANGE", sweep=bullish_sweep),
    )
    rows = _by_family(build_strategy_lab_hypotheses(
        analysis=analysis,
        regime="RANGE",
        session="ASIA",
        geometry_payload={"confirmation": "SWEEP_RECLAIM"},
    ))

    mean_reversion = rows[StrategyFamily.MEAN_REVERSION]
    assert mean_reversion.active is True
    assert mean_reversion.evidence["range_regime"] is True
    assert rows[StrategyFamily.TREND_MOMENTUM].score < mean_reversion.score


def test_liquidity_sweep_remains_a_challenger_not_a_required_framework():
    bullish = _feature()
    analysis = _analysis(
        h1=_snapshot(trend="BEARISH"),
        m15=_snapshot(trend="RANGE", bos="BULLISH", displacement=bullish, sweep=bullish),
        m5=_snapshot(trend="BULLISH", bos="BULLISH", displacement=bullish, sweep=bullish),
    )
    rows = build_strategy_lab_hypotheses(
        analysis=analysis,
        regime="REVERSAL",
        session="NEW_YORK",
        geometry_payload={"confirmation": "MSS_RECLAIM"},
    )

    assert {row.family for row in rows} == set(StrategyFamily)
    assert rows[0].family == StrategyFamily.LIQUIDITY_SWEEP
    assert rows[0].active is True
