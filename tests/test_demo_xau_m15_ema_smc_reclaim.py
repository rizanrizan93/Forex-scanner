from datetime import UTC, datetime, timedelta

from fx_scanner import demo_xau_m15_ema_smc_reclaim as model
from fx_scanner.demo_xau_m15_ema_smc_reclaim import (
    SCORE_WEIGHTS,
    STRATEGY_ID,
    _adx_di,
    _ema_series,
    _score_state,
    evaluate_xau_m15_ema_smc_reclaim,
)
from fx_scanner.models import Bar
from fx_scanner.technical import (
    DisplacementSignal,
    FVGSignal,
    StructureSnapshot,
    SweepSignal,
)


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
    # A trend impulse without the complete sweep -> structure -> retracement
    # sequence must remain WATCH/NO_TRADE rather than chase the move.
    assert result.long.evidence["structure_gate"] is False
    assert result.long.active is False
    assert result.long.score <= 74.0
    assert result.execution_eligible is False
    assert result.policy_effect == "OBSERVATION_ONLY"


def test_persistent_bos_is_not_retimestamped_over_a_valid_retrace(monkeypatch):
    start = datetime(2026, 9, 18, tzinfo=UTC)
    rows = tuple(
        Bar(
            symbol="XAUUSD",
            timeframe="M15",
            timestamp=start + timedelta(minutes=15 * index),
            open=100.0,
            high=101.0,
            low=99.5,
            close=100.5,
            tick_count=100,
            spread_avg=0.2,
            spread_max=0.3,
        )
        for index in range(12)
    )

    event_index = 10

    def fake_snapshot(bars, **_kwargs):
        end = len(bars) - 1
        if end == event_index:
            return StructureSnapshot(
                trend="BULLISH",
                last_swing_high=100.0,
                last_swing_low=98.0,
                bos="BULLISH",
                mss=None,
                displacement=DisplacementSignal("BULLISH", 2.0, 1.5, 0.9, 1.2, True),
                fvg=FVGSignal("BULLISH", 100.0, 100.8, 0.8, True),
                sweep=SweepSignal("BULLISH", 99.0, 0.2, True, True),
            )
        if end == event_index + 1:
            # BOS remains true after the breakout, but this bar is the retest.
            return StructureSnapshot(
                trend="BULLISH",
                last_swing_high=100.0,
                last_swing_low=98.0,
                bos="BULLISH",
                mss=None,
                displacement=None,
                fvg=None,
                sweep=None,
            )
        return StructureSnapshot(
            trend="RANGE",
            last_swing_high=100.0,
            last_swing_low=98.0,
            bos=None,
            mss=None,
            displacement=None,
            fvg=None,
            sweep=None,
        )

    monkeypatch.setattr(model, "structure_snapshot", fake_snapshot)
    sequence = model._recent_smc_sequence(
        rows,
        direction="LONG",
        ema20_value=100.0,
        ema50_value=100.5,
        current_atr=1.0,
        window=5,
    )

    assert sequence["sweep_index"] == event_index
    assert sequence["bos_index"] == event_index
    assert sequence["displacement_index"] == event_index
    assert sequence["fvg_index"] == event_index
    assert sequence["ordered"] is True
    assert sequence["event_index"] == event_index
    assert sequence["retrace_after_event"] is True
    assert sequence["ema_retrace"] is True
    assert sequence["retracement_ok"] is True
