from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_scanner.demo_xau_strategy_latency_telemetry import STRATEGY_ACTIVATED_AT
from fx_scanner.demo_xau_v2_forward_scorecard import (
    _reliable_v2_rows,
    forward_stage,
    summarize_forward,
)

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
V2_SIGNAL = "cfcf8d12-b72e-40a3-80f4-b772df8c1c73"
OLD_SIGNAL = "687ce995-006d-4996-a123-49d36867655f"


def _signal(signal_id: str, observed_at):
    return {
        "id": signal_id,
        "observed_at": observed_at.isoformat(),
        "symbol": "XAUUSD",
        "direction": "SHORT",
        "state": "COOLDOWN",
        "final_score": 63.25,
        "setup_type": "TREND_CONTINUATION",
    }


def _closed(signal_id: str, position_id: str, net: float, observed_at):
    return {
        "observed_at": observed_at.isoformat(),
        "signal_key": signal_id,
        "code": "SL_HIT",
        "payload": {
            "signal_id": signal_id,
            "position_id": position_id,
            "symbol": "XAUUSD",
            "exit_type": "SL_HIT",
            "net_pnl_estimate": net,
            "partial_close": False,
        },
    }


def _advanced(signal_id: str, position_id: str, observed_at):
    return {
        "observed_at": observed_at.isoformat(),
        "signal_key": signal_id,
        "accepted": True,
        "payload": {
            "position_id": position_id,
            "execution": "ACKNOWLEDGED",
        },
    }


def test_forward_scorecard_excludes_pre_v2_xau_and_counts_known_adaptive_win():
    post = STRATEGY_ACTIVATED_AT + timedelta(hours=1)
    pre = STRATEGY_ACTIVATED_AT - timedelta(days=2)
    signals = {
        V2_SIGNAL: _signal(V2_SIGNAL, post),
        OLD_SIGNAL: _signal(OLD_SIGNAL, pre),
    }
    closed = (
        _closed(V2_SIGNAL, "41459318", 0.20, post + timedelta(minutes=50)),
        _closed(OLD_SIGNAL, "41392843", -8.25, pre + timedelta(minutes=30)),
    )
    adaptive = (
        _advanced(V2_SIGNAL, "41459318", post + timedelta(minutes=40)),
    )

    rows = _reliable_v2_rows(
        None,
        signals=signals,
        closed_rows=closed,
        adaptive_rows=adaptive,
    )
    assert len(rows) == 1
    assert rows[0]["signal_key"] == V2_SIGNAL
    assert rows[0]["payload"]["exit_type"] == "ADAPTIVE_PROFIT_LOCK_PROFIT"

    stats = summarize_forward(rows)
    assert stats.reliable_closed == 1
    assert stats.decisive == 1
    assert stats.wins == 1
    assert stats.losses == 0
    assert stats.adaptive_lock_wins == 1
    assert stats.net_pnl == 0.20
    assert forward_stage(stats.decisive) == "OBSERVE"


def test_forward_scorecard_stage_contract_is_bounded():
    assert forward_stage(0) == "OBSERVE"
    assert forward_stage(4) == "OBSERVE"
    assert forward_stage(5) == "SHADOW_EVALUATION"
    assert forward_stage(9) == "SHADOW_EVALUATION"
    assert forward_stage(10) == "MICRO_ACTIVATION_REVIEW_ELIGIBLE"
    assert forward_stage(19) == "MICRO_ACTIVATION_REVIEW_ELIGIBLE"
    assert forward_stage(20) == "LOCALIZED_STRATEGY_REVIEW_ELIGIBLE"


def test_forward_scorecard_remains_observation_only_and_runs_after_normalized_incremental():
    source = (ROOT / "src/fx_scanner/demo_xau_v2_forward_scorecard.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ctrader-demo-discovery-pipeline.yml").read_text(encoding="utf-8")
    assert '"automatic_strategy_mutation": False' in source
    assert '"execution_influence": False' in source
    assert "build_broker_gateway" not in source
    assert "ExecutionRouter" not in source
    assert "demo_xau_v2_forward_scorecard" in workflow
    assert workflow.index("demo_normalized_calibration_runner incremental") < workflow.index(
        "demo_xau_v2_forward_scorecard"
    )
