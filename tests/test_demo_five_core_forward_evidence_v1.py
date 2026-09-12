from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.demo_five_core_forward_evidence import (
    FORWARD_EVIDENCE_CONTRACT,
    XAU_D1_RESEARCH_BOUNDARY_SECONDS_UTC,
    bar_boundary_snapshot,
    evaluation_key,
    xau_d1_evaluation_snapshot,
)
from fx_scanner.demo_five_core_router import evaluate_xau_d1_tsmom_60_200
from fx_scanner.models import Bar

UTC = timezone.utc


def _bars(*, hour: int = 0) -> tuple[Bar, ...]:
    start = datetime(2025, 1, 1, hour, tzinfo=UTC)
    rows = []
    for i in range(205):
        px = 2000.0 + i * 2.0
        rows.append(
            Bar(
                symbol="XAUUSD",
                timeframe="D1",
                timestamp=start + timedelta(days=i),
                open=px,
                high=px + 10.0,
                low=px - 10.0,
                close=px + 2.0,
                tick_count=100,
                spread_avg=0.1,
                spread_max=0.2,
            )
        )
    return tuple(rows)


def test_forward_snapshot_matches_frozen_signal_math_and_is_non_authoritative():
    bars = _bars()
    as_of = bars[-1].timestamp + timedelta(minutes=10)
    signal = evaluate_xau_d1_tsmom_60_200(bars, as_of=as_of)
    snapshot = xau_d1_evaluation_snapshot(bars, as_of=as_of, signal=signal)

    assert snapshot["contract"] == FORWARD_EVIDENCE_CONTRACT
    assert snapshot["execution_influence"] is False
    assert snapshot["strategy_id"] == "D1_TSMOM_60_200"
    assert snapshot["direction"] == signal.direction == "LONG"
    assert snapshot["active"] == signal.active
    assert snapshot["reason"] == signal.reason
    assert snapshot["closed_bars"] >= 200
    assert snapshot["signal_close"] is not None
    assert snapshot["ema200"] is not None
    assert snapshot["return_60"] > 0
    assert snapshot["atr14"] == pytest.approx(signal.atr)
    assert snapshot["distance_to_ema200_pct"] > 0
    assert evaluation_key(snapshot)


def test_boundary_snapshot_detects_research_boundary_mismatch_without_changing_signal():
    bars = _bars(hour=22)
    boundary = bar_boundary_snapshot(
        bars,
        expected_open_seconds_utc=XAU_D1_RESEARCH_BOUNDARY_SECONDS_UTC,
    )
    assert boundary["unique_open_seconds_utc"] == [22 * 3600]
    assert boundary["expected_open_seconds_utc"] == 0
    assert boundary["matches_expected_boundary"] is False


def test_evaluation_key_requires_real_d1_evidence():
    snapshot = xau_d1_evaluation_snapshot((), as_of=datetime(2026, 9, 12, tzinfo=UTC))
    assert snapshot["closed_bars"] == 0
    assert evaluation_key(snapshot) is None
