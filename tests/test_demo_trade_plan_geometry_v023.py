from datetime import datetime, timezone
from types import SimpleNamespace

from fx_scanner.demo_trade_plan_geometry import (
    _nearest_directional_gap,
    build_demo_trade_plan,
)
from fx_scanner.liquidity import FairValueGap


UTC = timezone.utc
NOW = datetime(2026, 9, 3, tzinfo=UTC)


class FakeLiquidity:
    def __init__(self, fvgs, *, above=(), below=()):
        self.fvgs = list(fvgs)
        self.observed_at = NOW
        self._above = [SimpleNamespace(price=float(x)) for x in above]
        self._below = [SimpleNamespace(price=float(x)) for x in below]

    def levels_above(self, _price):
        return list(self._above)

    def levels_below(self, _price):
        return list(self._below)


def _gap(direction, lower, upper, status="OPEN"):
    return FairValueGap(direction, lower, upper, NOW, status, 0.0)


def _bar(high, low):
    return SimpleNamespace(high=float(high), low=float(low))


def _snap(*, trend, low=None, high=None, bos=None, mss=None, displacement=None, sweep=None, fvg=None):
    return SimpleNamespace(
        trend=trend,
        last_swing_low=low,
        last_swing_high=high,
        bos=bos,
        mss=mss,
        displacement=displacement,
        sweep=sweep,
        fvg=fvg,
    )


def test_nearest_directional_gap_prefers_current_price_geometry():
    liquidity = FakeLiquidity(
        [
            _gap("BULLISH", 97.0, 98.0),
            _gap("BULLISH", 99.8, 100.1, "PARTIAL"),
        ]
    )
    m5 = SimpleNamespace(fvg=None)

    selected = _nearest_directional_gap("LONG", m5, liquidity, 100.2)

    assert selected is not None
    assert selected.lower == 99.8
    assert selected.upper == 100.1


def test_demo_plan_synthesizes_tp2_only_after_structural_tp1(monkeypatch):
    import fx_scanner.demo_trade_plan_geometry as geometry

    monkeypatch.setattr(geometry, "atr", lambda _bars, _period: 1.0)
    liquidity = FakeLiquidity(
        [
            _gap("BULLISH", 97.0, 98.0),
            _gap("BULLISH", 99.8, 100.1, "PARTIAL"),
        ],
        above=(102.0,),
    )
    m15 = _snap(trend="BULLISH", low=99.5)
    h1 = _snap(trend="BULLISH", low=99.0)
    m5 = _snap(trend="RANGE", low=99.8, bos="BULLISH")

    plan = build_demo_trade_plan(
        direction="LONG",
        current_price=100.2,
        m15=m15,
        h1=h1,
        m5=m5,
        liquidity=liquidity,
        m5_bars=[_bar(99.9, 99.5), _bar(100.5, 99.9), _bar(100.4, 100.0), _bar(100.3, 100.1)],
        atr_period=14,
        sl_buffer_atr=0.15,
        minimum_entry_zone_atr=0.05,
    )

    assert plan is not None
    assert plan.entry_low == 99.8
    assert plan.entry_high == 100.1
    assert plan.chase_distance_atr > 0.0
    assert plan.tp1 == 102.0
    assert plan.tp2 is not None
    assert plan.tp2 > plan.tp1
    assert plan.rr2 is not None
    assert plan.rr2 >= 2.0


def test_demo_plan_stays_fail_closed_without_any_structural_target(monkeypatch):
    import fx_scanner.demo_trade_plan_geometry as geometry

    monkeypatch.setattr(geometry, "atr", lambda _bars, _period: 1.0)
    liquidity = FakeLiquidity(
        [_gap("BEARISH", 99.9, 100.2, "PARTIAL")],
        below=(),
    )
    m15 = _snap(trend="BEARISH", high=100.5)
    h1 = _snap(trend="BEARISH", high=101.0)
    m5 = _snap(trend="RANGE", high=100.2, bos="BEARISH")

    plan = build_demo_trade_plan(
        direction="SHORT",
        current_price=99.8,
        m15=m15,
        h1=h1,
        m5=m5,
        liquidity=liquidity,
        m5_bars=[_bar(100.4, 100.0), _bar(100.0, 99.4), _bar(100.1, 99.5), _bar(99.9, 99.6)],
        atr_period=14,
        sl_buffer_atr=0.15,
        minimum_entry_zone_atr=0.05,
    )

    assert plan is None
