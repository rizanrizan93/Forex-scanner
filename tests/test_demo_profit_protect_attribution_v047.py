from fx_scanner.demo_closed_trade_reconciler import _classify_exit
from fx_scanner.demo_incremental_calibration import summarize_closed_events


def _closed_row(outcome: str, *, net: float = 0.5):
    return {
        "payload": {
            "symbol": "EURUSD",
            "setup_type": "TREND_CONTINUATION",
            "entry_mode": "HL_PULLBACK",
            "confirmation": "M5_REACTION",
            "direction": "LONG",
            "entry_low": 1.1000,
            "entry_high": 1.1010,
            "planned_sl": 1.0950,
            "exit_price": 1.1040,
            "exit_type": outcome,
            "net_pnl_estimate": net,
        }
    }


def test_structural_profit_protect_overrides_generic_market_close_classification():
    outcome = _classify_exit(
        close_order=None,
        signal={"sl": 1.095, "tp2": 1.115},
        exit_price=1.104,
        gross_profit=0.75,
        partial=False,
        structural_profit_protect=True,
    )
    assert outcome == "STRUCTURAL_PROTECT_PROFIT"


def test_structural_protect_slippage_is_not_falsely_called_profit():
    assert _classify_exit(
        close_order=None,
        signal={},
        exit_price=1.099,
        gross_profit=-0.05,
        partial=False,
        structural_profit_protect=True,
    ) == "STRUCTURAL_PROTECT_LOSS"
    assert _classify_exit(
        close_order=None,
        signal={},
        exit_price=1.100,
        gross_profit=0.0,
        partial=False,
        structural_profit_protect=True,
    ) == "STRUCTURAL_PROTECT_BREAKEVEN"


def test_partial_close_is_never_relabelled_as_structural_full_exit():
    outcome = _classify_exit(
        close_order=None,
        signal={},
        exit_price=1.104,
        gross_profit=0.5,
        partial=True,
        structural_profit_protect=True,
    )
    assert outcome == "PARTIAL_CLOSE_PROFIT"


def test_structural_protect_is_system_trade_management_not_manual_close():
    summary = summarize_closed_events(
        [
            _closed_row("STRUCTURAL_PROTECT_PROFIT", net=0.7),
            _closed_row("TP_HIT", net=1.2),
            _closed_row("SL_HIT", net=-0.4),
            _closed_row("MANUAL_CLOSE_PROFIT", net=0.2),
        ]
    )
    stats = summary.overall
    assert stats.closed == 4
    assert stats.system_closed == 3
    assert stats.manual_closed == 1
    assert stats.wins == 2
    assert stats.losses == 1
    assert stats.tp_wins == 1
    assert stats.sl_losses == 1
    assert stats.protected_wins == 1
    assert stats.protected_losses == 0
    assert stats.protected_breakevens == 0


def test_structural_protect_loss_and_breakeven_have_separate_buckets():
    stats = summarize_closed_events(
        [
            _closed_row("STRUCTURAL_PROTECT_LOSS", net=-0.1),
            _closed_row("STRUCTURAL_PROTECT_BREAKEVEN", net=0.0),
        ]
    ).overall
    assert stats.system_closed == 2
    assert stats.manual_closed == 0
    assert stats.protected_losses == 1
    assert stats.protected_breakevens == 1
    assert stats.losses == 1
    assert stats.breakevens == 1
