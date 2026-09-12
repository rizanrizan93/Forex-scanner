from datetime import datetime, timedelta, timezone

from fx_scanner.demo_five_core_soft_ema_research import (
    ALIGNED_SCORE,
    COUNTERTREND_SCORE,
    XAU_EMA_BIAS_STRATEGY_ID,
    XAU_SOFT_STRATEGY_ID,
    USDJPY_SOFT_STRATEGY_ID,
    evaluate_usdjpy_soft_ema,
    evaluate_xau_ema_bias_v3,
    evaluate_xau_soft_ema,
)
from fx_scanner.models import Bar

UTC = timezone.utc


def _bar(symbol: str, timeframe: str, ts: datetime, close: float, half_range: float) -> Bar:
    return Bar(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=ts,
        open=close,
        high=close + half_range,
        low=close - half_range,
        close=close,
        tick_count=100,
        spread_avg=0.1,
        spread_max=0.2,
    )


def _xau_below_ema_with_positive_ret60() -> tuple[Bar, ...]:
    start = datetime(2025, 1, 6, tzinfo=UTC)
    rows = []
    for i in range(140):
        rows.append(_bar("XAUUSD", "D1", start + timedelta(days=i), 3000.0 - i * 2.0, 8.0))
    for j in range(61):
        rows.append(_bar("XAUUSD", "D1", start + timedelta(days=140 + j), 2500.0 + j * 1.5, 8.0))
    rows.append(_bar("XAUUSD", "D1", start + timedelta(days=201), 2591.0, 8.0))
    return tuple(rows)


def test_xau_v2_keeps_momentum_long_comparator_below_ema200():
    rows = _xau_below_ema_with_positive_ret60()
    candidate = evaluate_xau_soft_ema(
        rows,
        as_of=rows[-1].timestamp + timedelta(minutes=10),
    )

    assert candidate.strategy_id == XAU_SOFT_STRATEGY_ID
    assert candidate.direction == "LONG"
    assert candidate.active is True
    assert candidate.ema_context == "EMA_COUNTERTREND"
    assert candidate.score == COUNTERTREND_SCORE
    assert candidate.reason == "ENTRY_WINDOW_ACTIVE_EMA_COUNTERTREND"


def test_xau_v3_uses_short_bias_when_price_is_below_ema200():
    rows = _xau_below_ema_with_positive_ret60()
    candidate = evaluate_xau_ema_bias_v3(
        rows,
        as_of=rows[-1].timestamp + timedelta(minutes=10),
    )

    assert candidate.strategy_id == XAU_EMA_BIAS_STRATEGY_ID
    assert candidate.direction == "SHORT"
    assert candidate.active is True
    assert candidate.ema_context == "EMA_BELOW_SHORT_BIAS"
    assert candidate.score == COUNTERTREND_SCORE
    assert candidate.reason == "ENTRY_WINDOW_ACTIVE_EMA_BELOW_SHORT_BIAS_MOMENTUM_DIVERGENT"


def test_xau_v3_short_gets_higher_score_when_momentum_confirms():
    start = datetime(2025, 1, 6, tzinfo=UTC)
    rows = []
    for i in range(201):
        close = 3000.0 - i * 2.0
        rows.append(_bar("XAUUSD", "D1", start + timedelta(days=i), close, 8.0))
    rows.append(_bar("XAUUSD", "D1", start + timedelta(days=201), 2590.0, 8.0))

    candidate = evaluate_xau_ema_bias_v3(
        tuple(rows),
        as_of=rows[-1].timestamp + timedelta(minutes=10),
    )

    assert candidate.direction == "SHORT"
    assert candidate.active is True
    assert candidate.ema_context == "EMA_BELOW_SHORT_BIAS"
    assert candidate.score == ALIGNED_SCORE
    assert candidate.reason.endswith("MOMENTUM_CONFIRMED")


def test_usdjpy_soft_ema_breakout_is_bidirectional_and_ema_is_context_only():
    start = datetime(2026, 1, 5, tzinfo=UTC)
    rows = []
    for i in range(170):
        rows.append(_bar("USDJPY", "H4", start + timedelta(hours=4 * i), 150.0 + i * 0.002, 0.20))
    for i in range(170, 200):
        rows.append(_bar("USDJPY", "H4", start + timedelta(hours=4 * i), 150.34 + (i - 170) * 0.001, 0.01))
    rows.append(_bar("USDJPY", "H4", start + timedelta(hours=4 * 200), 151.0, 0.02))
    rows.append(_bar("USDJPY", "H4", start + timedelta(hours=4 * 201), 151.01, 0.02))

    candidate = evaluate_usdjpy_soft_ema(
        tuple(rows),
        as_of=rows[-1].timestamp + timedelta(minutes=10),
    )

    assert candidate.strategy_id == USDJPY_SOFT_STRATEGY_ID
    assert candidate.direction == "LONG"
    assert candidate.active is True
    assert candidate.ema_context in {"EMA_ALIGNED", "EMA_COUNTERTREND"}
    assert candidate.score in {ALIGNED_SCORE, COUNTERTREND_SCORE}
