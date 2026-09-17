from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_m15_ema_smc_reclaim import (
    SCORE_WEIGHTS,
    STRATEGY_ID,
    _adx_di,
    _ema_series,
    _score_state,
    evaluate_xau_m15_ema_smc_reclaim,
)
from fx_scanner.models import Bar


def _trend_bars(timeframe: str, count: int, *, step_minutes: int) -> tuple[Bar, ...]:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    offsets = (0.0, 1.0, 3.0, 1.0, -1.0, -2.0)
    rows: list[Bar] = []
    previous_close = 4200.0
    for index in range(count - 3):
        close = 4200.0 + 0.45 * index + offsets[index % len(offsets)]
        open_price = previous_close
        high = max(open_price, close) + 0.55
        low = min(open_price, close) - 0.55
        rows.append(
            Bar(
                symbol="XAUUSD",
                timeframe=timeframe,
                timestamp=start + timedelta(minutes=step_minutes * index),
                open=open_price,
                high=high,
                low=low,
                close=close,
                tick_count=100 + index,
                spread_avg=0.2,
                spread_max=0.3,
            )
        )
        previous_close = close

    # Finish with a clean bullish displacement/FVG sequence above prior liquidity.
    for local_index, jump in enumerate((2.0, 4.0, 7.0), start=count - 3):
        open_price = previous_close + 0.8
        close = previous_close + jump
        rows.append(
            Bar(
                symbol="XAUUSD",
                timeframe=timeframe,
                timestamp=start + timedelta(minutes=step_minutes * local_index),
                open=open_price,
                high=close + 0.15,
                low=open_price - 0.05,
                close=close,
                tick_count=400 + local_index * 2,
                spread_avg=0.2,
                spread_max=0.3,
            )
        )
        previous_close = close
    return tuple(rows)


def test_score_threshold_contract_is_exact():
    assert _score_state(64.99) == ("NO_TRADE", False)
    assert _score_state(65.0) == ("WATCH", False)
    assert _score_state(75.0) == ("VALID_SETUP", True)
    assert _score_state(85.0) == ("A_PLUS_SETUP", True)


def test_ema_and_adx_helpers_are_directional():
    values = tuple(float(index) for index in range(1, 221))
    ema20 = _ema_series(values, 20)
    ema50 = _ema_series(values, 50)
    ema200 = _ema_series(values, 200)
    assert ema20[-1] is not None
    assert ema50[-1] is not None
    assert ema200[-1] is not None
    assert float(ema20[-1]) > float(ema50[-1]) > float(ema200[-1])

    m15 = _trend_bars("M15", 230, step_minutes=15)
    adx, plus_di, minus_di, _ = _adx_di(m15)
    assert adx is not None and adx > 20.0
    assert plus_di is not None and minus_di is not None
    assert plus_di > minus_di


def test_insufficient_history_fails_closed_and_never_executes():
    m15 = _trend_bars("M15", 100, step_minutes=15)
    h1 = _trend_bars("H1", 20, step_minutes=60)
    result = evaluate_xau_m15_ema_smc_reclaim(m15, h1)
    assert result.strategy_id == STRATEGY_ID
    assert result.available is False
    assert result.state == "NO_TRADE"
    assert result.active is False
    assert result.execution_eligible is False
    assert result.policy_effect == "OBSERVATION_ONLY"


def test_bullish_ema_smc_setup_scores_long_but_remains_shadow_only():
    m15 = _trend_bars("M15", 230, step_minutes=15)
    h1 = _trend_bars("H1", 50, step_minutes=60)
    result = evaluate_xau_m15_ema_smc_reclaim(m15, h1)

    assert result.available is True
    assert result.selected_direction == "LONG"
    assert result.long is not None and result.short is not None
    assert result.long.score > result.short.score
    assert result.long.components["ema_alignment"] == SCORE_WEIGHTS["ema_alignment"]
    assert result.long.components["adx_di"] >= 8.0
    assert result.long.evidence["regime_gate"] is True
    assert result.long.evidence["structure_gate"] is True
    assert result.execution_eligible is False
    assert result.policy_effect == "OBSERVATION_ONLY"
