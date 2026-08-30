from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.config import load_project_config
from fx_scanner.liquidity import (
    DealingRange,
    FairValueGap,
    LiquidityKind,
    LiquidityLevel,
    LiquidityMap,
)
from fx_scanner.models import Bar, SignalState
from fx_scanner.ranking import PairRank
from fx_scanner.strategy import (
    SetupType,
    analyze_pair_mtf,
    select_pair_candidates,
)
from fx_scanner.technical import (
    DisplacementSignal,
    FVGSignal,
    StructureSnapshot,
    SweepSignal,
)

UTC = timezone.utc
AS_OF = datetime(2026, 8, 28, 14, 0, tzinfo=UTC)


def rank(symbol, rank_no, edge, macro_edge, direction="LONG"):
    return PairRank(
        symbol=symbol,
        direction=direction,
        relative_macro_edge=macro_edge,
        relative_technical_edge=edge,
        cross_asset_edge=80 if direction == "LONG" else -80,
        pair_edge=edge,
        absolute_edge=abs(edge),
        coverage=1.0,
        missing_components=(),
        rank=rank_no,
    )


def test_top8_top5_selection_requires_macro_direction_compatibility():
    symbols = [
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD",
        "AUDUSD", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP",
    ]
    ranked = [
        rank(symbol, i + 1, 90 - i, 100, "LONG")
        for i, symbol in enumerate(symbols)
    ]
    # Highest ranked item becomes macro-incompatible and must be excluded.
    ranked[0] = rank("EURUSD", 1, 90, -100, "LONG")
    selected = select_pair_candidates(ranked, macro_compatible_top=8, deep_analysis_top=5)
    assert len(selected.macro_compatible) == 8
    assert len(selected.deep_analysis) == 5
    assert "EURUSD" not in {x.symbol for x in selected.macro_compatible}


def snapshot(
    *,
    trend="BULLISH",
    bos="BULLISH",
    mss=None,
    sweep=None,
    fvg=None,
    displacement=None,
    low=1.095,
    high=1.105,
):
    return StructureSnapshot(
        trend=trend,
        last_swing_high=high,
        last_swing_low=low,
        bos=bos,
        mss=mss,
        displacement=displacement
        or DisplacementSignal("BULLISH", 1.0, 1.0, 0.6, 1.0, False),
        fvg=fvg,
        sweep=sweep,
    )


def fixed_liquidity():
    return LiquidityMap(
        "EURUSD",
        AS_OF,
        (
            LiquidityLevel(LiquidityKind.PDH, 1.1100, AS_OF),
            LiquidityLevel(LiquidityKind.PWH, 1.1200, AS_OF),
            LiquidityLevel(LiquidityKind.PDL, 1.0900, AS_OF),
            LiquidityLevel(LiquidityKind.PWL, 1.0800, AS_OF),
        ),
        DealingRange(1.0900, 1.1100, 1.1000, 0.45, "DISCOUNT"),
        (FairValueGap("BULLISH", 1.1000, 1.1010, AS_OF, "OPEN", 0.0),),
        (),
    )


def bars(tf, count, close=1.1005):
    step = {
        "D1": timedelta(days=1),
        "H4": timedelta(hours=4),
        "H1": timedelta(hours=1),
        "M15": timedelta(minutes=15),
        "M5": timedelta(minutes=5),
    }[tf]
    start = AS_OF - step * count
    out = []
    for i in range(count):
        o = close - 0.0001
        out.append(
            Bar(
                "EURUSD",
                tf,
                start + step * i,
                o,
                close + 0.0006,
                close - 0.0006,
                close,
                100,
                0.0001,
                0.0002,
            )
        )
    return out


def all_guard_flags(cfg):
    return {name: False for name in cfg.scoring["hard_guards"]}


def test_setup_without_m5_trigger_is_capped_at_setup_forming(monkeypatch):
    cfg = load_project_config()
    bullish_sweep = SweepSignal("BULLISH", 1.0950, 0.2, True, True)
    mapping = {
        "D1": snapshot(),
        "H4": snapshot(),
        "H1": snapshot(),
        "M15": snapshot(sweep=bullish_sweep),
        "M5": snapshot(
            bos="BULLISH",
            fvg=FVGSignal("BULLISH", 1.1000, 1.1010, 0.5, True),
        ),
    }
    monkeypatch.setattr(
        "fx_scanner.strategy.structure_snapshot",
        lambda x, **kwargs: mapping[x[0].timeframe],
    )
    monkeypatch.setattr(
        "fx_scanner.strategy.build_liquidity_map",
        lambda **kwargs: fixed_liquidity(),
    )
    bundle = {
        "D1": bars("D1", 20),
        "H4": bars("H4", 30),
        "H1": bars("H1", 40),
        "M15": bars("M15", 50),
        "M5": bars("M5", 60),
    }
    result = analyze_pair_mtf(
        rank=rank("EURUSD", 1, 80, 160),
        bars_by_timeframe=bundle,
        cfg=cfg,
        as_of=AS_OF,
        external_guard_flags=all_guard_flags(cfg),
        positioning_score=100,
        execution_quality_score=100,
    )
    assert result.setup_type == SetupType.LIQUIDITY_SWEEP_REVERSAL
    assert not result.trigger_confirmed
    assert result.decision.state == SignalState.SETUP_FORMING


def test_trigger_plan_and_clear_guards_can_reach_execution_ready(monkeypatch):
    cfg = load_project_config()
    bullish_sweep = SweepSignal("BULLISH", 1.0950, 0.2, True, True)
    valid_disp = DisplacementSignal("BULLISH", 3.0, 2.0, 0.9, 2.0, True)
    mapping = {
        "D1": snapshot(mss="BULLISH"),
        "H4": snapshot(mss="BULLISH"),
        "H1": snapshot(mss="BULLISH"),
        "M15": snapshot(sweep=bullish_sweep, displacement=valid_disp),
        "M5": snapshot(
            mss="BULLISH",
            displacement=valid_disp,
            fvg=FVGSignal("BULLISH", 1.1000, 1.1010, 0.5, True),
        ),
    }
    monkeypatch.setattr(
        "fx_scanner.strategy.structure_snapshot",
        lambda x, **kwargs: mapping[x[0].timeframe],
    )
    monkeypatch.setattr(
        "fx_scanner.strategy.build_liquidity_map",
        lambda **kwargs: fixed_liquidity(),
    )
    bundle = {
        "D1": bars("D1", 20),
        "H4": bars("H4", 30),
        "H1": bars("H1", 40),
        "M15": bars("M15", 50),
        "M5": bars("M5", 60),
    }
    result = analyze_pair_mtf(
        rank=rank("EURUSD", 1, 95, 200),
        bars_by_timeframe=bundle,
        cfg=cfg,
        as_of=AS_OF,
        external_guard_flags=all_guard_flags(cfg),
        positioning_score=100,
        execution_quality_score=100,
    )
    assert result.trigger_confirmed
    assert result.trade_plan is not None
    assert result.trade_plan.rr2 is not None and result.trade_plan.rr2 >= 1.5
    assert result.decision.state == SignalState.EXECUTION_READY


def test_missing_external_guard_input_still_fails_closed(monkeypatch):
    cfg = load_project_config()
    valid_disp = DisplacementSignal("BULLISH", 3.0, 2.0, 0.9, 2.0, True)
    bullish_sweep = SweepSignal("BULLISH", 1.0950, 0.2, True, True)
    mapping = {
        "D1": snapshot(mss="BULLISH"),
        "H4": snapshot(mss="BULLISH"),
        "H1": snapshot(mss="BULLISH"),
        "M15": snapshot(sweep=bullish_sweep, displacement=valid_disp),
        "M5": snapshot(mss="BULLISH", displacement=valid_disp),
    }
    monkeypatch.setattr(
        "fx_scanner.strategy.structure_snapshot",
        lambda x, **kwargs: mapping[x[0].timeframe],
    )
    monkeypatch.setattr(
        "fx_scanner.strategy.build_liquidity_map",
        lambda **kwargs: fixed_liquidity(),
    )
    guards = all_guard_flags(cfg)
    guards.pop("NEWS_BLOCK")
    bundle = {
        "D1": bars("D1", 20),
        "H4": bars("H4", 30),
        "H1": bars("H1", 40),
        "M15": bars("M15", 50),
        "M5": bars("M5", 60),
    }
    result = analyze_pair_mtf(
        rank=rank("EURUSD", 1, 95, 200),
        bars_by_timeframe=bundle,
        cfg=cfg,
        as_of=AS_OF,
        external_guard_flags=guards,
        positioning_score=100,
        execution_quality_score=100,
    )
    assert result.decision.state == SignalState.NO_TRADE
    assert "GUARD_INPUT_MISSING:NEWS_BLOCK" in result.decision.guards


def test_opposing_htf_trend_sets_structure_invalid(monkeypatch):
    cfg = load_project_config()
    mapping = {
        "D1": snapshot(trend="BEARISH", bos="BEARISH"),
        "H4": snapshot(),
        "H1": snapshot(),
        "M15": snapshot(),
        "M5": snapshot(),
    }
    monkeypatch.setattr(
        "fx_scanner.strategy.structure_snapshot",
        lambda x, **kwargs: mapping[x[0].timeframe],
    )
    monkeypatch.setattr(
        "fx_scanner.strategy.build_liquidity_map",
        lambda **kwargs: fixed_liquidity(),
    )
    bundle = {
        "D1": bars("D1", 20),
        "H4": bars("H4", 30),
        "H1": bars("H1", 40),
        "M15": bars("M15", 50),
        "M5": bars("M5", 60),
    }
    result = analyze_pair_mtf(
        rank=rank("EURUSD", 1, 90, 180),
        bars_by_timeframe=bundle,
        cfg=cfg,
        as_of=AS_OF,
        external_guard_flags=all_guard_flags(cfg),
        positioning_score=100,
        execution_quality_score=100,
    )
    assert result.computed_guards["STRUCTURE_INVALID"]
    assert result.decision.state == SignalState.NO_TRADE
