from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_challenger_runs_after_xau_discovery_as_best_effort_shadow_only():
    workflow = (ROOT / ".github/workflows/ctrader-demo-discovery-pipeline.yml").read_text(encoding="utf-8")
    producer = "python -m fx_scanner.demo_xau_technical_producer"
    challenger = "python -m fx_scanner.demo_xau_expansion_challenger"
    reconciler = "python -m fx_scanner.demo_closed_trade_reconciler"
    assert workflow.index(producer) < workflow.index(challenger) < workflow.index(reconciler)
    block = workflow[workflow.index("- name: Classify XAU expansion challenger shadow evidence"):workflow.index("- name: Reconcile cTrader closed DEMO outcomes")]
    assert "continue-on-error: true" in block
    assert "if: ${{ always() }}" in block


def test_challenger_has_no_execution_authority_or_order_path():
    source = (ROOT / "src/fx_scanner/demo_xau_expansion_challenger.py").read_text(encoding="utf-8")
    assert '"policy_effect": "OBSERVATION_ONLY"' in source
    assert '"execution_influence": False' in source
    assert "demo_fresh_ready_handoff" not in source
    assert "ExecutionRouter" not in source
    assert "build_broker_gateway" not in source
    assert 'EVENT_TYPE = "DEMO_XAU_EXPANSION_CHALLENGER_SHADOW"' in source
