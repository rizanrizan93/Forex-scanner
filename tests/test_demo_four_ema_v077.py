from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fx_scanner.demo_four_ema import (
    FOUR_EMA_PERIODS,
    FOUR_EMA_PROFILE,
    build_four_ema_bundle,
    build_four_ema_features,
)
from fx_scanner.demo_strategy_lab import StrategyFamily, build_strategy_lab_hypotheses
from fx_scanner.models import Bar

UTC = timezone.utc


def _bars(*, direction: str, timeframe: str = "M5", count: int = 80):
    seconds = {"H1": 3600, "M15": 900, "M5": 300}[timeframe]
    start = datetime(2026, 9, 1, tzinfo=UTC)
    rows = []
    sign = 1.0 if direction == "UP" else -1.0
    for index in range(count):
        center = 1.1000 + sign * 0.00035 * index
        close = center + sign * 0.00010
        low = min(center, close) - 0.00035
        high = max(center, close) + 0.00035
        rows.append(
            Bar(
                symbol="EURUSD",
                timeframe=timeframe,
                timestamp=start + timedelta(seconds=seconds * index),
                open=center,
                high=high,
                low=low,
                close=close,
                tick_count=100 + index,
                spread_avg=0.0001,
                spread_max=0.0002,
            )
        )
    return tuple(rows)


def _feature(direction="BULLISH", valid=True):
    return SimpleNamespace(direction=direction, valid=valid)


def _snapshot(*, trend="BULLISH", bos=None, displacement=None):
    return SimpleNamespace(
        trend=trend,
        bos=bos,
        mss=None,
        displacement=displacement,
        fvg=None,
        sweep=None,
    )


def test_four_ema_shadow_detects_directional_alignment_without_execution_policy():
    bullish = build_four_ema_features(_bars(direction="UP"), direction="LONG")
    bearish = build_four_ema_features(_bars(direction="DOWN"), direction="SHORT")

    assert bullish.available is True
    assert bullish.alignment == "BULLISH"
    assert bullish.directional_aligned is True
    assert bullish.directional_slopes is True
    assert bullish.price_side_slow_ok is True
    assert bullish.separation_atr is not None and bullish.separation_atr > 0
    assert bullish.policy_effect == "OBSERVATION_ONLY"

    assert bearish.available is True
    assert bearish.alignment == "BEARISH"
    assert bearish.directional_aligned is True
    assert bearish.directional_slopes is True
    assert bearish.price_side_slow_ok is True
    assert bearish.policy_effect == "OBSERVATION_ONLY"


def test_four_ema_shadow_fails_open_for_research_when_history_is_short():
    features = build_four_ema_features(
        _bars(direction="UP", count=20),
        direction="LONG",
    )

    assert features.available is False
    assert features.alignment == "UNAVAILABLE"
    assert features.directional_aligned is False
    assert features.policy_effect == "OBSERVATION_ONLY"


def test_four_ema_bundle_is_explicitly_unconfirmed_brochure_reconstruction():
    bundle = build_four_ema_bundle(
        {
            "H1": _bars(direction="UP", timeframe="H1", count=55),
            "M15": _bars(direction="UP", timeframe="M15", count=65),
            "M5": _bars(direction="UP", timeframe="M5", count=75),
        },
        direction="LONG",
    )

    assert bundle["profile"] == FOUR_EMA_PROFILE
    assert bundle["periods"] == list(FOUR_EMA_PERIODS)
    assert bundle["brochure_periods_confirmed"] is False
    assert bundle["policy_effect"] == "OBSERVATION_ONLY"
    assert bundle["available_timeframes"] == 3
    assert bundle["directional_confluence"] == 3


def test_four_ema_strategy_family_can_activate_only_as_shadow_hypothesis():
    bullish = _feature()
    analysis = SimpleNamespace(
        direction="LONG",
        h1=_snapshot(trend="BULLISH", bos="BULLISH"),
        m15=_snapshot(trend="BULLISH", bos="BULLISH", displacement=bullish),
        m5=_snapshot(trend="BULLISH", bos="BULLISH", displacement=bullish),
    )
    ema_evidence = build_four_ema_bundle(
        {
            "H1": _bars(direction="UP", timeframe="H1", count=55),
            "M15": _bars(direction="UP", timeframe="M15", count=65),
            "M5": _bars(direction="UP", timeframe="M5", count=75),
        },
        direction="LONG",
    )
    rows = {
        row.family: row
        for row in build_strategy_lab_hypotheses(
            analysis=analysis,
            regime="TREND_STRONG",
            session="LONDON",
            geometry_payload={"entry_mode": "HL_PULLBACK", "confirmation": "M5_STRUCTURE_BREAK"},
            ema_evidence=ema_evidence,
        )
    }

    candidate = rows[StrategyFamily.FOUR_EMA_PULLBACK]
    assert candidate.active is True
    assert candidate.score >= 60.0
    assert candidate.evidence["profile"] == FOUR_EMA_PROFILE
    assert candidate.evidence["brochure_periods_confirmed"] is False
    assert candidate.policy_effect == "OBSERVATION_ONLY"
