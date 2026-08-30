from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.exceptions import DataContractError
from fx_scanner.models import Bar
from fx_scanner.validation.backtest import TradeIntent
from fx_scanner.validation.replay import PointInTimeReplay

UTC = timezone.utc
BASE = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)


def m5(i):
    ts = BASE + timedelta(minutes=5 * i)
    return Bar(
        "EURUSD",
        "M5",
        ts,
        1.1000,
        1.1010,
        1.0990,
        1.1002,
        100,
        0.0001,
        0.0002,
    )


def signal(as_of, trade_id="R1", cutoff=None):
    return TradeIntent(
        trade_id,
        "EURUSD",
        "LONG",
        as_of,
        1.1000,
        1.1002,
        1.0990,
        1.1020,
        0.0001,
        "SETUP",
        "TREND",
        feature_cutoff_at=cutoff,
    )


def test_point_in_time_view_exposes_only_closed_bars():
    replay = PointInTimeReplay(
        {"EURUSD": {"M5": [m5(0), m5(1), m5(2)]}},
        timeframe_seconds={"M5": 300},
    )
    view = replay.view(BASE + timedelta(minutes=7))
    visible = view.bars("EURUSD", "M5")
    assert len(visible) == 1
    assert visible[0].timestamp == BASE


def test_replay_signal_must_match_replay_timestamp():
    replay = PointInTimeReplay(
        {"EURUSD": {"M5": [m5(0), m5(1), m5(2)]}},
        timeframe_seconds={"M5": 300},
    )
    as_of = BASE + timedelta(minutes=10)

    def factory(view):
        return [signal(view.as_of - timedelta(minutes=1))]

    with pytest.raises(DataContractError, match="signal_at must equal"):
        replay.run([as_of], factory)


def test_replay_emits_unique_point_in_time_intents():
    replay = PointInTimeReplay(
        {"EURUSD": {"M5": [m5(i) for i in range(6)]}},
        timeframe_seconds={"M5": 300},
    )
    times = [BASE + timedelta(minutes=10), BASE + timedelta(minutes=15)]

    def factory(view):
        assert all(
            bar.timestamp + timedelta(minutes=5) <= view.as_of
            for bar in view.bars("EURUSD", "M5")
        )
        return [signal(view.as_of, trade_id=f"R-{int(view.as_of.timestamp())}")]

    result = replay.run(times, factory)
    assert result.timestamps_processed == 2
    assert len(result.intents) == 2
    assert result.intents[0].feature_cutoff_at == times[0]


def test_replay_rejects_duplicate_trade_ids_across_timestamps():
    replay = PointInTimeReplay(
        {"EURUSD": {"M5": [m5(i) for i in range(6)]}},
        timeframe_seconds={"M5": 300},
    )
    times = [BASE + timedelta(minutes=10), BASE + timedelta(minutes=15)]

    with pytest.raises(DataContractError, match="duplicate replay trade_id"):
        replay.run(times, lambda view: [signal(view.as_of, trade_id="DUP")])
