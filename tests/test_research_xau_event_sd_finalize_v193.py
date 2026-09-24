from fx_scanner.research_xau_event_finalize_v193 import (
    _valid_sd_state as final_valid_sd_state,
    final_decision,
)
from fx_scanner.research_xau_event_sd_condition_v193_year import (
    _valid_sd_state as year_valid_sd_state,
)


def test_final_decision_is_fail_closed_until_all_gates_pass():
    assert final_decision(
        base_ready=False,
        sd_ready=True,
        parity_ready=True,
    ) == "BASE_REACTION_BACKFILL_NOT_READY"
    assert final_decision(
        base_ready=True,
        sd_ready=False,
        parity_ready=True,
    ) == "SUPPLY_DEMAND_CONDITIONING_INCOMPLETE"
    assert final_decision(
        base_ready=True,
        sd_ready=True,
        parity_ready=False,
    ) == "AWAIT_CURRENT_PARITY"
    assert final_decision(
        base_ready=True,
        sd_ready=True,
        parity_ready=True,
    ) == "TIMESTAMP_AUDIT_REQUIRED"
    assert final_decision(
        base_ready=True,
        sd_ready=True,
        parity_ready=True,
        timestamp_audit_ready=True,
    ) == "FULL_BACKFILL_RESEARCH_READY"


def test_supply_demand_state_coverage_excludes_errors_and_deferred_rows():
    for value in (
        "ATLAS_ERROR",
        "INSUFFICIENT_M15_FOR_ATLAS",
        "DEFERRED_POST_WALK_FORWARD",
        "",
    ):
        assert year_valid_sd_state(value) is False
        assert final_valid_sd_state(value) is False

    for value in (
        "ATLAS_AVAILABLE",
        "NO_ACTIVE_SUPPLY_DEMAND_ZONE",
    ):
        assert year_valid_sd_state(value) is True
        assert final_valid_sd_state(value) is True


def test_timestamp_audit_blocks_even_when_sd_and_parity_pass():
    assert final_decision(
        base_ready=True,
        sd_ready=True,
        parity_ready=True,
        timestamp_audit_ready=False,
    ) == "TIMESTAMP_AUDIT_REQUIRED"
