from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.models import Bar
from fx_scanner.research_h1_breakout_v1 import (
    FROZEN_CANDIDATES,
    pip_size,
    replay_candidate,
    reprice_cost,
    summarize,
)

UTC = timezone.utc


def _bars(symbol="EURUSD", breakout_up=True):
    start = datetime(2025, 1, 1, tzinfo=UTC)
    rows = []
    price = 1.1000 if not symbol.endswith("JPY") else 150.0
    step = 0.00005 if not symbol.endswith("JPY") else 0.005
    wick = 0.0004 if not symbol.endswith("JPY") else 0.04
    for i in range(240):
        close = price + i * step
        rows.append(
            Bar(
                symbol=symbol,
                timeframe="H1",
                timestamp=start + timedelta(hours=i),
                open=close - step / 2,
                high=close + wick,
                low=close - wick,
                close=close,
                tick_count=10,
                spread_avg=0.0,
                spread_max=0.0,
            )
        )
    # Force a decisive breakout after EMA warm-up.
    i = 220
    previous_high = max(row.high for row in rows[i - 20:i])
    previous_low = min(row.low for row in rows[i - 20:i])
    if breakout_up:
        close = previous_high + 10 * wick
    else:
        close = previous_low - 10 * wick
    rows[i] = Bar(
        symbol=symbol,
        timeframe="H1",
        timestamp=start + timedelta(hours=i),
        open=rows[i].open,
        high=max(close + wick, rows[i].high),
        low=min(close - wick, rows[i].low),
        close=close,
        tick_count=10,
        spread_avg=0.0,
        spread_max=0.0,
    )
    # Next bar entry and target-friendly continuation.
    entry = close
    rows[i + 1] = Bar(
        symbol=symbol,
        timeframe="H1",
        timestamp=start + timedelta(hours=i + 1),
        open=entry,
        high=entry + 30 * wick,
        low=entry - wick,
        close=entry + 20 * wick,
        tick_count=10,
        spread_avg=0.0,
        spread_max=0.0,
    )
    return tuple(rows)


def test_frozen_registry_has_distinct_predeclared_candidates():
    assert [row.name for row in FROZEN_CANDIDATES] == [
        "H1_DONCHIAN20_TREND_2R",
        "H1_COMP20_TREND_2R",
        "H1_COMP20_TREND_2P5R",
        "H1_DONCHIAN55_TREND_2R",
    ]


def test_pip_size_is_pair_aware():
    assert pip_size("EURUSD") == pytest.approx(0.0001)
    assert pip_size("USDJPY") == pytest.approx(0.01)


def test_replay_uses_next_bar_and_stop_first_contract():
    candidate = FROZEN_CANDIDATES[0]
    trades = replay_candidate(_bars(), candidate=candidate)
    assert trades
    trade = trades[0]
    assert trade.entry_time > trade.decision_time
    assert trade.entry_price > 0
    assert trade.stop_loss < trade.entry_price
    assert trade.take_profit > trade.entry_price


def test_cost_repricing_preserves_geometry_and_reduces_net_r():
    trades = replay_candidate(_bars(), candidate=FROZEN_CANDIDATES[0])
    assert trades
    priced = reprice_cost(trades, round_trip_cost_pips=1.5)
    assert priced[0].entry_price == trades[0].entry_price
    assert priced[0].stop_loss == trades[0].stop_loss
    assert priced[0].gross_r == trades[0].gross_r
    assert priced[0].net_r < priced[0].gross_r


def test_summary_uses_net_results():
    trades = replay_candidate(_bars(), candidate=FROZEN_CANDIDATES[0])
    priced = reprice_cost(trades, round_trip_cost_pips=1.2)
    result = summarize(priced)
    assert result.trades == len(priced)
    assert result.max_drawdown_r >= 0
