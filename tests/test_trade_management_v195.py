from fx_scanner.trade_management_v195 import evaluate_position, summarize_positions


def test_buy_position_r_and_target_progress():
    row = {
        "position_id": "1",
        "symbol": "XAUUSD",
        "side": "BUY",
        "volume": 1.0,
        "open_price": 4285.0,
        "current_price": 4295.0,
        "sl": 4275.0,
        "tp": 4310.0,
        "profit": 10.0,
        "swap": 0.0,
    }
    out = evaluate_position(
        row,
        reaction_target=4294.7,
        terminal_low=4300.9,
        terminal_high=4319.1,
        structure_direction="LONG",
    )
    assert out["current_r"] == 1.0
    assert out["first_target_state"] == "REACHED"
    assert out["management_state"] == "FIRST_TARGET_REACHED_REVIEW_PROTECTION"
    assert out["structure_alignment"] == "ALIGNED"
    assert out["execution_authority"] is False


def test_missing_sl_is_protection_required():
    row = {
        "position_id": "2",
        "symbol": "XAUUSD",
        "side": "SELL",
        "volume": 0.01,
        "open_price": 4300.0,
        "current_price": 4290.0,
        "sl": None,
        "tp": 4270.0,
        "profit": 10.0,
    }
    out = evaluate_position(row, structure_direction="SHORT")
    assert out["protection_state"] == "SL_MISSING_TP_PRESENT"
    assert out["management_state"] == "PROTECTION_REQUIRED"
    assert out["current_r"] is None


def test_structure_opposition_is_visible_not_auto_action():
    row = {
        "position_id": "3",
        "symbol": "XAUUSD",
        "side": "BUY",
        "volume": 0.1,
        "open_price": 100.0,
        "current_price": 101.0,
        "sl": 95.0,
        "tp": 110.0,
    }
    out = evaluate_position(row, structure_direction="SHORT")
    assert out["structure_alignment"] == "OPPOSED"
    assert out["execution_influence"] is False


def test_summary_filters_xau_and_handles_mixed_sides():
    rows = [
        {"symbol": "XAUUSD", "side": "BUY", "volume": 0.2, "open_price": 100, "profit": 2},
        {"symbol": "XAUUSD", "side": "SELL", "volume": 0.1, "open_price": 110, "profit": -1},
        {"symbol": "EURUSD", "side": "BUY", "volume": 1.0, "open_price": 1.1, "profit": 5},
    ]
    out = summarize_positions(rows)
    assert out["count"] == 2
    assert out["total_volume"] == 0.30000000000000004
    assert out["total_profit"] == 1.0
    assert out["net_side"] == "MIXED"


def test_summary_empty_xau():
    out = summarize_positions([{"symbol": "EURUSD"}])
    assert out["state"] == "NO_XAU_DEMO_POSITION"
    assert out["count"] == 0
