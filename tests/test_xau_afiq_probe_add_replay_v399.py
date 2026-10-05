from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fx_scanner.xau_afiq_probe_add_replay_v399 import resolve_probe_add

UTC = timezone.utc


def _bar(hour: int, *, o: float, h: float, l: float, c: float):
    return SimpleNamespace(timestamp=datetime(2026, 1, 1, hour, tzinfo=UTC), open=o, high=h, low=l, close=c)


def _candidate():
    return {
        "zone_id": "z1",
        "direction": "LONG",
        "entry_reference": 100.0,
        "low": 99.0,
        "high": 101.0,
        "structural_invalidation": 97.0,
        "validation_level": 104.0,
        "targets": [110.0],
        "score": 11.0,
        "timeframe": "H1",
    }


def test_probe_timeout_cuts_one_quarter_only():
    bars = (
        _bar(0, o=100.0, h=101.0, l=99.0, c=100.0),
        _bar(1, o=100.0, h=102.0, l=99.0, c=101.0),
        _bar(2, o=101.0, h=103.0, l=100.0, c=102.0),
        _bar(3, o=102.0, h=103.0, l=101.0, c=102.0),
    )
    trade = resolve_probe_add(bars, signal_index=0, candidate=_candidate(), validation_window=2)
    assert trade is not None
    assert trade.exit_reason == "VALIDATION_TIMEOUT_EXIT"
    assert trade.add_entry_index is None
    assert trade.exposure_fraction == 0.25


def test_reclaim_adds_at_next_open_then_target():
    bars = (
        _bar(0, o=100.0, h=101.0, l=99.0, c=100.0),
        _bar(1, o=100.0, h=104.2, l=99.0, c=104.1),
        _bar(2, o=104.0, h=111.0, l=103.0, c=110.0),
    )
    trade = resolve_probe_add(bars, signal_index=0, candidate=_candidate(), validation_window=2)
    assert trade is not None
    assert trade.confirmed is True
    assert trade.add_entry_index == 2
    assert trade.exit_reason == "TARGET_AFTER_ADD"
    assert trade.exposure_fraction == 1.0
    assert trade.pnl_price_weighted > 0


def test_stop_first_before_reclaim():
    bars = (
        _bar(0, o=100.0, h=101.0, l=99.0, c=100.0),
        _bar(1, o=100.0, h=105.0, l=96.0, c=104.5),
    )
    trade = resolve_probe_add(bars, signal_index=0, candidate=_candidate(), validation_window=2)
    assert trade is not None
    assert trade.exit_reason == "STOP_FIRST_PROBE"
    assert trade.confirmed is False
    assert trade.pnl_price_weighted < 0
