from pathlib import Path

from fx_scanner.demo_execution_fresh_ready_handoff import (
    _ALLOWED_STRATEGIES_BY_SYMBOL,
    _XAU_CANONICAL_STRATEGY,
    _XAU_SHADOW_STRATEGIES,
)
from fx_scanner.demo_xau_m15_ema_smc_reclaim import STRATEGY_ID

ROOT = Path(__file__).resolve().parents[1]


def test_xau_has_one_canonical_demo_execution_strategy():
    assert set(_ALLOWED_STRATEGIES_BY_SYMBOL) == {"XAUUSD"}
    allowed = _ALLOWED_STRATEGIES_BY_SYMBOL["XAUUSD"]
    assert STRATEGY_ID == _XAU_CANONICAL_STRATEGY
    assert allowed == frozenset({STRATEGY_ID})
    assert STRATEGY_ID not in _XAU_SHADOW_STRATEGIES
    assert allowed.isdisjoint(_XAU_SHADOW_STRATEGIES)


def test_shadow_xau_producers_do_not_gate_canonical_handoff():
    text = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    handoff = text.split("- name: Execute all fresh strategy-authorized DEMO signals", 1)[1]
    handoff = handoff.split("- name: Enforce pair-specific max-hold exits", 1)[0]
    assert "steps.produce_xau_m15_ema_smc_reclaim.outcome == 'success'" in handoff
    assert "steps.produce_xau_v42.outcome == 'success'" not in handoff
    assert "steps.produce_xau_m15_reversal.outcome == 'success'" not in handoff
    assert "steps.produce_xau_m15_sweep_fade.outcome == 'success'" not in handoff
    assert "demo_xau_canonical_position_manager" in text
