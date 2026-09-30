from datetime import UTC, datetime, timedelta

from fx_scanner.models import Bar
from fx_scanner.xau_rizan_style_path_calibration_v304 import evaluate_reference_outcome


def test_v305_v304_outcome_excludes_unclosed_m15_bar() -> None:
    available = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)
    reference = {
        "reference_id": "REF-CLOSED-BAR",
        "symbol": "XAUUSD",
        "available_from": available.isoformat(),
        "horizon_hours": 48,
        "decision_zone": {"direction": "SHORT", "low": 4200.0, "high": 4212.0},
        "key_band": {"low": 4208.0, "high": 4212.0},
        "rejection_path": {"direction": "SHORT", "destinations": []},
        "acceptance_path": {"direction": "LONG", "destinations": []},
    }
    bar = Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=available,
        open=4198.0,
        high=4205.0,
        low=4196.0,
        close=4202.0,
        tick_count=100,
        spread_avg=0.2,
        spread_max=0.3,
    )
    result = evaluate_reference_outcome(
        reference=reference,
        bars=(bar,),
        as_of=available + timedelta(minutes=10),
    )
    assert result["bars_evaluated"] == 0
    assert result["decision_zone_arrived"] is False
    assert result["branch_outcome"] == "WAIT_DECISION_ZONE_ARRIVAL"
