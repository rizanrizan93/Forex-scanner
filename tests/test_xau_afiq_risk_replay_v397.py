from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fx_scanner.xau_afiq_risk_replay_v397 import _metrics, resolve_stop_first

UTC = timezone.utc


def _bar(hour: int, *, o: float, h: float, l: float, c: float):
    return SimpleNamespace(timestamp=datetime(2026, 1, 1, hour, tzinfo=UTC), open=o, high=h, low=l, close=c)


def _candidate():
    return {
        "direction": "LONG",
        "low": 100.0,
        "high": 104.0,
        "structural_invalidation": 98.0,
        "targets": [110.0],
        "zone_id": "z1",
        "timeframe": "H1",
        "score": 11.0,
    }


def test_stop_first_wins_same_bar_conflict():
    bars = (
        _bar(0, o=102.0, h=103.0, l=101.0, c=102.0),
        _bar(1, o=102.0, h=111.0, l=97.0, c=105.0),
    )
    trade = resolve_stop_first(bars, signal_index=0, candidate=_candidate(), variant="EARLY_STOP_FIRST", require_entry_in_zone=True)
    assert trade is not None
    assert trade.exit_reason == "STOP_FIRST"
    assert trade.r_multiple == -1.0


def test_tiny_structural_risk_is_rejected():
    bars = (
        _bar(0, o=102.0, h=103.0, l=101.0, c=102.0),
        _bar(1, o=102.0, h=108.0, l=101.0, c=107.0),
    )
    candidate = _candidate()
    candidate["structural_invalidation"] = 101.9
    assert resolve_stop_first(bars, signal_index=0, candidate=candidate, variant="EARLY_STOP_FIRST", require_entry_in_zone=True) is None


def test_metrics_fixed_price_pf_is_primary():
    bars = (
        _bar(0, o=102.0, h=103.0, l=101.0, c=102.0),
        _bar(1, o=102.0, h=111.0, l=101.0, c=110.0),
    )
    trade = resolve_stop_first(bars, signal_index=0, candidate=_candidate(), variant="EARLY_STOP_FIRST", require_entry_in_zone=True)
    assert trade is not None
    metrics = _metrics([trade])
    assert metrics["fixed_price_pf"] == float("inf")
    assert metrics["expectancy_price"] > 0
