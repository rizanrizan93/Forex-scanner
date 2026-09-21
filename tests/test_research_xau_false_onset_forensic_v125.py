from datetime import datetime, timezone

import pandas as pd

from fx_scanner.research_xau_false_onset_forensic_v125 import (
    EXECUTION_INFLUENCE,
    NORMALIZED_FEATURES,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    TRAJECTORY_LAGS,
    _trajectory_snapshot,
)


def test_v125_is_strictly_shadow_forensic():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert TRAJECTORY_LAGS == (5, 20)
    assert "risk_price" not in NORMALIZED_FEATURES
    assert "risk_usd_001" not in NORMALIZED_FEATURES


def test_v125_trajectory_uses_only_prior_rows():
    z = timezone.utc
    rows = []
    for i in range(25):
        rows.append(
            {
                "available_at": datetime(2025, 1, i + 1, tzinfo=z),
                "state": "BULL_COMPRESSED",
                "species": "BULL_COMPRESSED",
                "raw_state": "BULL_COMPRESSED",
                "direction_state": "BULL",
                "era_score": 0.3,
                "pct_atr_ratio_252": i / 100,
                "pct_ema200_distance_atr": i / 100,
                "pct_atr14_pct": i / 100,
                "pct_range20_atr": i / 100,
                "pct_drawdown60_atr": i / 100,
                "pct_trend60_atr": i / 100,
                "pct_ret60_atr": i / 100,
            }
        )
    frame = pd.DataFrame(rows)
    snap = _trajectory_snapshot(frame, datetime(2025, 1, 21, tzinfo=z))
    assert abs(snap["d5_pct_atr14_pct"] - 0.05) < 1e-12
    assert abs(snap["d20_pct_atr14_pct"] - 0.20) < 1e-12
    assert snap["feature_available_at"].startswith("2025-01-21")
