from pathlib import Path

import numpy as np
import pandas as pd

from fx_scanner.research_xau_changepoint_reset_router_v87 import (
    BASELINE_D1_DAYS,
    CONFIRM_CONSECUTIVE_DAYS,
    EXECUTION_INFLUENCE,
    FEATURES,
    LOOKBACK_TRADING_DAYS,
    MIN_CHANGE_SPACING_DAYS,
    MIN_COMPLETED_TRADES,
    MIN_SHOCK_FEATURES,
    MIN_TRAILING_EXPECTANCY_R,
    MIN_TRAILING_PF,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    ROBUST_Z_THRESHOLD,
    detect_change_points,
    gate_family_with_changepoint_reset,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v87_is_shadow_only_and_reuses_frozen_health_gate():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert LOOKBACK_TRADING_DAYS == 126
    assert MIN_COMPLETED_TRADES == 30
    assert MIN_TRAILING_PF == 1.10
    assert MIN_TRAILING_EXPECTANCY_R == 0.05


def test_v87_changepoint_contract_is_preregistered_and_multivariate():
    assert BASELINE_D1_DAYS == 252
    assert ROBUST_Z_THRESHOLD == 3.0
    assert MIN_SHOCK_FEATURES == 2
    assert CONFIRM_CONSECUTIVE_DAYS == 3
    assert MIN_CHANGE_SPACING_DAYS == 20
    assert FEATURES == (
        "trend60_atr",
        "ema200_distance_atr",
        "atr14_pct",
        "efficiency20",
    )


def test_v87_detector_is_causal_and_effective_after_confirmation():
    n = 330
    t = pd.date_range("2020-01-01", periods=n, freq="B", tz="UTC")
    k = np.arange(n, dtype=float)
    base1 = np.sin(k / 11.0) * 0.10
    base2 = np.cos(k / 13.0) * 0.10
    base3 = 0.01 + np.sin(k / 17.0) * 0.0002
    base4 = 0.35 + np.cos(k / 19.0) * 0.01
    # Structural shock begins only after the full prior baseline exists.
    base1[285:] += 2.0
    base2[285:] += 2.0
    frame = pd.DataFrame(
        {
            "time": t,
            "trend60_atr": base1,
            "ema200_distance_atr": base2,
            "atr14_pct": base3,
            "efficiency20": base4,
        }
    )
    points = detect_change_points(frame)
    assert points
    # The shock persists to the end of this synthetic sample, so one
    # structural shift must not generate periodic duplicate change points.
    assert len(points) == 1
    first = points[0]
    confirm = pd.Timestamp(first["confirm_at"])
    effective = pd.Timestamp(first["effective_at"])
    assert effective > confirm
    assert first["shock_feature_count"] >= 2


def test_v87_has_no_broker_execution_or_calendar_era_router():
    src = (ROOT / "src/fx_scanner/research_xau_changepoint_reset_router_v87.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_xau_changepoint_reset_router_v87_runtime.py").read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert "claim_signal_for_execution" not in combined
    assert '"detector_rearms_only_after_nonshock_state": True' in src
    assert '"year_or_era_feature_used_for_routing": False' in src
    assert '"selection_uses_future_outcomes": False' in src
    assert '"threshold_grid_search": False' in src


def test_v87_gate_accepts_serialized_change_point_timestamps():
    # Regression: persisted detector evidence stores ISO strings.
    from datetime import datetime, timedelta, timezone
    from fx_scanner.demo_donchian_adaptive_tournament import TournamentTrade

    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    trades = []
    for i in range(35):
        signal = base + timedelta(days=i + 20)
        trades.append(
            TournamentTrade(
                "TEST", "XAUUSD", "LONG",
                signal, signal, signal + timedelta(hours=1),
                i, i, 2000.0, 2001.0, 10.0,
                1990.0, 2020.0,
                0.20, 0.01, 0.19, 1, "TIME_EXIT",
            )
        )
    dates = tuple((base + timedelta(days=i)).date() for i in range(100))
    kept, payload = gate_family_with_changepoint_reset(
        trades,
        trading_dates=dates,
        change_points=(
            {
                "confirm_at": (base + timedelta(days=10)).isoformat(),
                "effective_at": (base + timedelta(days=11)).isoformat(),
            },
        ),
    )
    assert isinstance(kept, tuple)
    assert payload["change_points_seen"] == 1
