from pathlib import Path
from types import SimpleNamespace

from fx_scanner.demo_trade_plan_geometry import assess_demo_wave_entry


def snap(*, trend="BULLISH", low=103.0, high=106.0, bos=None, mss=None, displacement=None, sweep=None):
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


def disp(direction):
    return SimpleNamespace(valid=True, direction=direction)


def sweep(direction):
    return SimpleNamespace(valid=True, direction=direction)


def bars(*pairs):
    return [SimpleNamespace(high=float(high), low=float(low)) for high, low in pairs]


def test_long_mid_wave_is_not_executable(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_WAVE_MIN_PULLBACK_ATR", "0.25")
    monkeypatch.setenv("CTRADER_DEMO_WAVE_MAX_ZONE_ATR", "0.50")
    monkeypatch.setenv("CTRADER_DEMO_MOMENTUM_MAX_ZONE_ATR", "0.20")
    result = assess_demo_wave_entry(
        direction="LONG",
        current_price=105.00,
        entry_low=104.80,
        entry_high=104.90,
        h1=snap(trend="BULLISH", low=103.0),
        m15=snap(trend="BULLISH", low=104.0),
        m5=snap(trend="BULLISH", low=104.5, displacement=disp("BULLISH")),
        m5_bars=bars((104.7, 104.2), (104.9, 104.4), (105.1, 104.8), (105.05, 104.9)),
        current_atr=1.0,
    )
    assert not result.ready
    assert result.mode == "WAIT"
    assert result.reason == "WAIT_HL_LH_PULLBACK"


def test_long_higher_low_pullback_with_m5_break_is_ready(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_WAVE_MIN_PULLBACK_ATR", "0.25")
    monkeypatch.setenv("CTRADER_DEMO_WAVE_MAX_ZONE_ATR", "0.50")
    monkeypatch.setenv("CTRADER_DEMO_MOMENTUM_MAX_ZONE_ATR", "0.20")
    result = assess_demo_wave_entry(
        direction="LONG",
        current_price=104.50,
        entry_low=104.20,
        entry_high=104.40,
        h1=snap(trend="BULLISH", low=102.5),
        m15=snap(trend="BULLISH", low=103.8),
        m5=snap(trend="RANGE", low=104.0, bos="BULLISH"),
        m5_bars=bars((104.2, 103.9), (104.7, 104.2), (105.0, 104.6), (104.8, 104.4)),
        current_atr=1.0,
    )
    assert result.ready
    assert result.mode == "HL_PULLBACK"
    assert result.confirmation == "M5_STRUCTURE_BREAK"
    assert result.pullback_atr >= 0.25
    assert result.zone_distance_atr <= 0.50


def test_short_lower_high_pullback_with_sweep_reclaim_is_ready(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_WAVE_MIN_PULLBACK_ATR", "0.25")
    monkeypatch.setenv("CTRADER_DEMO_WAVE_MAX_ZONE_ATR", "0.50")
    monkeypatch.setenv("CTRADER_DEMO_MOMENTUM_MAX_ZONE_ATR", "0.20")
    result = assess_demo_wave_entry(
        direction="SHORT",
        current_price=95.50,
        entry_low=95.60,
        entry_high=95.80,
        h1=snap(trend="BEARISH", high=98.0),
        m15=snap(trend="BEARISH", high=96.4),
        m5=snap(trend="RANGE", high=96.0, sweep=sweep("BEARISH")),
        m5_bars=bars((96.4, 95.8), (95.9, 95.2), (95.5, 95.0), (95.8, 95.4)),
        current_atr=1.0,
    )
    assert result.ready
    assert result.mode == "LH_PULLBACK"
    assert result.confirmation == "M5_SWEEP_RECLAIM"


def test_momentum_exception_requires_break_and_displacement_close_to_zone(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_WAVE_MIN_PULLBACK_ATR", "0.25")
    monkeypatch.setenv("CTRADER_DEMO_WAVE_MAX_ZONE_ATR", "0.50")
    monkeypatch.setenv("CTRADER_DEMO_MOMENTUM_MAX_ZONE_ATR", "0.20")
    result = assess_demo_wave_entry(
        direction="LONG",
        current_price=104.95,
        entry_low=104.75,
        entry_high=104.90,
        h1=snap(trend="BULLISH", low=103.0),
        m15=snap(trend="BULLISH", low=104.0),
        m5=snap(trend="BULLISH", low=104.5, bos="BULLISH", displacement=disp("BULLISH")),
        m5_bars=bars((104.7, 104.2), (104.85, 104.4), (105.0, 104.7), (104.98, 104.8)),
        current_atr=1.0,
    )
    assert result.ready
    assert result.mode == "MOMENTUM_CONTINUATION"
    assert result.zone_distance_atr <= 0.20


def test_confirmed_wave_still_waits_if_price_is_too_far_from_entry_zone(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_WAVE_MIN_PULLBACK_ATR", "0.25")
    monkeypatch.setenv("CTRADER_DEMO_WAVE_MAX_ZONE_ATR", "0.50")
    monkeypatch.setenv("CTRADER_DEMO_MOMENTUM_MAX_ZONE_ATR", "0.20")
    result = assess_demo_wave_entry(
        direction="LONG",
        current_price=105.20,
        entry_low=104.00,
        entry_high=104.20,
        h1=snap(trend="BULLISH", low=102.5),
        m15=snap(trend="BULLISH", low=103.5),
        m5=snap(trend="RANGE", low=104.0, bos="BULLISH"),
        m5_bars=bars((104.3, 103.9), (105.8, 105.0), (105.6, 105.1), (105.3, 105.0)),
        current_atr=1.0,
    )
    assert not result.ready
    assert result.reason == "WAIT_RETRACE_TO_ENTRY_ZONE"


def test_demo_trade_plan_no_longer_extends_fvg_to_current_price():
    source = Path("src/fx_scanner/demo_trade_plan_geometry.py").read_text()
    assert "entry_high = float(current_price)" not in source
    assert "entry_low = float(current_price)" not in source
    assert "if not wave.ready:" in source
    assert "HL_PULLBACK" in source
    assert "LH_PULLBACK" in source


def test_workflow_declares_wave_entry_thresholds():
    workflow = Path(".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    assert 'CTRADER_DEMO_WAVE_MIN_PULLBACK_ATR: "0.25"' in workflow
    assert 'CTRADER_DEMO_WAVE_MAX_ZONE_ATR: "0.50"' in workflow
    assert 'CTRADER_DEMO_MOMENTUM_MAX_ZONE_ATR: "0.20"' in workflow
    assert 'CTRADER_DEMO_CHASE_BLOCK_ATR: "2.0"' in workflow
