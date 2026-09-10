from fx_scanner.demo_incremental_calibration import summarize_closed_events


def _row(exit_type, net):
    return {
        "payload": {
            "exit_type": exit_type,
            "net_pnl_estimate": net,
            "symbol": "XAUUSD",
            "setup_type": "IMPULSE_RETEST_V2",
            "entry_mode": "FIRST_RETEST",
            "confirmation": "IMPULSE_ACCEPTED",
        }
    }


def test_adaptive_profit_lock_win_is_system_win_but_not_native_tp():
    stats = summarize_closed_events([_row("ADAPTIVE_PROFIT_LOCK_PROFIT", 0.20)]).overall
    assert stats.system_closed == 1
    assert stats.wins == 1
    assert stats.losses == 0
    assert stats.adaptive_lock_wins == 1
    assert stats.tp_wins == 0
    assert stats.sl_losses == 0
    assert stats.net_pnl == 0.20


def test_adaptive_profit_lock_loss_is_system_loss_but_not_native_sl():
    stats = summarize_closed_events([_row("ADAPTIVE_PROFIT_LOCK_LOSS", -0.20)]).overall
    assert stats.system_closed == 1
    assert stats.losses == 1
    assert stats.adaptive_lock_losses == 1
    assert stats.sl_losses == 0
    assert stats.tp_wins == 0
