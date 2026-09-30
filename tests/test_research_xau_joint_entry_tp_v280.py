from datetime import UTC, datetime, timedelta

import pandas as pd

from fx_scanner.research_xau_joint_entry_tp_v280 import (
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    _candidates,
    replay_plan,
    walk_forward,
)


def _plan(year=2024):
    at = datetime(year, 1, 2, tzinfo=UTC)
    return {
        "plan_id": str(year), "direction": "LONG", "stop": 90.0,
        "plan_at": at.isoformat(),
        "signal_expires_at": (at + timedelta(hours=1)).isoformat(),
        "children": [
            {"slot": 1, "reference_price": 100.0, "planned_target": 120.0},
            {"slot": 2, "reference_price": 98.0, "planned_target": 116.0},
            {"slot": 3, "reference_price": 97.0, "planned_target": 140.0},
        ],
    }


def _bars(at, *, low=99.0, high=121.0):
    return pd.DataFrame([
        {"timestamp": at + timedelta(minutes=1), "open": 100.0,
         "high": high, "low": low, "close": 100.0},
        {"timestamp": at + timedelta(days=1), "open": 101.0,
         "high": high, "low": low, "close": 110.0},
        {"timestamp": at + timedelta(days=31), "open": 110.0,
         "high": high, "low": low, "close": 110.0},
    ])


def test_pair_grid_uses_only_frozen_pre_touch_structural_prices():
    pairs = _candidates(_plan())
    assert pairs == {
        "E1_T1": (100.0, 120.0), "E1_T2": (100.0, 116.0),
        "E2_T1": (98.0, 120.0), "E2_T2": (98.0, 116.0),
    }
    assert EXECUTION_INFLUENCE is False
    assert LIVE_EXECUTION_ENABLED is False


def test_replay_counts_missed_entry_as_zero_and_never_rewards_fill_bar_tp():
    plan = _plan()
    at = datetime.fromisoformat(plan["plan_at"])
    result = replay_plan(plan, _bars(at))
    assert result["pairs"]["E2_T1"]["base"]["state"] == "MISSED"
    assert result["pairs"]["E2_T1"]["base"]["net_r_per_opportunity"] == 0
    assert result["pairs"]["E1_T1"]["base"]["state"] == "WIN"
    incomplete = _bars(at).iloc[:2]
    assert replay_plan(plan, incomplete)["censored"] is True


def test_ambiguous_bar_is_stop_first_even_when_tp_is_also_touched():
    plan = _plan()
    at = datetime.fromisoformat(plan["plan_at"])
    bars = _bars(at, low=89.0, high=121.0)
    result = replay_plan(plan, bars)
    baseline = result["pairs"]["E1_T1"]["base"]
    assert baseline["state"] == "LOSS"
    assert baseline["ambiguous_bar"] is True


def test_walk_forward_never_selects_using_test_year_and_requires_common_grid():
    rows = []
    for year, e1, e2 in [(2023, -1.0, 0.5), (2024, -1.0, 0.5), (2025, 2.0, -2.0)]:
        for i in range(30):
            rows.append({
                "year": year, "plan_id": f"{year}-{i}", "censored": False,
                "mature_at": f"{year}-06-01T00:00:00+00:00",
                "pairs": {
                    key: {
                        mode: {"state": "WIN" if value > 0 else "LOSS",
                               "net_r_per_opportunity": value, "ambiguous_bar": False}
                        for mode in ("base", "stress")
                    }
                    for key, value in (("E1_T1", e1), ("E2_T1", e2))
                },
            })
    folds = walk_forward(rows)["folds"]
    assert folds[0]["eligible"] is False
    assert folds[1]["selected_pair"] == "E2_T1"
    assert folds[2]["selected_pair"] == "E2_T1"
    assert folds[2]["selected"]["stress"]["expectancy_r_per_opportunity"] == -2.0


def test_missing_pair_in_test_year_blocks_unpaired_comparison():
    def pair(value):
        return {mode: {"state": "WIN", "net_r_per_opportunity": value,
                       "ambiguous_bar": False} for mode in ("base", "stress")}
    rows = [{"year": 2023, "mature_at": "2023-06-01T00:00:00+00:00",
             "pairs": {"E1_T1": pair(0.1), "E2_T1": pair(0.5)},
             "censored": False} for _ in range(30)]
    rows += [{"year": 2024, "mature_at": "2024-06-01T00:00:00+00:00",
              "pairs": {"E1_T1": pair(0.1)}, "censored": False} for _ in range(30)]
    assert walk_forward(rows)["folds"][1]["reason"] == "INCOMPLETE_PAIRED_TEST_GRID"
