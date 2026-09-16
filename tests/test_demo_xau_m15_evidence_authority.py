from datetime import datetime, timedelta, timezone

from fx_scanner.demo_xau_m15_ema_reversal_recovery import STRATEGY_ID as EMA_STRATEGY_ID
from fx_scanner.demo_xau_m15_evidence_authority import assess_xau_m15_evidence_authority
from fx_scanner.demo_xau_m15_liquidity_sweep_fade import STRATEGY_ID as SWEEP_STRATEGY_ID
from fx_scanner.research_xau_m15_dual_strategy import RESEARCH_VERSION

UTC = timezone.utc
NOW = datetime(2026, 9, 17, 0, 0, tzinfo=UTC)


def _historical(strategy_id: str, *, passed: bool = True, age_hours: int = 1):
    evidence = {
        "strategy_id": strategy_id,
        "stage": "FORWARD_SHADOW_ELIGIBLE" if passed else "RESEARCH_ONLY",
        "development_pass": passed,
        "holdout_opened": passed,
        "holdout_pass": passed,
        "selected_max_hold_bars": 16 if passed else None,
        "reason": "UNTOUCHED_HOLDOUT_PASS" if passed else "NO_MAX_HOLD_VARIANT_PASSED_DEVELOPMENT_GATES",
    }
    return {
        "observed_at": (NOW - timedelta(hours=age_hours)).isoformat(),
        "healthy": True,
        "details": {
            "research_version": RESEARCH_VERSION,
            "decision": {"strategies": [evidence]},
        },
    }


def _forward(strategy_id: str, *, sample: int = 30, expectancy: float = 0.10, pf: float = 1.20, dd: float = 4.0, age_hours: int = 1):
    return {
        "observed_at": (NOW - timedelta(hours=age_hours)).isoformat(),
        "healthy": True,
        "details": {
            "strategy_id": strategy_id,
            "metrics": {
                "closed_trades": sample,
                "expectancy_r": expectancy,
                "profit_factor": pf,
                "max_drawdown_r": dd,
                "promotion_evidence_state": "EVIDENCE_POSITIVE_REVIEW_CANDIDATE",
            },
        },
    }


def test_missing_historical_evidence_fails_closed():
    decision = assess_xau_m15_evidence_authority(
        EMA_STRATEGY_ID,
        historical_row=None,
        forward_row=_forward(EMA_STRATEGY_ID),
        as_of=NOW,
    )
    assert decision.execution_authorized is False
    assert decision.lifecycle_stage == "SHADOW_ONLY"
    assert decision.reason == "HISTORICAL_EVIDENCE_MISSING"


def test_stale_historical_evidence_fails_closed():
    decision = assess_xau_m15_evidence_authority(
        EMA_STRATEGY_ID,
        historical_row=_historical(EMA_STRATEGY_ID, age_hours=97),
        forward_row=_forward(EMA_STRATEGY_ID),
        as_of=NOW,
    )
    assert decision.execution_authorized is False
    assert decision.reason == "HISTORICAL_EVIDENCE_STALE"


def test_failed_historical_gate_blocks_even_positive_forward_sample():
    decision = assess_xau_m15_evidence_authority(
        EMA_STRATEGY_ID,
        historical_row=_historical(EMA_STRATEGY_ID, passed=False),
        forward_row=_forward(EMA_STRATEGY_ID, sample=100, expectancy=0.5, pf=2.0),
        as_of=NOW,
    )
    assert decision.execution_authorized is False
    assert decision.lifecycle_stage == "SHADOW_ONLY"
    assert decision.reason.startswith("HISTORICAL_GATE_NOT_PASSED")


def test_historical_pass_but_forward_sample_below_30_remains_observation_only():
    decision = assess_xau_m15_evidence_authority(
        EMA_STRATEGY_ID,
        historical_row=_historical(EMA_STRATEGY_ID),
        forward_row=_forward(EMA_STRATEGY_ID, sample=29),
        as_of=NOW,
    )
    assert decision.execution_authorized is False
    assert decision.lifecycle_stage == "FORWARD_OBSERVATION"
    assert decision.forward_closed_trades == 29


def test_forward_pf_or_drawdown_failure_blocks_execution():
    decision = assess_xau_m15_evidence_authority(
        EMA_STRATEGY_ID,
        historical_row=_historical(EMA_STRATEGY_ID),
        forward_row=_forward(EMA_STRATEGY_ID, pf=1.14, dd=8.01),
        as_of=NOW,
    )
    assert decision.execution_authorized is False
    assert decision.lifecycle_stage == "FORWARD_OBSERVATION"


def test_both_evidence_gates_authorize_demo_execution_only():
    decision = assess_xau_m15_evidence_authority(
        EMA_STRATEGY_ID,
        historical_row=_historical(EMA_STRATEGY_ID),
        forward_row=_forward(EMA_STRATEGY_ID),
        as_of=NOW,
    )
    assert decision.execution_authorized is True
    assert decision.lifecycle_stage == "DEMO_EXECUTION_AUTHORIZED"
    assert decision.selected_max_hold_bars == 16
    assert decision.payload()["live_execution_enabled"] is False


def test_sweep_uses_same_preregistered_authority_contract():
    decision = assess_xau_m15_evidence_authority(
        SWEEP_STRATEGY_ID,
        historical_row=_historical(SWEEP_STRATEGY_ID),
        forward_row=_forward(SWEEP_STRATEGY_ID),
        as_of=NOW,
    )
    assert decision.execution_authorized is True
    assert decision.forward_profit_factor == 1.20
