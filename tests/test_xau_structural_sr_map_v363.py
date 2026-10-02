from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fx_scanner.xau_structural_sr_map_v363 import (
    build_structural_sr_map,
)


def _bars(closes: list[float], *, start: datetime | None = None):
    start = start or datetime(2026, 10, 1, tzinfo=UTC)
    rows = []
    for i, close in enumerate(closes):
        open_ = closes[i - 1] if i else close
        high = max(open_, close) + 0.25
        low = min(open_, close) - 0.25
        rows.append(
            SimpleNamespace(
                timestamp=start + timedelta(minutes=15 * i),
                open=open_,
                high=high,
                low=low,
                close=close,
            )
        )
    return rows


def _resistance_level() -> dict:
    return {
        "kind": "RESISTANCE",
        "price": 100.0,
        "strength": 3.0,
        "sources": ["H2_SWING_HIGH", "PRIOR_DAY_HIGH"],
        "available_at": "2026-10-01T00:00:00+00:00",
    }


def _map(rows, *, as_of=None):
    as_of = as_of or rows[-1].timestamp + timedelta(minutes=15)
    return build_structural_sr_map(
        levels=[_resistance_level()],
        bars_m15=rows,
        bars_m5=[],
        as_of=as_of,
        price_now=float(rows[-1].close),
        atr_reference=10.0,
    )


def test_v363_resistance_requires_acceptance_retest_and_hold_before_support_flip():
    closes = [98.4] * 24 + [99.0, 101.2, 101.0, 100.9, 101.0, 101.1]
    rows = _bars(closes)
    # Force the retest wick into the structural band while keeping the close above it.
    rows[27].low = 100.30
    result = _map(rows)
    level = result["levels"][0]

    assert level["lifecycle_state"] == "CONFIRMED_SUPPORT_FLIP"
    assert level["current_role"] == "SUPPORT"
    assert level["confirmed_flip"] is True
    assert result["nearest_support"]["price"] == 100.0
    assert result["direction_signal"] is False
    assert result["execution_authority"] is False


def test_v363_failed_bull_breakout_requires_reclaim_and_is_not_support():
    closes = [98.4] * 24 + [99.0, 101.2, 101.0, 100.4, 99.0, 99.1]
    rows = _bars(closes)
    result = _map(rows)
    level = result["levels"][0]

    assert level["lifecycle_state"] == "FAILED_BULL_BREAKOUT_RECLAIM_REQUIRED"
    assert level["reclaim_required"] is True
    assert level["current_role"] == "RESISTANCE_CANDIDATE"
    assert result["nearest_support"] == {}


def test_v363_wick_above_resistance_without_close_acceptance_is_rejection_not_flip():
    closes = [98.8] * 30
    rows = _bars(closes)
    rows[-1].high = 101.2
    rows[-1].close = 100.2
    result = _map(rows)
    level = result["levels"][0]

    assert level["lifecycle_state"] == "UPSIDE_SWEEP_LIKE_REJECTION"
    assert level["current_role"] == "RESISTANCE"
    assert level["confirmed_flip"] is False


def test_v363_ignores_incomplete_breakout_candle():
    closes = [98.8] * 29 + [101.3]
    rows = _bars(closes)
    # The final candle has opened but has not completed at as_of.
    as_of = rows[-1].timestamp + timedelta(minutes=5)
    result = _map(rows, as_of=as_of)
    level = result["levels"][0]

    assert level["lifecycle_state"] == "ACTIVE_RESISTANCE"
    assert level["current_role"] == "RESISTANCE"


def test_v363_paths_are_conditional_context_not_execution_signals():
    levels = [
        {
            "kind": "SUPPORT",
            "price": 95.0,
            "strength": 2.0,
            "sources": ["H2_SWING_LOW"],
            "available_at": "2026-10-01T00:00:00+00:00",
        },
        {
            "kind": "RESISTANCE",
            "price": 105.0,
            "strength": 2.0,
            "sources": ["H2_SWING_HIGH"],
            "available_at": "2026-10-01T00:00:00+00:00",
        },
    ]
    rows = _bars([100.0] * 30)
    result = build_structural_sr_map(
        levels=levels,
        bars_m15=rows,
        bars_m5=[],
        as_of=rows[-1].timestamp + timedelta(minutes=15),
        price_now=100.0,
        atr_reference=10.0,
    )

    assert result["bull_path"]["state"] == "CONDITIONAL_CONTEXT_ONLY"
    assert result["bear_path"]["state"] == "CONDITIONAL_CONTEXT_ONLY"
    assert result["bull_path"]["checkpoints"][0]["price"] == 105.0
    assert result["bear_path"]["checkpoints"][0]["price"] == 95.0
    assert result["execution_influence"] is False
