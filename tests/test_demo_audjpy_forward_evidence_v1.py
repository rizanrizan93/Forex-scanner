from datetime import datetime, timedelta, timezone

from fx_scanner.demo_audjpy_forward_evidence import (
    FORWARD_EVIDENCE_CONTRACT,
    STRATEGY_ID,
    audjpy_h4_evaluation_snapshot,
    evaluation_key,
)
from fx_scanner.models import Bar

UTC = timezone.utc


def _trend_bars(count: int = 240) -> tuple[Bar, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    previous = 100.0
    for index in range(count):
        close = 100.0 + index * 0.02
        if index == count - 1:
            close += 0.20
        open_ = previous
        high = max(open_, close) + 0.01
        low = min(open_, close) - 0.01
        rows.append(
            Bar(
                "AUDJPY",
                "H4",
                start + timedelta(hours=4 * index),
                open_,
                high,
                low,
                close,
                100,
                0.0,
                0.0,
            )
        )
        previous = close
    return tuple(rows)


def test_audjpy_forward_snapshot_is_non_authoritative_and_pair_specific():
    bars = _trend_bars()
    as_of = bars[-1].timestamp + timedelta(hours=5)
    snapshot = audjpy_h4_evaluation_snapshot(bars, as_of=as_of)

    assert snapshot["contract"] == FORWARD_EVIDENCE_CONTRACT
    assert snapshot["symbol"] == "AUDJPY"
    assert snapshot["strategy_id"] == STRATEGY_ID == "H4_DONCHIAN40_ADX20"
    assert snapshot["execution_influence"] is False
    assert snapshot["execution_eligible"] is False
    assert snapshot["active"] is True
    assert snapshot["direction"] == "LONG"
    assert snapshot["reason"] == "DONCHIAN40_BREAKOUT_TREND_LONG"
    assert snapshot["shadow_sl"] < snapshot["signal_close"] < snapshot["shadow_tp"]
    assert evaluation_key(snapshot)


def test_audjpy_forward_snapshot_fails_closed_on_short_history():
    bars = _trend_bars(100)
    as_of = bars[-1].timestamp + timedelta(hours=5)
    snapshot = audjpy_h4_evaluation_snapshot(bars, as_of=as_of)

    assert snapshot["active"] is False
    assert snapshot["execution_eligible"] is False
    assert snapshot["reason"] == "INSUFFICIENT_H4_HISTORY"
    assert evaluation_key(snapshot) is None
