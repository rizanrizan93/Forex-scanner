from datetime import datetime, timezone

from fx_scanner.research_xau_v47_gvz_implied_vol_v75 import (
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    GVZ_LOOKBACK,
    GVZ_STATES,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    REQUIRED_COSTS,
    TARGET_IV_BUCKETS,
    STOP_IV_BUCKETS,
    availability_timestamp,
    build_gvz_context,
)

UTC = timezone.utc


def test_v75_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True
    assert REQUIRED_COSTS == ("LOW_1700", "V24_STRESS_4675")


def test_v75_gvz_availability_is_next_utc_day():
    source = datetime(2026, 9, 17, 0, 0, tzinfo=UTC)
    assert availability_timestamp(source).isoformat() == "2026-09-18T00:00:00+00:00"


def test_v75_gvz_quintile_warmup_is_prior_only():
    rows = [
        (
            datetime(2025, 1, 1, tzinfo=UTC) + __import__("datetime").timedelta(days=i),
            float(i + 1),
        )
        for i in range(GVZ_LOOKBACK + 1)
    ]
    frame = build_gvz_context(rows)
    assert str(frame.iloc[GVZ_LOOKBACK - 1]["gvz_state"]) == "UNAVAILABLE"
    assert str(frame.iloc[GVZ_LOOKBACK]["gvz_state"]) == "Q5_HIGH"


def test_v75_frozen_bucket_contracts():
    assert GVZ_STATES == ("Q1_LOW", "Q2", "Q3", "Q4", "Q5_HIGH", "UNAVAILABLE")
    assert STOP_IV_BUCKETS == (
        "LE_0_25",
        "GT_0_25_LE_0_50",
        "GT_0_50_LE_1_00",
        "GT_1_00",
        "UNAVAILABLE",
    )
    assert TARGET_IV_BUCKETS == (
        "LE_0_50",
        "GT_0_50_LE_1_00",
        "GT_1_00_LE_1_50",
        "GT_1_50",
        "UNAVAILABLE",
    )
