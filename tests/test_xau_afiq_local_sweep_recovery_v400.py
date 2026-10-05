from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fx_scanner.xau_afiq_local_sweep_recovery_v400 import (
    _select_liquidity,
    resolve_local_recovery,
)

UTC = timezone.utc


def _bar(hour: int, *, o: float, h: float, l: float, c: float):
    return SimpleNamespace(timestamp=datetime(2026, 1, 1, hour, tzinfo=UTC), open=o, high=h, low=l, close=c)


def _bars_for_signal_and_entry(*tail):
    base = [
        _bar(0, o=100.0, h=101.0, l=98.0, c=100.0),
        _bar(1, o=100.0, h=101.0, l=99.0, c=100.0),
        _bar(2, o=100.0, h=102.0, l=99.2, c=101.0),
        _bar(3, o=101.0, h=102.0, l=99.5, c=100.5),
    ]
    return tuple(base + list(tail))


def _candidate():
    return {
        "zone_id": "z1",
        "direction": "LONG",
        "entry_reference": 100.5,
        "low": 99.0,
        "high": 101.0,
        "structural_invalidation": 96.0,
        "targets": [110.0],
        "score": 11.0,
        "timeframe": "H1",
        "liquidity": [
            {"side": "SELL_SIDE", "price": 98.0, "pivot_index": 0, "available_index": 2},
        ],
    }


def test_selects_only_unswept_adverse_liquidity():
    bars = _bars_for_signal_and_entry(_bar(4, o=100.0, h=101.0, l=99.0, c=100.0))
    level = _select_liquidity(_candidate(), bars, 3, 100.0, 96.0)
    assert level == 98.0


def test_consumed_liquidity_is_rejected():
    bars = list(_bars_for_signal_and_entry(_bar(4, o=100.0, h=101.0, l=99.0, c=100.0)))
    bars[3] = _bar(3, o=101.0, h=102.0, l=97.9, c=100.5)
    assert _select_liquidity(_candidate(), tuple(bars), 3, 100.0, 96.0) is None


def test_sweep_then_mid_recovery_adds_next_open_and_targets():
    bars = _bars_for_signal_and_entry(
        _bar(4, o=100.0, h=101.0, l=97.8, c=100.2),
        _bar(5, o=100.3, h=111.0, l=99.0, c=110.0),
    )
    trade = resolve_local_recovery(
        bars,
        signal_index=3,
        candidate=_candidate(),
        recovery_mode="ZONE_MID",
    )
    assert trade is not None
    assert trade.sweep_index == 4
    assert trade.recovery_index == 4
    assert trade.add_entry_index == 5
    assert trade.exit_reason == "TARGET_AFTER_ADD"
    assert trade.exposure_fraction == 1.0
    assert trade.pnl_price_weighted > 0


def test_stop_first_beats_same_bar_recovery():
    bars = _bars_for_signal_and_entry(
        _bar(4, o=100.0, h=101.0, l=95.0, c=100.5),
    )
    trade = resolve_local_recovery(
        bars,
        signal_index=3,
        candidate=_candidate(),
        recovery_mode="SWEPT_LIQUIDITY",
    )
    assert trade is not None
    assert trade.exit_reason == "STOP_FIRST_PROBE"
    assert trade.add_entry_index is None
    assert trade.pnl_price_weighted < 0


def test_no_sweep_exits_probe_after_window():
    tail = [
        _bar(hour, o=100.0, h=102.0, l=98.5, c=100.5)
        for hour in range(4, 13)
    ]
    bars = _bars_for_signal_and_entry(*tail)
    trade = resolve_local_recovery(
        bars,
        signal_index=3,
        candidate=_candidate(),
        recovery_mode="ZONE_MID",
        recovery_window=8,
    )
    assert trade is not None
    assert trade.exit_reason == "NO_SWEEP_TIMEOUT_EXIT"
    assert trade.exposure_fraction == 0.25
