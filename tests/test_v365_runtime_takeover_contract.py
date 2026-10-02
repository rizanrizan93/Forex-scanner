from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_v365_runtime_identity_is_persisted_in_both_workers():
    runtime = (ROOT / "src/fx_scanner/demo_xau_dual_engine_runtime_v344.py").read_text()
    executor = (ROOT / "src/fx_scanner/demo_xau_v351_executor.py").read_text()

    assert '"git_sha": runtime_head_sha' in runtime
    assert 'os.getenv("RIZAN_RUNTIME_HEAD_SHA")' in runtime
    assert 'os.getenv("RIZAN_RUNTIME_HEAD_SHA")' in executor
    assert '"live_execution_enabled": False' in runtime
    assert '"live_execution_enabled": False' in executor


def test_v365_primary_runtime_handoff_is_api_verified_and_fail_closed():
    path = ROOT / ".github/workflows/rizan-xau-dual-engine-v344.yml"
    text = path.read_text()
    yaml.safe_load(text)

    assert 'RIZAN_RUNTIME_HEAD_SHA: ${{ github.sha }}' in text
    assert 'gh api "/repos/${GITHUB_REPOSITORY}/commits/main" --jq .sha' in text
    assert "V365_HANDOFF_FAIL_CLOSED" in text
    assert "V365_GRACEFUL_HANDOFF" in text
    assert "git fetch origin main --depth=1 >/dev/null 2>&1 || true" not in text


def test_v365_takeover_cancels_old_runtime_only_after_safe_executor_window():
    path = ROOT / ".github/workflows/rizan-xau-runtime-takeover-v365.yml"
    text = path.read_text()
    yaml.safe_load(text)

    assert "safe_executor_window" in text
    assert "ctrader_demo_xau_v351_executor" in text
    assert "V365_TAKEOVER_FAIL_CLOSED" in text
    assert "/actions/runs/${run_id}/cancel" in text
    assert "WAIT|BLOCKED|DUPLICATE_BLOCK|ORDER_NOT_ACCEPTED|ERROR_FAIL_CLOSED" in text
    assert '[ "${accepted}" != "true" ]' in text
    assert '[ "${age}" -ge 0 ] && [ "${age}" -le 25 ]' in text
    assert "/actions/workflows/${workflow}/dispatches" in text
