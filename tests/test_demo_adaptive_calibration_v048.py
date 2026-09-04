from __future__ import annotations

import pytest

from fx_scanner.demo_adaptive_calibration import build_adaptive_policy_from_rows


def _row(
    exit_type: str,
    *,
    entry_mode: str = "HL_PULLBACK",
    symbol: str = "EURUSD",
    setup: str = "ICT_PULLBACK",
    direction: str = "LONG",
):
    return {
        "payload": {
            "exit_type": exit_type,
            "entry_mode": entry_mode,
            "symbol": symbol,
            "setup_type": setup,
            "direction": direction,
            "net_pnl_estimate": 1.0 if exit_type == "TP_HIT" else -1.0,
        }
    }


def test_legacy_losses_do_not_mutate_wave_aware_policy():
    rows = [_row("TP_HIT", entry_mode="LEGACY")]
    rows += [_row("SL_HIT", entry_mode="LEGACY") for _ in range(9)]

    policy = build_adaptive_policy_from_rows(rows, base_floor=50.01, enabled=True)

    assert policy.legacy_stats.decisive_system == 10
    assert policy.legacy_stats.losses == 9
    assert policy.wave_stats.decisive_system == 0
    assert policy.global_penalty == 0.0
    assert policy.root_cause == "LEGACY_LOSS_DOMINANT"
    assert policy.required_score({"symbol": "EURUSD", "setup_type": "ICT_PULLBACK", "direction": "LONG"}) == pytest.approx(50.01)


def test_wave_aware_losses_raise_demo_floor_after_ten_decisive_outcomes():
    rows = [_row("TP_HIT") for _ in range(2)] + [_row("SL_HIT") for _ in range(8)]

    policy = build_adaptive_policy_from_rows(rows, base_floor=50.01, enabled=True)

    assert policy.wave_stats.decisive_system == 10
    assert policy.global_penalty == pytest.approx(2.5)
    assert policy.root_cause == "WAVE_WIN_RATE_BELOW_TARGET"
    assert policy.required_score({"symbol": "EURUSD", "setup_type": "ICT_PULLBACK", "direction": "LONG"}) == pytest.approx(52.51)


def test_good_wave_aware_performance_does_not_raise_floor():
    rows = [_row("TP_HIT") for _ in range(7)] + [_row("SL_HIT") for _ in range(3)]

    policy = build_adaptive_policy_from_rows(rows, base_floor=50.01, enabled=True)

    assert policy.wave_stats.win_rate == pytest.approx(0.7)
    assert policy.global_penalty == 0.0
    assert policy.root_cause == "NO_ADAPTIVE_PENALTY_REQUIRED"
    assert policy.required_score({"symbol": "EURUSD", "setup_type": "ICT_PULLBACK", "direction": "LONG"}) == pytest.approx(50.01)


def test_pair_specific_penalty_can_apply_without_broad_penalty():
    rows = []
    rows += [_row("TP_HIT", symbol="EURUSD") for _ in range(2)]
    rows += [_row("SL_HIT", symbol="EURUSD") for _ in range(8)]
    rows += [_row("TP_HIT", symbol="GBPUSD") for _ in range(8)]
    rows += [_row("SL_HIT", symbol="GBPUSD") for _ in range(2)]

    policy = build_adaptive_policy_from_rows(rows, base_floor=50.01, enabled=True)

    assert policy.wave_stats.decisive_system == 20
    assert policy.global_penalty == 0.0
    assert policy.symbol_penalties["EURUSD"] == pytest.approx(2.5)
    assert "GBPUSD" not in policy.symbol_penalties
    assert policy.required_score({"symbol": "EURUSD", "setup_type": "ICT_PULLBACK", "direction": "LONG"}) == pytest.approx(52.51)
    assert policy.required_score({"symbol": "GBPUSD", "setup_type": "ICT_PULLBACK", "direction": "LONG"}) == pytest.approx(50.01)


def test_feature_gate_disables_mutation_but_keeps_diagnostics():
    rows = [_row("TP_HIT") for _ in range(2)] + [_row("SL_HIT") for _ in range(8)]

    policy = build_adaptive_policy_from_rows(rows, base_floor=50.01, enabled=False)

    assert policy.wave_stats.decisive_system == 10
    assert policy.enabled is False
    assert policy.global_penalty == 0.0
    assert policy.required_score({"symbol": "EURUSD", "setup_type": "ICT_PULLBACK", "direction": "LONG"}) == pytest.approx(50.01)
