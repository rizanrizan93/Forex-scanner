from datetime import datetime, timezone

from fx_scanner.demo_outcome_normalization import normalize_adaptive_profit_lock_outcomes


UTC = timezone.utc


class DummyStore:
    pass


def test_adaptive_lock_boundary_is_breakeven_despite_float_roundoff():
    closed = ({
        "observed_at": "2026-09-09T13:16:24+00:00",
        "signal_key": "sig-1",
        "code": "SL_HIT",
        "payload": {
            "position_id": "41424199",
            "exit_type": "SL_HIT",
            "net_pnl_estimate": 0.010000000000000009,
        },
    },)
    adaptive = ({
        "observed_at": "2026-09-09T12:43:28+00:00",
        "signal_key": "sig-1",
        "accepted": True,
        "payload": {
            "position_id": "41424199",
            "execution": "ACKNOWLEDGED",
        },
    },)

    normalized = normalize_adaptive_profit_lock_outcomes(
        DummyStore(), closed, adaptive_rows=adaptive
    )

    assert normalized[0]["code"] == "ADAPTIVE_PROFIT_LOCK_BREAKEVEN"
    assert normalized[0]["payload"]["exit_type"] == "ADAPTIVE_PROFIT_LOCK_BREAKEVEN"
    assert normalized[0]["payload"]["outcome_normalized_for_calibration"] is True
    # Input evidence remains immutable.
    assert closed[0]["code"] == "SL_HIT"
