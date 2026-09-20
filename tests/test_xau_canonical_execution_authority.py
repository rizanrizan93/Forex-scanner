from pathlib import Path

from fx_scanner.demo_execution_fresh_ready_handoff import (
    _ALLOWED_STRATEGIES_BY_SYMBOL,
    _XAU_CANONICAL_STRATEGY,
    _XAU_D1_TSMOM_STRATEGY,
    _XAU_SHADOW_STRATEGIES,
)
from fx_scanner.demo_xau_m15_ema_smc_reclaim import STRATEGY_ID

ROOT = Path(__file__).resolve().parents[1]


def test_xau_has_exact_canonical_and_d1_demo_execution_strategies():
    assert set(_ALLOWED_STRATEGIES_BY_SYMBOL) == {"XAUUSD"}
    allowed = _ALLOWED_STRATEGIES_BY_SYMBOL["XAUUSD"]
    assert STRATEGY_ID == _XAU_CANONICAL_STRATEGY
    assert _XAU_D1_TSMOM_STRATEGY == "D1_TSMOM_60_200"
    assert allowed == frozenset({STRATEGY_ID, _XAU_D1_TSMOM_STRATEGY})
    assert STRATEGY_ID not in _XAU_SHADOW_STRATEGIES
    assert _XAU_D1_TSMOM_STRATEGY not in _XAU_SHADOW_STRATEGIES
    assert allowed.isdisjoint(_XAU_SHADOW_STRATEGIES)


def test_shadow_xau_producers_do_not_gate_canonical_handoff():
    text = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    handoff = text.split("- name: Execute all fresh strategy-authorized DEMO signals", 1)[1]
    handoff = handoff.split("- name: Enforce pair-specific max-hold exits", 1)[0]
    assert "steps.produce_xau_d1_tsmom.outcome == 'success'" in handoff
    assert "steps.produce_xau_m15_ema_smc_reclaim.outcome == 'success'" in handoff
    assert "steps.produce_xau_v42.outcome == 'success'" not in handoff
    assert "steps.produce_xau_m15_reversal.outcome == 'success'" not in handoff
    assert "steps.produce_xau_m15_sweep_fade.outcome == 'success'" not in handoff
    assert "demo_xau_canonical_position_manager" in text


def test_broker_critical_xau_path_precedes_all_shadow_producers():
    text = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    repair = text.index("demo_existing_protection_repair")
    d1 = text.index("demo_xau_d1_tsmom_candidate_producer")
    canonical = text.index("demo_xau_m15_ema_smc_reclaim_candidate_producer")
    handoff = text.index("demo_execution_fresh_ready_handoff --limit 10")
    manager = text.index("demo_xau_canonical_position_manager")
    shadows = (
        text.index("demo_xau_expansion_v42_candidate_producer"),
        text.index("demo_xau_m15_ema_reversal_candidate_producer"),
        text.index("demo_xau_m15_liquidity_sweep_fade_candidate_producer"),
    )
    assert repair < d1 < handoff < manager
    assert repair < canonical < handoff < manager
    assert all(manager < shadow for shadow in shadows)
