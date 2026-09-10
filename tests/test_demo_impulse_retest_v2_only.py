from datetime import datetime, timedelta, timezone

from fx_scanner.demo_impulse_retest_v2 import (
    EXECUTION_SYMBOLS,
    TARGET_R,
    build_impulse_retest_v2_plan,
    evaluate_impulse_retest_v2,
)
from fx_scanner.models import Bar

UTC = timezone.utc


def _bar(i, o, h, l, c, symbol="XAUUSD"):
    return Bar(
        symbol=symbol,
        timeframe="M5",
        timestamp=datetime(2026, 9, 10, tzinfo=UTC) + timedelta(minutes=5 * i),
        open=o,
        high=h,
        low=l,
        close=c,
        tick_count=100,
        spread_avg=0.2,
        spread_max=0.3,
    )


def _long_fixture(symbol="XAUUSD"):
    rows = []
    price = 3500.0
    for i in range(38):
        o = price + 0.02 * i
        rows.append(_bar(i, o, o + 0.50, o - 0.50, o + 0.05, symbol))
    prior_high = max(x.high for x in rows[-12:])
    i = len(rows)
    o = prior_high - 0.20
    rows.append(_bar(i, o, prior_high + 1.30, prior_high - 0.25, prior_high + 1.15, symbol))
    impulse_close = rows[-1].close
    i += 1
    rows.append(_bar(i, impulse_close, impulse_close + 0.20, prior_high + 0.20, prior_high + 0.35, symbol))
    return rows


def test_xauusd_is_the_only_execution_symbol():
    assert EXECUTION_SYMBOLS == frozenset({"XAUUSD"})


def test_valid_first_retest_activates_xauusd_strategy_and_builds_15r_plan():
    rows = _long_fixture()
    signal = evaluate_impulse_retest_v2(rows, direction="LONG")
    assert signal.active is True
    assert signal.execution_eligible is True
    assert signal.reason == "VALID_FIRST_CONTROLLED_RETEST"
    plan = build_impulse_retest_v2_plan(signal, current_price=rows[-1].close)
    assert plan is not None
    assert plan.rr2 == TARGET_R == 1.5
    assert plan.stop_loss < plan.entry_low
    assert plan.tp2 > plan.entry_high


def test_same_pattern_on_eurusd_is_shadow_only_not_execution_eligible():
    rows = _long_fixture("EURUSD")
    signal = evaluate_impulse_retest_v2(rows, direction="LONG")
    assert signal.active is True
    assert signal.execution_eligible is False
    assert signal.reason == "SHADOW_ONLY_SYMBOL"


def test_bare_break_without_impulse_body_is_rejected():
    rows = _long_fixture()
    impulse = rows[-2]
    rows[-2] = _bar(
        len(rows) - 2,
        impulse.close - 0.05,
        impulse.high,
        impulse.low,
        impulse.close,
    )
    signal = evaluate_impulse_retest_v2(rows, direction="LONG")
    assert signal.active is False


def test_lost_acceptance_before_retest_invalidates_signal():
    rows = _long_fixture()
    signal0 = evaluate_impulse_retest_v2(rows, direction="LONG")
    assert signal0.breakout_level is not None
    impulse = rows[-2]
    bad = _bar(
        len(rows) - 1,
        impulse.close,
        impulse.close + 0.1,
        signal0.breakout_level - 0.7,
        signal0.breakout_level - 0.5,
    )
    later = _bar(
        len(rows),
        signal0.breakout_level + 0.5,
        signal0.breakout_level + 0.8,
        signal0.breakout_level + 0.2,
        signal0.breakout_level + 0.4,
    )
    signal = evaluate_impulse_retest_v2(rows[:-1] + [bad, later], direction="LONG")
    assert signal.active is False
