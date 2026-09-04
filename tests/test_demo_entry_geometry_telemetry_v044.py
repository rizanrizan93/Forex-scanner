from datetime import datetime, timezone
from types import SimpleNamespace

from fx_scanner.demo_incremental_calibration import summarize_closed_events
from fx_scanner.demo_technical_producer import _persist_geometry_events
from fx_scanner.demo_trade_plan_geometry import (
    build_demo_trade_plan,
    plan_geometry_evidence,
)
from fx_scanner.liquidity import FairValueGap, LiquidityKind, LiquidityLevel


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


class FakeLiquidity:
    def __init__(self):
        self.observed_at = NOW
        self.fvgs = (
            FairValueGap("BULLISH", 104.20, 104.40, NOW, "PARTIAL", 0.25),
        )
        self._above = (
            LiquidityLevel(LiquidityKind.SWING_HIGH, 105.20, NOW),
            LiquidityLevel(LiquidityKind.LONDON_HIGH, 105.80, NOW),
        )

    def levels_above(self, _price):
        return self._above

    def levels_below(self, _price):
        return ()


def snap(*, trend="BULLISH", low=103.8, high=105.2, bos=None, mss=None, displacement=None, sweep=None):
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


def bars(*pairs):
    return [SimpleNamespace(high=float(high), low=float(low)) for high, low in pairs]


def test_plan_retains_exact_hl_geometry_for_durable_signal(monkeypatch):
    import fx_scanner.demo_trade_plan_geometry as geometry

    monkeypatch.setattr(geometry, "atr", lambda _bars, _period: 1.0)
    monkeypatch.setenv("CTRADER_DEMO_WAVE_MIN_PULLBACK_ATR", "0.25")
    monkeypatch.setenv("CTRADER_DEMO_WAVE_MAX_ZONE_ATR", "0.50")
    monkeypatch.setenv("CTRADER_DEMO_MOMENTUM_MAX_ZONE_ATR", "0.20")
    plan = build_demo_trade_plan(
        direction="LONG",
        current_price=104.50,
        m15=snap(low=103.8),
        h1=snap(low=103.0, high=106.0),
        m5=snap(trend="RANGE", low=104.0, bos="BULLISH"),
        liquidity=FakeLiquidity(),
        m5_bars=bars((104.2, 103.9), (104.7, 104.2), (105.0, 104.6), (104.8, 104.4)),
        atr_period=14,
        sl_buffer_atr=0.15,
        minimum_entry_zone_atr=0.05,
        chase_block_atr=2.0,
    )
    assert plan is not None
    evidence = plan_geometry_evidence(plan)
    assert evidence is not None
    assert evidence.entry_mode == "HL_PULLBACK"
    assert evidence.confirmation == "M5_STRUCTURE_BREAK"
    assert evidence.pullback_atr >= 0.25
    assert evidence.zone_distance_atr <= 0.50
    assert evidence.fvg_status == "PARTIAL"
    assert evidence.exit_model == "STRUCTURE_LIQUIDITY"


class FakeStore:
    def __init__(self):
        self.events = []

    def record_order_event(self, **kwargs):
        self.events.append(kwargs)


def test_ready_signal_geometry_is_persisted_with_signal_uuid(monkeypatch):
    import fx_scanner.demo_trade_plan_geometry as geometry

    monkeypatch.setattr(geometry, "atr", lambda _bars, _period: 1.0)
    monkeypatch.setenv("CTRADER_ACCOUNT_ID", "12345")
    monkeypatch.setenv("CTRADER_DEMO_WAVE_MIN_PULLBACK_ATR", "0.25")
    plan = build_demo_trade_plan(
        direction="LONG",
        current_price=104.50,
        m15=snap(low=103.8),
        h1=snap(low=103.0, high=106.0),
        m5=snap(trend="RANGE", low=104.0, bos="BULLISH"),
        liquidity=FakeLiquidity(),
        m5_bars=bars((104.2, 103.9), (104.7, 104.2), (105.0, 104.6), (104.8, 104.4)),
        atr_period=14,
        sl_buffer_atr=0.15,
        minimum_entry_zone_atr=0.05,
        chase_block_atr=2.0,
    )
    store = FakeStore()
    policy = SimpleNamespace(ctrader={"account_id_env": "CTRADER_ACCOUNT_ID", "trader_login_env": "CTRADER_TRADER_LOGIN"})
    row = {
        "id": "00000000-0000-0000-0000-000000000001",
        "run_id": "run-1",
        "symbol": "EURUSD",
        "direction": "LONG",
        "setup_type": "TREND_CONTINUATION",
        "state": "EXECUTION_READY",
        "final_score": 70.0,
    }
    analysis = SimpleNamespace(trade_plan=plan)
    written, missing = _persist_geometry_events(
        store=store,
        policy=policy,
        persisted=(row,),
        analyses={"EURUSD": analysis},
    )
    assert written == 1
    assert missing == 0
    assert store.events[0]["event_type"] == "DEMO_SIGNAL_GEOMETRY"
    assert store.events[0]["signal_key"] == row["id"]
    assert store.events[0]["payload"]["entry_mode"] == "HL_PULLBACK"


def test_incremental_calibration_separates_new_entry_modes_from_legacy():
    rows = [
        {"payload": {"symbol": "EURUSD", "setup_type": "TREND_CONTINUATION", "entry_mode": "HL_PULLBACK", "confirmation": "M5_STRUCTURE_BREAK", "exit_type": "TP_HIT", "net_pnl_estimate": 1.0}},
        {"payload": {"symbol": "GBPUSD", "setup_type": "TREND_CONTINUATION", "entry_mode": "LH_PULLBACK", "confirmation": "M5_SWEEP_RECLAIM", "exit_type": "SL_HIT", "net_pnl_estimate": -1.0}},
        {"payload": {"symbol": "USDCHF", "setup_type": "TREND_CONTINUATION", "exit_type": "SL_HIT", "net_pnl_estimate": -0.5}},
    ]
    summary = summarize_closed_events(rows)
    assert set(summary.by_entry_mode) == {"HL_PULLBACK", "LH_PULLBACK", "LEGACY"}
    assert summary.by_entry_mode["HL_PULLBACK"].wins == 1
    assert summary.by_entry_mode["LH_PULLBACK"].losses == 1
    assert set(summary.by_confirmation) == {"M5_STRUCTURE_BREAK", "M5_SWEEP_RECLAIM", "LEGACY"}
