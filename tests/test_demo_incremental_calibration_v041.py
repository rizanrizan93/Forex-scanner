from fx_scanner.demo_incremental_calibration import (
    calibration_stage,
    suggested_score_floor_penalty,
    summarize_closed_events,
)


def _row(
    *,
    symbol="EURUSD",
    setup="TREND_CONTINUATION",
    outcome="SL_HIT",
    net=-1.0,
    direction="LONG",
    entry_low=1.1000,
    entry_high=1.1010,
    stop=1.0950,
    exit_price=1.0950,
):
    return {
        "payload": {
            "symbol": symbol,
            "setup_type": setup,
            "exit_type": outcome,
            "net_pnl_estimate": net,
            "direction": direction,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "planned_sl": stop,
            "exit_price": exit_price,
        }
    }


def test_manual_close_is_reported_but_does_not_drive_system_win_rate():
    summary = summarize_closed_events(
        [
            _row(outcome="SL_HIT", net=-0.4),
            _row(outcome="TP_HIT", net=1.2, exit_price=1.1120),
            _row(outcome="MANUAL_CLOSE_PROFIT", net=0.3, exit_price=1.1040),
        ]
    )
    stats = summary.overall
    assert stats.closed == 3
    assert stats.system_closed == 2
    assert stats.manual_closed == 1
    assert stats.wins == 1
    assert stats.losses == 1
    assert stats.win_rate == 0.5
    assert round(stats.net_pnl, 6) == 1.1


def test_calibration_stays_observational_until_enough_decisive_system_exits():
    stats = summarize_closed_events([_row() for _ in range(9)]).overall
    assert calibration_stage(stats) == "SHADOW"
    assert suggested_score_floor_penalty(stats) == 0.0


def test_micro_calibration_suggestion_is_bounded_and_never_boosts():
    poor = summarize_closed_events([_row() for _ in range(10)]).overall
    assert calibration_stage(poor) == "MICRO_READY"
    assert suggested_score_floor_penalty(poor) == 2.5

    strong = summarize_closed_events(
        [_row(outcome="TP_HIT", net=1.0, exit_price=1.1120) for _ in range(10)]
    ).overall
    assert suggested_score_floor_penalty(strong) == 0.0


def test_pair_and_setup_buckets_are_kept_separate():
    summary = summarize_closed_events(
        [
            _row(symbol="EURUSD", setup="TREND_CONTINUATION", outcome="TP_HIT", net=1.0),
            _row(symbol="XAUUSD", setup="LIQUIDITY_SWEEP_REVERSAL", outcome="SL_HIT", net=-2.0),
        ]
    )
    assert set(summary.by_symbol) == {"EURUSD", "XAUUSD"}
    assert set(summary.by_setup) == {"TREND_CONTINUATION", "LIQUIDITY_SWEEP_REVERSAL"}
