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


def test_chase_valid_long_plan_extends_executable_zone_to_market(monkeypatch):
    import fx_scanner.demo_trade_plan_geometry as geometry

    monkeypatch.setattr(geometry, "atr", lambda _bars, _period: 1.0)
    liquidity = FakeLiquidity(
        [_gap("BULLISH", 99.8, 100.1)],
        above=(102.0,),
    )
    plan = build_demo_trade_plan(
        direction="LONG",
        current_price=100.4,
        m15=SimpleNamespace(sweep=None),
        h1=SimpleNamespace(last_swing_low=99.0, last_swing_high=None),
        m5=SimpleNamespace(fvg=None),
        liquidity=liquidity,
        m5_bars=[object()],
        atr_period=14,
        sl_buffer_atr=0.15,
        minimum_entry_zone_atr=0.05,
        chase_block_atr=0.50,
    )

    assert plan is not None
    assert plan.entry_low == 99.8
    assert plan.entry_high == 100.4
    assert plan.chase_distance_atr == 0.0
    assert plan.tp1 == 102.0
    assert plan.tp2 is not None
    assert plan.rr2 is not None
    assert plan.rr2 >= 2.0


def test_over_chased_long_plan_remains_blockable(monkeypatch):
    import fx_scanner.demo_trade_plan_geometry as geometry

    monkeypatch.setattr(geometry, "atr", lambda _bars, _period: 1.0)
    liquidity = FakeLiquidity(
        [_gap("BULLISH", 99.8, 100.1)],
        above=(102.0, 103.0),
    )
    plan = build_demo_trade_plan(
        direction="LONG",
        current_price=100.8,
        m15=SimpleNamespace(sweep=None),
        h1=SimpleNamespace(last_swing_low=99.0, last_swing_high=None),
        m5=SimpleNamespace(fvg=None),
        liquidity=liquidity,
        m5_bars=[object()],
        atr_period=14,
        sl_buffer_atr=0.15,
        minimum_entry_zone_atr=0.05,
        chase_block_atr=0.50,
    )

    assert plan is not None
    assert plan.entry_high == 100.1
    assert plan.chase_distance_atr > 0.50


def test_calibration_pretrigger_is_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("CTRADER_DEMO_CALIBRATION_ALLOW_PRETRIGGER", raising=False)
    assert _demo_calibration_pretrigger_enabled() is False
    monkeypatch.setenv("CTRADER_DEMO_CALIBRATION_ALLOW_PRETRIGGER", "1")
    assert _demo_calibration_pretrigger_enabled() is True


def test_demo_pipeline_uses_minimum_supported_calibration_threshold():
    text = Path(".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    assert 'CTRADER_DEMO_EXECUTION_CANDIDATE_MIN: "50"' in text
    assert 'CTRADER_DEMO_CALIBRATION_ALLOW_PRETRIGGER: "1"' in text
