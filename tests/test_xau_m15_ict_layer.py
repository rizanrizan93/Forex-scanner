from datetime import datetime, timedelta, timezone

from fx_scanner.demo_xau_m15_ict_layer import (
    ICT_LAYER_CONTRACT,
    evaluate_ict_execution_context,
)
from fx_scanner.models import Bar

UTC = timezone.utc


def _bar(index: int, *, start: datetime, open_: float, high: float, low: float, close: float) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=start + timedelta(minutes=15 * index),
        open=open_,
        high=high,
        low=low,
        close=close,
        tick_count=200 + index,
        spread_avg=0.20,
        spread_max=0.35,
    )


def _long_ict_bundle() -> tuple[tuple[Bar, ...], datetime]:
    start = datetime(2026, 9, 15, 0, 0, tzinfo=UTC)
    rows = [
        _bar(i, start=start, open_=100.0, high=101.0, low=99.0, close=100.1)
        for i in range(249)
    ]

    # Establish a broad dealing range outside the entry-pattern lookback.
    rows[-20] = _bar(229, start=start, open_=100.0, high=110.0, low=90.0, close=100.0)

    # Bullish ICT entry sequence: last bearish order block -> displacement/FVG
    # -> later retracement into the OB/FVG while price is in discount.
    rows[-10] = _bar(239, start=start, open_=99.0, high=99.2, low=96.5, close=97.0)
    rows[-9] = _bar(240, start=start, open_=97.0, high=101.0, low=97.0, close=100.5)
    rows[-8] = _bar(241, start=start, open_=101.0, high=102.0, low=100.0, close=101.5)
    for offset in range(-7, -1):
        index = len(rows) + offset
        rows[offset] = _bar(index, start=start, open_=101.0, high=102.5, low=99.0, close=101.1)
    rows[-1] = _bar(248, start=start, open_=100.2, high=100.8, low=98.5, close=99.6)

    as_of = rows[-1].timestamp + timedelta(minutes=15)
    return tuple(rows), as_of


def test_ict_layer_accepts_discount_ob_fvg_retest_with_external_target():
    rows, as_of = _long_ict_bundle()
    context = evaluate_ict_execution_context(
        rows,
        direction="LONG",
        atr_value=2.0,
        as_of=as_of,
    )

    assert context.contract == ICT_LAYER_CONTRACT
    assert context.available is True
    assert context.previous_day_high is not None
    assert context.previous_day_low is not None
    assert context.premium_discount_ok is True
    assert context.order_block_retest is True
    assert context.fvg_retest is True
    assert context.confluence_count >= 2
    assert context.external_liquidity_target is not None
    assert context.anti_chase_ok is True
    assert context.execution_ready is True
    assert context.reasons == ()


def test_ict_layer_blocks_premium_chase_for_long_even_with_history():
    rows, as_of = _long_ict_bundle()
    changed = list(rows)
    last = changed[-1]
    changed[-1] = _bar(
        len(changed) - 1,
        start=rows[0].timestamp,
        open_=108.0,
        high=109.5,
        low=107.5,
        close=109.0,
    )
    context = evaluate_ict_execution_context(
        tuple(changed),
        direction="LONG",
        atr_value=2.0,
        as_of=as_of,
    )

    assert context.execution_ready is False
    assert "ICT_ANTI_CHASE_BLOCK" in context.reasons


def test_ict_layer_fails_closed_on_invalid_direction_or_atr():
    rows, as_of = _long_ict_bundle()
    bad_direction = evaluate_ict_execution_context(
        rows,
        direction="FLAT",
        atr_value=2.0,
        as_of=as_of,
    )
    bad_atr = evaluate_ict_execution_context(
        rows,
        direction="LONG",
        atr_value=0.0,
        as_of=as_of,
    )

    assert bad_direction.execution_ready is False
    assert bad_atr.execution_ready is False
    assert bad_direction.reasons == ("INVALID_DIRECTION_OR_ATR",)
    assert bad_atr.reasons == ("INVALID_DIRECTION_OR_ATR",)
