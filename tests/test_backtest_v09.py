from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.exceptions import DataContractError
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
        bar(2, low=1.1004, high=1.1011),
        bar(3, low=1.1004, high=1.1012),
        bar(4, low=1.1004, high=1.1013),
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
    with pytest.raises(DataContractError, match="duplicate trade_id"):
        engine().run([intent(), intent()], {"EURUSD": []}, timeframe_seconds=300)


def test_observed_broker_spread_overrides_lower_fallback_and_is_audited():
    wide = Bar(
        "EURUSD",
        "M5",
        SIGNAL + timedelta(minutes=5),
        1.1005,
        1.1010,
        1.1000,
        1.1005,
        100,
        0.0003,
        0.0004,
    )
    target = bar(2, low=1.1004, high=1.1023, close=1.1020)
    result = engine().evaluate(intent(), [wide, target], timeframe_seconds=300)
    assert result.spread_pips_used == pytest.approx(3.0)
    assert result.slippage_pips_used == pytest.approx(0.2)


def test_stress_multiplier_applies_to_observed_spread_not_only_fallback():
    wide = Bar(
        "EURUSD",
        "M5",
        SIGNAL + timedelta(minutes=5),
        1.1005,
        1.1010,
        1.1000,
        1.1005,
        100,
        0.0003,
        0.0004,
    )
    target = bar(2, low=1.1004, high=1.1023, close=1.1020)
    stressed = CostModel(0.8, 0.2, 0.2).stressed(
        spread_multiplier=1.25,
        slippage_multiplier=1.50,
    )
    result = engine(stressed).evaluate(intent(), [wide, target], timeframe_seconds=300)
    assert result.spread_pips_used == pytest.approx(3.75)
    assert result.slippage_pips_used == pytest.approx(0.30)


def test_feature_cutoff_cannot_reference_future_information():
    with pytest.raises(DataContractError, match="feature cutoff"):
        intent(feature_cutoff_at=SIGNAL + timedelta(seconds=1))


def test_mixed_timeframe_history_fails_closed():
    first = bar(1, low=1.1000, high=1.1010)
    second = Bar(
        "EURUSD",
        "H1",
        SIGNAL + timedelta(minutes=10),
        1.1005,
        1.1022,
        1.1004,
        1.1020,
        100,
        0.0001,
        0.0002,
    )
    with pytest.raises(DataContractError, match="one timeframe"):
        engine().evaluate(intent(), [first, second], timeframe_seconds=300)


def test_planned_stop_below_minimum_fails_before_costs_can_make_it_look_wider():
    tiny = intent(
        entry_low=1.1000,
        entry_high=1.1001,
        stop_loss=1.09995,
        take_profit=1.1020,
    )
    with pytest.raises(DataContractError, match="planned stop distance"):
        engine().evaluate(
            tiny,
            [bar(1, low=1.1000, high=1.1010)],
            timeframe_seconds=300,
        )


def test_history_ending_before_entry_expiry_is_open_not_missed():
    bars = [
        bar(1, low=1.1005, high=1.1010),
        bar(2, low=1.1004, high=1.1011),
    ]
    result = engine().evaluate(intent(entry_expiry_bars=4), bars, timeframe_seconds=300)
    assert result.outcome == TradeOutcome.OPEN
    assert result.net_r is None
    assert result.reason == "HISTORY_ENDED_BEFORE_ENTRY_EXPIRY"


def test_history_ending_after_entry_but_before_max_hold_is_open_not_forced_exit():
    bars = [
        bar(1, low=1.1000, high=1.1010),
        bar(2, low=1.1004, high=1.1012),
        bar(3, low=1.1004, high=1.1013),
    ]
    result = engine().evaluate(
        intent(maximum_hold_bars=12),
        bars,
        timeframe_seconds=300,
    )
    assert result.outcome == TradeOutcome.OPEN
    assert result.entry_at == bars[0].timestamp
    assert result.exit_at is None
    assert result.net_r is None
    assert result.reason == "HISTORY_ENDED_BEFORE_MAX_HOLD"


def test_long_stop_uses_bid_side_and_can_trigger_before_mid_touches_stop():
    # With 2-pip spread, bid is 1 pip below mid. Mid low stays above the
    # configured stop but bid reaches it.
    wide = Bar(
        "EURUSD",
        "M5",
        SIGNAL + timedelta(minutes=5),
        1.1005,
        1.1010,
        1.1000,
        1.1005,
        100,
        0.0002,
        0.0002,
    )
    stop_bar = Bar(
        "EURUSD",
        "M5",
        SIGNAL + timedelta(minutes=10),
        1.1000,
        1.1005,
        1.09905,
        1.0995,
        100,
        0.0002,
        0.0002,
    )
    result = engine().evaluate(intent(), [wide, stop_bar], timeframe_seconds=300)
    assert stop_bar.low > intent().stop_loss
    assert result.outcome == TradeOutcome.LOSS
    assert result.exit_spread_pips_used == pytest.approx(2.0)


def test_long_target_requires_bid_not_mid_high():
    entry = bar(1, low=1.1000, high=1.1010)
    # Mid high exceeds TP by only 0.5 pip while 2-pip spread means bid high is
    # still 0.5 pip below TP. The target must not be counted.
    near_target = Bar(
        "EURUSD",
        "M5",
        SIGNAL + timedelta(minutes=10),
        1.1010,
        1.10205,
        1.1006,
        1.1018,
        100,
        0.0002,
        0.0002,
    )
    result = engine().evaluate(
        intent(maximum_hold_bars=12),
        [entry, near_target],
        timeframe_seconds=300,
    )
    assert result.outcome == TradeOutcome.OPEN
    assert result.reason == "HISTORY_ENDED_BEFORE_MAX_HOLD"


def test_short_target_and_stop_use_ask_side_symmetrically():
    short_intent = intent(
        trade_id="SHORT-1",
        direction="SHORT",
        entry_low=1.1000,
        entry_high=1.1002,
        stop_loss=1.1012,
        take_profit=1.0980,
    )
    entry = Bar(
        "EURUSD",
        "M5",
        SIGNAL + timedelta(minutes=5),
        1.1001,
        1.1005,
        1.0998,
        1.1001,
        100,
        0.0002,
        0.0002,
    )
    near_target = Bar(
        "EURUSD",
        "M5",
        SIGNAL + timedelta(minutes=10),
        1.0990,
        1.0995,
        1.09795,
        1.0985,
        100,
        0.0002,
        0.0002,
    )
    result = engine().evaluate(
        short_intent,
        [entry, near_target],
        timeframe_seconds=300,
    )
    # Mid low is below TP, but ask low remains above it because of half-spread.
    assert near_target.low < short_intent.take_profit
    assert result.outcome == TradeOutcome.OPEN
    assert result.reason == "HISTORY_ENDED_BEFORE_MAX_HOLD"
