from pathlib import Path

from fx_scanner.research_xau_canonical_replay_v1 import (
    BE_BUFFER_R,
    H1_WINDOW,
    M15_WINDOW,
    MAX_HOLD_BARS,
)


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_replay_matches_live_history_window_contract():
    assert M15_WINDOW == 240
    assert H1_WINDOW == 60
    assert MAX_HOLD_BARS == 64
    assert BE_BUFFER_R == 0.03


def test_canonical_replay_is_research_only_and_uses_current_authority_modules():
    source = (ROOT / "src/fx_scanner/research_xau_canonical_replay_v1.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_xau_canonical_replay_v1_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-canonical-replay-v1.yml").read_text()

    assert "evaluate_xau_m15_ema_smc_reclaim_execution" in source
    assert "build_xau_m15_ema_smc_reclaim_plan" in source
    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert '"execution_influence": False' in source
    assert "HISTORY_BARS = 50_000" in runtime
    assert "pull_request:" in workflow
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow
