from __future__ import annotations

import pytest

from fx_scanner.demo_adaptive_calibration import (
    build_adaptive_policy_from_rows,
    load_adaptive_policy,
)


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


def test_wave_aware_losses_raise_demo_floor_after_thirty_decisive_outcomes():
    rows = [_row("TP_HIT") for _ in range(6)] + [_row("SL_HIT") for _ in range(24)]

    policy = build_adaptive_policy_from_rows(rows, base_floor=50.01, enabled=True)

    assert policy.wave_stats.decisive_system == 30
    assert policy.global_penalty == pytest.approx(4.29)
    assert policy.root_cause == "WAVE_WIN_RATE_BELOW_TARGET"
    assert policy.details()["score_floor_promotion_stage"] == "PROMOTED_BOUNDED"
    assert policy.required_score({"symbol": "EURUSD", "setup_type": "ICT_PULLBACK", "direction": "LONG"}) == pytest.approx(54.30)


def test_good_wave_aware_performance_does_not_raise_floor():
    rows = [_row("TP_HIT") for _ in range(21)] + [_row("SL_HIT") for _ in range(9)]

    policy = build_adaptive_policy_from_rows(rows, base_floor=50.01, enabled=True)

    assert policy.wave_stats.win_rate == pytest.approx(0.7)
    assert policy.global_penalty == 0.0
    assert policy.root_cause == "NO_ADAPTIVE_PENALTY_REQUIRED"
    assert policy.required_score({"symbol": "EURUSD", "setup_type": "ICT_PULLBACK", "direction": "LONG"}) == pytest.approx(50.01)


def test_pair_specific_penalty_can_apply_without_broad_penalty():
    rows = []
    rows += [_row("TP_HIT", symbol="EURUSD") for _ in range(6)]
    rows += [_row("SL_HIT", symbol="EURUSD") for _ in range(24)]
    rows += [_row("TP_HIT", symbol="GBPUSD") for _ in range(24)]
    rows += [_row("SL_HIT", symbol="GBPUSD") for _ in range(6)]

    policy = build_adaptive_policy_from_rows(rows, base_floor=50.01, enabled=True)

    assert policy.wave_stats.decisive_system == 60
    assert policy.global_penalty == 0.0
    assert policy.symbol_penalties["EURUSD"] == pytest.approx(4.29)
    assert "GBPUSD" not in policy.symbol_penalties
    assert policy.required_score({"symbol": "EURUSD", "setup_type": "ICT_PULLBACK", "direction": "LONG"}) == pytest.approx(54.30)
    assert policy.required_score({"symbol": "GBPUSD", "setup_type": "ICT_PULLBACK", "direction": "LONG"}) == pytest.approx(50.01)


def test_feature_gate_disables_mutation_but_keeps_diagnostics():
    rows = [_row("TP_HIT") for _ in range(2)] + [_row("SL_HIT") for _ in range(8)]

    policy = build_adaptive_policy_from_rows(rows, base_floor=50.01, enabled=False)

    assert policy.wave_stats.decisive_system == 10
    assert policy.enabled is False
    assert policy.global_penalty == 0.0
    assert policy.required_score({"symbol": "EURUSD", "setup_type": "ICT_PULLBACK", "direction": "LONG"}) == pytest.approx(50.01)


class _Response:
    def __init__(self, data):
        self.data = data


class _ClosedQuery:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def select(self, *_args):
        return self

    def eq(self, column, value):
        self.calls.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self.calls.append(("in", column, tuple(values)))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        return _Response(self.rows)


class _Client:
    def __init__(self, query):
        self.query = query

    def table(self, name):
        assert name == "broker_order_events"
        return self.query


class _Store:
    def __init__(self, query):
        self.client = _Client(query)


def test_policy_loader_scopes_closed_rows_to_both_aliases_and_enriches_geometry(
    monkeypatch,
):
    import fx_scanner.demo_adaptive_calibration_v2_runtime as context

    query = _ClosedQuery(
        [{"signal_key": "signal-1", "payload": {"exit_type": "SL_HIT"}}]
    )
    store = _Store(query)
    monkeypatch.setattr(
        context,
        "_account_ids",
        lambda _store: ("configured-alias", "native-account"),
    )
    monkeypatch.setattr(
        context,
        "_geometry_context",
        lambda _store, *, account_ids: {
            "signal-1": {
                "entry_mode": "LH_PULLBACK",
                "confirmation": "M5_STRUCTURE_BREAK",
            }
        },
    )

    policy = load_adaptive_policy(
        store,
        account_id="configured-alias",
        base_floor=50.01,
        enabled=True,
    )

    assert ("in", "account_id", ("configured-alias", "native-account")) in query.calls
    assert policy.wave_stats.decisive_system == 1
    assert policy.wave_stats.losses == 1
