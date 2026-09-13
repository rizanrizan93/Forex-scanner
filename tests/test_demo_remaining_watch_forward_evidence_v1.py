from datetime import datetime, timedelta, timezone

from fx_scanner.demo_remaining_watch_forward_evidence import (
    FORWARD_EVIDENCE_CONTRACT,
    evaluate_remaining_watch_pair,
    evaluation_key,
)
from fx_scanner.models import Bar

UTC = timezone.utc


def _trend_bars(symbol: str, timeframe: str, *, count: int, step_hours: int, step: float) -> tuple[Bar, ...]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    rows = []
    previous = 100.0
    for index in range(count):
        close = 100.0 + index * step
        if timeframe == "H4" and index == count - 1:
            close += 0.40
        open_ = previous
        high = max(open_, close) + 0.01
        low = min(open_, close) - 0.01
        rows.append(
            Bar(
                symbol,
                timeframe,
                start + timedelta(hours=step_hours * index),
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


def test_d1_tsmom_remaining_watch_pairs_are_shadow_only():
    for symbol, strategy_id in (
        ("GBPJPY", "D1_TSMOM_60_200"),
        ("CADJPY", "D1_TSMOM_120_200"),
    ):
        bars = _trend_bars(symbol, "D1", count=240, step_hours=24, step=0.05)
        as_of = bars[-1].timestamp + timedelta(hours=25)
        snapshot = evaluate_remaining_watch_pair(symbol, bars, as_of=as_of)

        assert snapshot["contract"] == FORWARD_EVIDENCE_CONTRACT
        assert snapshot["strategy_id"] == strategy_id
        assert snapshot["execution_influence"] is False
        assert snapshot["promotion_authority"] is False
        assert snapshot["execution_eligible"] is False
        assert snapshot["direction"] == "LONG"
        assert snapshot["active"] is True
        assert snapshot["shadow_sl"] < snapshot["signal_close"] < snapshot["shadow_tp"]
        assert evaluation_key(snapshot)


def test_usdcad_h4_donchian_remaining_watch_is_shadow_only():
    bars = _trend_bars("USDCAD", "H4", count=240, step_hours=4, step=0.002)
    as_of = bars[-1].timestamp + timedelta(hours=5)
    snapshot = evaluate_remaining_watch_pair("USDCAD", bars, as_of=as_of)

    assert snapshot["strategy_id"] == "H4_DONCHIAN40_ADX20"
    assert snapshot["execution_influence"] is False
    assert snapshot["promotion_authority"] is False
    assert snapshot["execution_eligible"] is False
    assert snapshot["direction"] == "LONG"
    assert snapshot["active"] is True
    assert snapshot["reason"] == "DONCHIAN40_BREAKOUT_TREND_LONG"
    assert snapshot["shadow_sl"] < snapshot["signal_close"] < snapshot["shadow_tp"]
    assert evaluation_key(snapshot)


def test_remaining_watch_evidence_fails_closed_on_insufficient_history():
    bars = _trend_bars("GBPJPY", "D1", count=100, step_hours=24, step=0.05)
    as_of = bars[-1].timestamp + timedelta(hours=25)
    snapshot = evaluate_remaining_watch_pair("GBPJPY", bars, as_of=as_of)

    assert snapshot["active"] is False
    assert snapshot["execution_eligible"] is False
    assert snapshot["reason"] == "INSUFFICIENT_D1_HISTORY"
    assert evaluation_key(snapshot) is None
