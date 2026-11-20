"""Prospective shadow regression: examples are synthetic, not real trades."""
import pytest
from fx_scanner.fed_r71_forward_shadow_gate import (
    audit_forward_shadow,START_WIB,HORIZONS,CONTRACT)

MODEL="a"*40
PARAMS="b"*64
FREEZE="2026-11-21T01:00:00+07:00"


def audit(records,**kwargs):
    return audit_forward_shadow(
        records,horizon=kwargs.pop("horizon","D1"),
        frozen_model_sha=MODEL,frozen_params_sha=PARAMS,
        freeze_at=kwargs.pop("freeze_at",FREEZE),**kwargs)


def item(**changes):
    base={
        "horizon":"D1","side":"BUY",
        "frozen_model_sha":MODEL,
        "frozen_params_sha":PARAMS,
        "decision_at":"2026-11-23T12:00:00+07:00",
        "source_observed_at":"2026-11-23T11:58:00+07:00",
        "source_received_at":"2026-11-23T11:59:00+07:00",
        "outcome_at":"2026-11-24T12:00:00+07:00",
        "outcome_captured_at":"2026-11-24T12:01:00+07:00",
        "completed_trading_sessions":1,
        "entry_price":4000.0,
        "outcome_price":4015.0,
    }
    base.update(changes)
    return base


def test_empty_forward_ledger_waits_for_new_actual_market_data():
    result=audit([])
    assert result["contract"]==CONTRACT
    assert result["completed_future_records"]==0
    assert result["status"]=="WAIT_NEW_POST_FREEZE_MARKET_OUTCOMES"
    assert result["production_release_approved"] is False
    assert result["execution_authority"] is False


def test_2025_prior_known_market_data_is_permanently_rejected():
    x=item(decision_at="2025-06-02T12:00:00Z",
           source_observed_at="2025-06-02T11:58:00Z",
           source_received_at="2025-06-02T11:59:00Z",
           outcome_at="2025-06-03T12:00:00Z",
           outcome_captured_at="2025-06-03T12:01:00Z")
    result=audit([x])
    assert result["completed_future_records"]==0
    assert result["excluded_reasons"][0][1]=="REUSED_PRE_FREEZE_MARKET_HISTORY"


def test_without_completed_trading_sessions_reject_early_outcome():
    x=item(outcome_at="2026-11-23T12:05:00+07:00",
           outcome_captured_at="2026-11-23T12:06:00+07:00",
           completed_trading_sessions=0)
    result=audit([x])
    assert result["completed_future_records"]==0
    assert result["excluded_reasons"][0][1]=="HORIZON_TRADING_SESSIONS_INCOMPLETE"


def test_missing_outcome_is_pending_not_counted_win_or_loss():
    x=item(outcome_at=None,outcome_price=None,
           completed_trading_sessions=0)
    result=audit([x])
    assert result["pending_future_records"]==1
    assert result["completed_future_records"]==0
    assert result["independent_forward_accuracy_verified"] is False


def test_future_source_arrival_cannot_authorize_past_entry():
    x=item(source_received_at="2026-11-23T13:00:00+07:00")
    result=audit([x])
    assert result["excluded_reasons"][0][1]=="FUTURE_SOURCE_OR_CAPTURE_TIMESTAMP"


def test_model_sha_change_breaks_precommitted_forward_ledger():
    x=item(frozen_params_sha="0"*64)
    result=audit([x])
    assert result["excluded_reasons"][0][1]=="MODEL_REVISED_AFTER_PRECOMMITMENT"


def test_complete_provisional_outcome_never_becomes_pit_certification():
    result=audit([item()],independent_acquisition_manifest_verified=True)
    assert result["completed_future_records"]==1
    assert result["events"][0]["correct_after_hypothetical_0_40_spread"] is True
    assert result["events"][0]["original_ingestion_manifest_independently_verified"] is False
    assert result["source_capture_clocks_are_attested"] is False
    assert result["independent_forward_accuracy_verified"] is False
    assert result["min_independent_forward_evidence_met"] is False


def test_outcome_receipt_cannot_predate_outcome():
    result=audit([item(outcome_captured_at="2026-11-24T10:00:00+07:00")])
    assert result["excluded_reasons"][0][1]=="OUTCOME_CAPTURE_BEFORE_OUTCOME"


def test_future_model_start_gate_and_horizon_required():
    with pytest.raises(ValueError,match="FREEZE_BEFORE_NEW_HOLDOUT"):
        audit([],freeze_at="2026-11-20T00:00:00+07:00")
    x=item(horizon="W1",completed_trading_sessions=2)
    r=audit([x],horizon="W1")
    assert r["excluded_reasons"][0][1]=="HORIZON_TRADING_SESSIONS_INCOMPLETE"
    assert HORIZONS["Y1"]==252
