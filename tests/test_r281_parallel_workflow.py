"""Static safety gates for parallel R28.1 publish workflow.

No new inference model or order flow is permitted by this workflow-only fix.
"""
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/r281_direction_shadow_hourly.yml"


def test_all_four_timeframes_are_parallel_and_publish_is_atomic():
    src = WORKFLOW.read_text()
    for tf in ("1h", "4h", "1D", "1W"):
        assert f"tf: {tf}" in src
    assert "strategy:" in src and "matrix:" in src
    assert "needs: [infer]" in src
    assert "needs.infer.result == 'success'" in src
    assert "python scripts/r281_publish_shadow.py" in src
    assert "run-id: 44970328847" in src
    assert "run-id: 44901264975" in src
    assert "run-id: 44886465487" in src


def test_broker_source_and_no_live_order_authority_preserved():
    src = WORKFLOW.read_text()
    assert "research/r281-direction-inference-parity-20261123" in src
    assert "tests/test_r281_live_shadow_parity.py" in src
    assert "tests/test_r281_live_market.py" in src
    assert "tests/test_r281_publish_shadow.py" in src
    assert "git add runtime/r281-shadow-direction.json" in src
    assert "cancel-in-progress: false" in src
    assert "place_order" not in src
    assert "cBots" not in src.replace("No cBot", "")


def test_schedule_supports_first_22_minutes_after_close():
    src = WORKFLOW.read_text()
    assert "cron: '7,22,37,52 * * * 1-5'" in src
    assert "timeout-minutes: 30" in src


def test_model_trained_only_on_cache_miss_then_fast_refit_reuse():
    src = WORKFLOW.read_text()
    assert "actions/cache@v4" in src
    assert "r281-2025-parity-refit-fast-v1" in src
    assert "reconstructed-model.joblib" in src
    assert "if: steps.cache.outputs.cache-hit != 'true'" in src
    assert "if: steps.cache.outputs.cache-hit == 'true'" in src
    assert "python scripts/r281_live_shadow_parity.py" in src
    assert "python scripts/r281_fast_live_inference.py" in src
    assert "tests/test_r281_fast_live_inference.py" in src
    assert "git add runtime/r281-shadow-direction.json" in src
