from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fx_scanner.xau_afiq_local_confirm_entry_v401 import resolve_confirm_entry

UTC = timezone.utc


def _bar(hour: int, *, o: float, h: float, l: float, c: float):
    return SimpleNamespace(timestamp=datetime(2026, 1, 1, hour, tzinfo=UTC), open=o, high=h, low=l, close=c)


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


def _prefix():
    return [
        _bar(0, o=100.0, h=101.0, l=98.0, c=100.0),
        _bar(1, o=100.0, h=101.0, l=99.0, c=100.0),
        _bar(2, o=100.0, h=102.0, l=99.2, c=101.0),
        _bar(3, o=101.0, h=102.0, l=99.5, c=100.5),
    ]


def test_mid_recovery_enters_next_open_then_targets():
    bars = tuple(_prefix() + [
        _bar(4, o=100.0, h=101.0, l=97.8, c=100.2),
        _bar(5, o=100.3, h=111.0, l=99.0, c=110.0),
    ])
    trade = resolve_confirm_entry(
        bars,
        signal_index=3,
        candidate=_candidate(),
        recovery_mode="ZONE_MID",
    )
    assert trade is not None
    assert trade.sweep_index == 4
    assert trade.recovery_index == 4
    assert trade.entry_index == 5
    assert trade.exit_reason == "TARGET"
    assert trade.pnl_price > 0


def test_two_acceptance_closes_before_entry_cancel_setup():
    bars = tuple(_prefix() + [
        _bar(4, o=100.0, h=100.5, l=95.0, c=95.5),
        _bar(5, o=95.5, h=96.0, l=94.0, c=95.0),
        _bar(6, o=95.0, h=101.0, l=94.0, c=100.5),
    ])
    trade = resolve_confirm_entry(
        bars,
        signal_index=3,
        candidate=_candidate(),
        recovery_mode="ZONE_MID",
    )
    assert trade is None


def test_single_wick_through_stop_can_recover_before_entry():
    bars = tuple(_prefix() + [
        _bar(4, o=100.0, h=101.0, l=95.5, c=100.2),
        _bar(5, o=100.3, h=111.0, l=99.0, c=110.0),
    ])
    trade = resolve_confirm_entry(
        bars,
        signal_index=3,
        candidate=_candidate(),
        recovery_mode="ZONE_MID",
    )
    assert trade is not None
    assert trade.entry_index == 5
    assert trade.exit_reason == "TARGET"


def test_post_entry_stop_first_is_conservative():
    bars = tuple(_prefix() + [
        _bar(4, o=100.0, h=101.0, l=97.8, c=100.2),
        _bar(5, o=100.3, h=111.0, l=95.0, c=105.0),
    ])
    trade = resolve_confirm_entry(
        bars,
        signal_index=3,
        candidate=_candidate(),
        recovery_mode="ZONE_MID",
    )
    assert trade is not None
    assert trade.exit_reason == "STOP_FIRST"
    assert trade.r_multiple == -1.0
