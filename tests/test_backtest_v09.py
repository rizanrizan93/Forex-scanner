from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.models import Bar
from fx_scanner.validation.backtest import (
    BacktestEngine,
    CostModel,
    TradeIntent,
    TradeOutcome,
)

UTC = timezone.utc
SIGNAL = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)


def bar(i, *, low, high, close=1.1005, symbol="EURUSD"):
    ts = SIGNAL + timedelta(minutes=5 * i)
    return Bar(
        symbol,
        "M5",
        ts,
        close,
        high,
        low,
        close,
        100,
        0.0001,
        0.0002,
    )


def intent(**kwargs):
    values = dict(
        trade_id="T1",
        symbol="EURUSD",
        direction="LONG",
        signal_at=SIGNAL,
        entry_low=1.1000,
        entry_high=1.1002,
        stop_loss=1.0990,
        take_profit=1.1020,
        pip_size=0.0001,
        setup="TREND_CONTINUATION",
        regime="TREND",
        entry_expiry_bars=4,
        maximum_hold_bars=12,
    )
    values.update(kwargs)
    return TradeIntent(**values)


def engine(cost=None):
    return BacktestEngine(
        cost_model=cost or CostModel(0.8, 0.2, 0.2, 0.0),
        ambiguous_bar_policy="STOP_FIRST",
        minimum_stop_distance_pips=2.0,
    )


def test_signal_candle_is_never_used_for_fill_or_outcome():
    bars = [
        bar(0, low=1.0980, high=1.1030),
        bar(1, low=1.1005, high=1.1010),
        bar(2, low=1.1006, high=1.1011),
        bar(3, low=1.1007, high=1.1012),
        bar(4, low=1.1008, high=1.1013),
    ]
    result = engine().evaluate(intent(), bars, timeframe_seconds=300)
    assert result.outcome == TradeOutcome.MISSED
    assert result.reason == "ENTRY_NOT_TOUCHED_BEFORE_EXPIRY"


def test_target_only_on_entry_bar_is_not_counted_as_win():
    bars = [
        bar(1, low=1.1000, high=1.1025, close=1.1006),
        bar(2, low=1.1003, high=1.1021, close=1.1018),
    ]
    result = engine().evaluate(intent(), bars, timeframe_seconds=300)
    assert result.outcome == TradeOutcome.WIN
    assert result.entry_at == bars[0].timestamp
    assert result.exit_at == bars[1].timestamp
    assert result.bars_held == 1
    assert result.reason == "TARGET_HIT"


def test_entry_bar_stop_and_target_is_conservative_loss_and_audited_ambiguous():
    bars = [bar(1, low=1.0985, high=1.1025, close=1.1005)]
    result = engine().evaluate(intent(), bars, timeframe_seconds=300)
    assert result.outcome == TradeOutcome.LOSS
    assert result.net_r < -1.0
    assert result.ambiguous_bar is True
    assert result.reason == "STOP_FIRST_AMBIGUOUS"


def test_stressed_costs_reduce_net_r_without_changing_future_information():
    bars = [
        bar(1, low=1.1000, high=1.1010),
        bar(2, low=1.1004, high=1.1022, close=1.1020),
    ]
    base = CostModel(0.8, 0.2, 0.2)
    stressed = base.stressed(spread_multiplier=1.25, slippage_multiplier=1.50)
    base_result = engine(base).evaluate(intent(), bars, timeframe_seconds=300)
    stressed_result = engine(stressed).evaluate(intent(), bars, timeframe_seconds=300)
    assert base_result.outcome == TradeOutcome.WIN
    assert stressed_result.outcome == TradeOutcome.WIN
    assert stressed_result.net_r < base_result.net_r
    assert stressed_result.cost_r > base_result.cost_r


def test_missing_symbol_history_is_preserved_as_missed_not_zero_return():
    result = engine().run([intent()], {}, timeframe_seconds=300)
    trade = result.trades[0]
    assert trade.outcome == TradeOutcome.MISSED
    assert trade.net_r is None
    assert trade.reason == "MISSING_SYMBOL_HISTORY"


def test_duplicate_trade_id_fails_closed():
    with pytest.raises(Exception, match="duplicate trade_id"):
        engine().run([intent(), intent()], {"EURUSD": []}, timeframe_seconds=300)
