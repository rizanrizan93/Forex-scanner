from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fx_scanner.demo_trade_plan_geometry import build_demo_trade_plan
from fx_scanner.demo_technical_strategy import _demo_calibration_pretrigger_enabled
from fx_scanner.liquidity import FairValueGap


UTC = timezone.utc
NOW = datetime(2026, 9, 3, tzinfo=UTC)


class FakeLiquidity:
    def __init__(self, fvgs, *, above=(), below=()):
        self.fvgs = list(fvgs)
        self.observed_at = NOW
        self._above = [SimpleNamespace(price=float(x)) for x in above]
        self._below = [SimpleNamespace(price=float(x)) for x in below]

    def levels_above(self, price):
        return [item for item in self._above if item.price > float(price)]

    def levels_below(self, price):
        return [item for item in self._below if item.price < float(price)]


def _gap(direction, lower, upper, status="PARTIAL"):
    return FairValueGap(direction, lower, upper, NOW, status, 0.0)


def _bar(high, low):
    return SimpleNamespace(high=float(high), low=float(low))


def _snap(*, trend, low=None, high=None, bos=None, mss=None, displacement=None, sweep=None):
    return SimpleNamespace(
        trend=trend,
        last_swing_low=low,
        last_swing_high=high,
        bos=bos,
        mss=mss,
        displacement=displacement,
        sweep=sweep,
        fvg=None,
    )


def test_wave_ready_long_plan_keeps_raw_structural_zone(monkeypatch):
    import fx_scanner.demo_trade_plan_geometry as geometry

    monkeypatch.setattr(geometry, "atr", lambda _bars, _period: 1.0)
    liquidity = FakeLiquidity(
        [_gap("BULLISH", 99.8, 100.1)],
        above=(102.0,),
    )
    plan = build_demo_trade_plan(
        direction="LONG",
        current_price=100.2,
        m15=_snap(trend="BULLISH", low=99.5),
        h1=_snap(trend="BULLISH", low=99.0),
        m5=_snap(trend="RANGE", low=99.8, bos="BULLISH"),
        liquidity=liquidity,
        m5_bars=[_bar(99.9, 99.5), _bar(100.5, 99.9), _bar(100.4, 100.0), _bar(100.3, 100.1)],
        atr_period=14,
        sl_buffer_atr=0.15,
        minimum_entry_zone_atr=0.05,
        chase_block_atr=0.50,
    )

    assert plan is not None
    assert plan.entry_low == 99.8
    assert plan.entry_high == 100.1
    assert 0.0 < plan.chase_distance_atr <= 0.50
    assert plan.tp1 == 102.0
    assert plan.tp2 is not None
    assert plan.rr2 is not None
    assert plan.rr2 >= 2.0


def test_mid_wave_long_plan_is_blocked_even_inside_broad_chase_lane(monkeypatch):
    import fx_scanner.demo_trade_plan_geometry as geometry

    monkeypatch.setattr(geometry, "atr", lambda _bars, _period: 1.0)
    liquidity = FakeLiquidity(
        [_gap("BULLISH", 99.8, 100.1)],
        above=(102.0, 103.0),
    )
    plan = build_demo_trade_plan(
        direction="LONG",
        current_price=100.8,
        m15=_snap(trend="BULLISH", low=99.5),
        h1=_snap(trend="BULLISH", low=99.0),
        m5=_snap(trend="RANGE", low=99.8, bos="BULLISH"),
        liquidity=liquidity,
        m5_bars=[_bar(100.0, 99.6), _bar(101.2, 100.2), _bar(101.1, 100.6), _bar(100.9, 100.7)],
        atr_period=14,
        sl_buffer_atr=0.15,
        minimum_entry_zone_atr=0.05,
        chase_block_atr=2.0,
    )

    assert plan is None


def test_calibration_pretrigger_is_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("CTRADER_DEMO_CALIBRATION_ALLOW_PRETRIGGER", raising=False)
    assert _demo_calibration_pretrigger_enabled() is False
    monkeypatch.setenv("CTRADER_DEMO_CALIBRATION_ALLOW_PRETRIGGER", "1")
    assert _demo_calibration_pretrigger_enabled() is True


def test_demo_pipeline_uses_score_driven_floor_above_50():
    text = Path(".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    assert 'CTRADER_DEMO_EXECUTION_CANDIDATE_MIN: "50.01"' in text
    assert 'CTRADER_DEMO_CALIBRATION_ALLOW_PRETRIGGER: "1"' in text
    assert 'CTRADER_DEMO_WAVE_MIN_PULLBACK_ATR: "0.25"' in text
    assert 'CTRADER_DEMO_WAVE_MAX_ZONE_ATR: "0.50"' in text
