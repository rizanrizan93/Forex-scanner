from fx_scanner.demo_storage_guard import (
    ABSOLUTE_CEILING_MIB,
    CRITICAL_MIB,
    _result_payload,
)


def test_storage_guard_threshold_contract():
    assert ABSOLUTE_CEILING_MIB == 500.0
    assert CRITICAL_MIB == 475.0
    assert CRITICAL_MIB < ABSOLUTE_CEILING_MIB


def test_storage_guard_result_payload_accepts_rpc_shapes():
    assert _result_payload({"mode": "NORMAL"}) == {"mode": "NORMAL"}
    assert _result_payload([{"mode": "WATCH"}]) == {"mode": "WATCH"}
    assert _result_payload([]) == {}
    assert _result_payload(None) == {}
