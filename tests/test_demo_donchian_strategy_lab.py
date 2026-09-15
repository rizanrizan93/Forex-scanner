from types import SimpleNamespace

from fx_scanner.demo_strategy_lab import StrategyFamily, build_strategy_lab_hypotheses


def _snapshot(*, trend="BULLISH", bos=None):
    return SimpleNamespace(
        trend=trend,
        bos=bos,
        mss=None,
        displacement=None,
        fvg=None,
        sweep=None,
    )


def _analysis(direction="LONG"):
    return SimpleNamespace(
        direction=direction,
        h1=_snapshot(trend="BULLISH", bos="BULLISH"),
        m15=_snapshot(trend="BULLISH", bos="BULLISH"),
        m5=_snapshot(trend="BULLISH", bos="BULLISH"),
    )


def _by_family(rows):
    return {row.family: row for row in rows}


def test_donchian_h1_activates_only_when_close_buffer_breakout_is_triggered():
    rows = _by_family(build_strategy_lab_hypotheses(
        analysis=_analysis(),
        regime="TREND_STRONG",
        session="LONDON",
        donchian_evidence={
            "profile": "DONCHIAN_20_ATR14_H1",
            "timeframe": "H1",
            "lookback": 20,
            "atr_period": 14,
            "breakout_buffer_atr": 0.10,
            "available": True,
            "mature": True,
            "breakout_triggered": True,
            "close_beyond_channel": True,
            "intrabar_beyond_channel": True,
            "breakout_distance_atr": 0.35,
            "channel_width_atr": 4.2,
        },
    ))

    hypothesis = rows[StrategyFamily.DONCHIAN_ATR_BREAKOUT_H1]
    assert hypothesis.active is True
    assert hypothesis.score >= 60.0
    assert hypothesis.evidence["breakout_triggered"] is True
    assert hypothesis.evidence["design_basis"] == "PRIOR_DONCHIAN_CHANNEL_CLOSE_BREAK_PLUS_ATR_BUFFER"
    assert hypothesis.policy_effect == "OBSERVATION_ONLY"


def test_donchian_h1_wick_only_does_not_activate():
    rows = _by_family(build_strategy_lab_hypotheses(
        analysis=_analysis(),
        regime="TREND_STRONG",
        session="LONDON",
        donchian_evidence={
            "profile": "DONCHIAN_20_ATR14_H1",
            "timeframe": "H1",
            "lookback": 20,
            "atr_period": 14,
            "breakout_buffer_atr": 0.10,
            "available": True,
            "mature": True,
            "breakout_triggered": False,
            "close_beyond_channel": False,
            "intrabar_beyond_channel": True,
            "breakout_distance_atr": -0.05,
            "channel_width_atr": 4.2,
        },
    ))

    hypothesis = rows[StrategyFamily.DONCHIAN_ATR_BREAKOUT_H1]
    assert hypothesis.active is False
    assert hypothesis.score < 60.0
    assert hypothesis.evidence["intrabar_beyond_channel"] is True
