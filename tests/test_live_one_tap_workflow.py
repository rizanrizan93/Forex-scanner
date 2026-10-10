from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ctrader-live-manual-approval.yml"
RUNNER = ROOT / "src" / "fx_scanner" / "live_manual_approval_runner.py"


def test_live_workflow_is_manual_only_and_one_ticket():
    text = WORKFLOW.read_text()
    assert "workflow_dispatch:" in text
    assert "repository_dispatch:" not in text
    assert "github.event.client_payload" not in text
    assert 'FX_LIVE_TRADING_ENABLED: "0"' in text
    assert 'FX_KILL_SWITCH: "1"' in text
    assert 'CTRADER_DEMO_AUTOTRADE_ENABLED: "0"' in text
    assert "ticket_id:" in text
    # User selection of the immutable ticket is the transaction-level approval;
    # no second typed confirmation field is exposed in workflow_dispatch inputs.
    inputs_block = text.split("permissions:", 1)[0]
    assert "confirmation:" not in inputs_block
    assert "python -m fx_scanner.live_manual_approval_runner execute" in text
    assert '--confirmation "APPROVE LIVE $RIZAN_TICKET_ID"' in text


def test_live_runner_invokes_the_real_cli():
    text = RUNNER.read_text()
    assert "approval.CTraderExecutionGateway = LiveManualCTraderExecutionGateway" in text
    assert "approval.main()" in text
    assert 'if __name__ == "__main__":' in text
    assert "main()" in text
