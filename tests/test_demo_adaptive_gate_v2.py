from dataclasses import replace

from fx_scanner.demo_adaptive_gate_v2 import (
    CompositeAdaptiveScorePolicy,
    build_adaptive_gate_v2_policy,
)

BASE = 50.01


def _payload(*, symbol="SOLUSD", setup="TREND_CONTINUATION", direction="LONG", regime="RANGE", exit_type="SL_HIT", complete=True):
    return {
        "symbol": symbol,
        "setup_type": setup,
        "direction": direction,
        "regime": regime,
        "entry_mode": "HL_PULLBACK",
        "confirmation": "BOS",
        "exit_type": exit_type,
        "v2_feature_snapshot_complete": complete,
    }


def _row(**kwargs):
    return {"payload": _payload(**kwargs)}


def _context(signal_id="sig", **kwargs):
    payload = _payload(**kwargs)
    payload.pop("exit_type", None)
    payload.pop("v2_feature_snapshot_complete", None)
    payload["snapshot_complete_for_regime"] = True
    return {signal_id: payload}


class LegacyPolicy:
    def __init__(self, required):
        self.required = required

    def required_score(self, row):
        return self.required


def test_v2_gate_stays_disabled_below_ten_complete_wave_outcomes():
    rows = tuple(_row() for _ in range(9))
    policy = build_adaptive_gate_v2_policy(
        rows, signal_context=_context(), base_floor=BASE, enabled=True
    )
    assert policy.enabled is False
    assert policy.wave_decisive == 9
    assert policy.max_penalty == 0.0
    assert policy.root_cause == "WAVE_SAMPLE_INSUFFICIENT"


def test_snapshot_coverage_below_eighty_percent_blocks_v2_even_with_sample():
    rows = tuple(_row() for _ in range(13)) + tuple(_row(complete=False) for _ in range(4))
    policy = build_adaptive_gate_v2_policy(
        rows, signal_context=_context(), base_floor=BASE, enabled=True
    )
    assert policy.wave_decisive == 13
    assert policy.snapshot_coverage < 0.80
    assert policy.enabled is False
    assert policy.root_cause == "SNAPSHOT_COVERAGE_INSUFFICIENT"


def test_specific_symbol_setup_direction_regime_is_selected_before_parent():
    rows = (
        tuple(_row(symbol="SOLUSD", exit_type="SL_HIT") for _ in range(5))
        + tuple(_row(symbol="BTCUSD", exit_type="TP_HIT") for _ in range(5))
    )
    contexts = {}
    contexts.update(_context("sol", symbol="SOLUSD"))
    contexts.update(_context("btc", symbol="BTCUSD"))
    policy = build_adaptive_gate_v2_policy(
        rows, signal_context=contexts, base_floor=BASE, enabled=True
    )

    sol = policy.decision({"id": "sol"})
    btc = policy.decision({"id": "btc"})
    assert policy.enabled is True
    assert policy.max_penalty == 2.5
    assert sol.scope_level == "SYMBOL_SETUP_DIRECTION_REGIME"
    assert sol.scope_key.startswith("SOLUSD|")
    assert sol.penalty == 2.5
    assert sol.required_score == BASE + 2.5
    assert btc.scope_level == "SYMBOL_SETUP_DIRECTION_REGIME"
    assert btc.penalty == 0.0
    assert btc.required_score == BASE


def test_hierarchy_falls_back_when_specific_scope_has_too_little_evidence():
    rows = (
        tuple(_row(symbol="SOLUSD", exit_type="SL_HIT") for _ in range(3))
        + tuple(_row(symbol="BTCUSD", exit_type="SL_HIT") for _ in range(7))
    )
    policy = build_adaptive_gate_v2_policy(
        rows,
        signal_context=_context("sol", symbol="SOLUSD"),
        base_floor=BASE,
        enabled=True,
    )
    decision = policy.decision({"id": "sol"})
    assert decision.scope_level == "SETUP_DIRECTION_REGIME"
    assert decision.evidence_count == 10
    assert decision.penalty == 2.5


def test_twenty_outcomes_allow_at_most_five_points_and_recovering_cohort_relaxes():
    bad_rows = (
        tuple(_row(symbol="SOLUSD", exit_type="SL_HIT") for _ in range(10))
        + tuple(_row(symbol="BTCUSD", exit_type="TP_HIT") for _ in range(10))
    )
    bad_policy = build_adaptive_gate_v2_policy(
        bad_rows,
        signal_context=_context("sol", symbol="SOLUSD"),
        base_floor=BASE,
        enabled=True,
    )
    assert bad_policy.max_penalty == 5.0
    assert bad_policy.decision({"id": "sol"}).penalty == 5.0

    recovered = tuple(_row(symbol="SOLUSD", exit_type="SL_HIT") for _ in range(5)) + tuple(
        _row(symbol="SOLUSD", exit_type="TP_HIT") for _ in range(5)
    )
    recovered += tuple(_row(symbol="BTCUSD", exit_type="TP_HIT") for _ in range(10))
    recovered_policy = build_adaptive_gate_v2_policy(
        recovered,
        signal_context=_context("sol", symbol="SOLUSD"),
        base_floor=BASE,
        enabled=True,
    )
    decision = recovered_policy.decision({"id": "sol"})
    assert decision.win_rate == 0.5
    assert decision.penalty == 0.0
    assert decision.required_score == BASE


def test_current_signal_without_complete_snapshot_never_receives_v2_penalty():
    rows = tuple(_row() for _ in range(10))
    policy = build_adaptive_gate_v2_policy(
        rows, signal_context={}, base_floor=BASE, enabled=True
    )
    decision = policy.decision({"id": "missing"})
    assert policy.enabled is True
    assert decision.penalty == 0.0
    assert decision.required_score == BASE
    assert decision.reason == "CURRENT_SIGNAL_SNAPSHOT_MISSING"


def test_composite_policy_never_stacks_legacy_and_v2_penalties():
    rows = tuple(_row() for _ in range(10))
    v2 = build_adaptive_gate_v2_policy(
        rows, signal_context=_context("sig"), base_floor=BASE, enabled=True
    )
    legacy = LegacyPolicy(BASE + 5.0)
    composite = CompositeAdaptiveScorePolicy(legacy_policy=legacy, v2_policy=v2)
    # V2 active: only its +2.5 applies. Legacy +5 is not added or maxed on top.
    assert composite.required_score({"id": "sig"}) == BASE + 2.5

    disabled_v2 = replace(v2, enabled=False, root_cause="WAVE_SAMPLE_INSUFFICIENT")
    fallback = CompositeAdaptiveScorePolicy(legacy_policy=legacy, v2_policy=disabled_v2)
    assert fallback.required_score({"id": "sig"}) == BASE + 5.0


def test_policy_details_lock_risk_sltp_production_and_live_mutation_off():
    policy = build_adaptive_gate_v2_policy(
        tuple(_row() for _ in range(10)),
        signal_context=_context(),
        base_floor=BASE,
        enabled=True,
    )
    details = policy.details()
    assert details["penalty_stacking"] is False
    assert details["risk_mutation"] is False
    assert details["sl_tp_mutation"] is False
    assert details["production_mutation"] is False
    assert details["live_unlock"] is False
