from datetime import UTC, datetime, timedelta

import pandas as pd

from fx_scanner.research_xau_entry_tp_precision_v284 import (
    EXECUTION_AUTHORITY, MAX_ENTRY_ERROR_USD, baseline_from_v242_shards,
    metrics, quote_side_replay,
    replay_plan, walk_forward,
)
from fx_scanner.research_xau_v229_historical_v242 import price_arrays


AT = datetime(2024, 1, 2, tzinfo=UTC)


def bars(*ohlc):
    return price_arrays(pd.DataFrame([
        {"timestamp": AT + timedelta(minutes=i + 1), "open": row[0],
         "high": row[1], "low": row[2], "close": row[3]}
        for i, row in enumerate(ohlc)
    ]))


def simulate(px, direction="SHORT", entry=100.0, stop=111.0, target=80.0):
    return quote_side_replay(
        px=px, direction=direction, order_at=AT,
        expires_at=AT + timedelta(hours=1),
        entry=entry, stop=stop, target=target,
        spread_pips=40.0, slippage_pips=0.2,
    )


def test_short_quote_fill_and_tp_within_five_dollars():
    px = bars((99, 100.3, 98, 99), (99, 103, 96, 97), (97, 98, 79, 80))
    result = simulate(px)
    assert result["state"] == "TP"
    assert result["precision_5_and_tp"] is True
    assert result["max_adverse_usd"] < MAX_ENTRY_ERROR_USD
    assert result["net_r"] > 0
    assert EXECUTION_AUTHORITY is False


def test_quote_side_does_not_claim_fill_when_only_mid_touches_limit():
    px = bars((99, 100.1, 98, 99), (99, 99.9, 79, 80))
    assert simulate(px)["state"] == "MISSED"


def test_tp_after_more_than_five_dollars_adverse_is_not_precise():
    px = bars((99, 100.3, 98, 99), (99, 106, 96, 97), (97, 98, 79, 80))
    result = simulate(px)
    assert result["state"] == "TP"
    assert result["precision_5_and_tp"] is False
    assert result["max_adverse_usd"] >= 5


def test_long_quote_fill_and_stop_first_on_ambiguous_bar():
    px = bars((101, 103, 99.7, 101), (101, 121, 89, 100))
    result = simulate(px, direction="LONG", entry=100, stop=90, target=120)
    assert result["state"] == "STOP"
    assert result["reason"] == "STOP_FIRST_AMBIGUOUS"


def test_target_only_fill_candle_cannot_be_scored_as_win():
    px = bars((99, 101, 79, 99), (99, 100, 95, 98))
    result = simulate(px)
    assert result["state"] == "TIME_EXIT"
    assert result["precision_5_and_tp"] is False


def test_replay_requires_full_horizon_and_uses_only_frozen_slot_pairs():
    plan = {
        "plan_id": "P", "plan_at": AT.isoformat(),
        "signal_expires_at": (AT + timedelta(hours=1)).isoformat(),
        "direction": "SHORT", "stop": 111.0,
        "children": [
            {"slot": 1, "reference_price": 100, "planned_target": 80},
            {"slot": 2, "reference_price": 102, "planned_target": 82},
            {"slot": 3, "reference_price": 104, "planned_target": 75},
        ],
    }
    frame = pd.DataFrame([
        {"timestamp": AT + timedelta(minutes=1), "open": 99, "high": 100.3, "low": 98, "close": 99},
        {"timestamp": AT + timedelta(minutes=2), "open": 99, "high": 101, "low": 79, "close": 80},
        {"timestamp": AT + timedelta(days=31), "open": 80, "high": 81, "low": 79, "close": 80},
    ])
    assert replay_plan(plan, frame.iloc[:2])["censored"] is True
    result = replay_plan(plan, frame)
    assert set(result["pairs"]) == {"E1_T1", "E1_T2", "E2_T1", "E2_T2"}
    assert metrics([result], "E1_T1", "base")["tp_per_opportunity"] == 1.0


def test_walk_forward_uses_prior_year_and_never_favors_missed_limits():
    def outcome(state, net, precise):
        return {"state": state, "net_r": net, "precision_5_and_tp": precise}
    rows = []
    for year in (2023, 2024):
        for i in range(30):
            # Deep entry hits TP beautifully on rare fills; its miss rate is
            # unacceptable relative to the baseline, even with positive R.
            deep = outcome("MISSED", 0, False) if i < 24 else outcome("TP", 10, True)
            rows.append({
                "year": year, "mature_at": f"{year}-06-01T00:00:00+00:00",
                "censored": False,
                "pairs": {
                    "E1_T1": {mode: outcome("TP", 0.5, i < 20) for mode in ("base", "stress")},
                    "E2_T1": {mode: deep for mode in ("base", "stress")},
                },
            })
    folds = walk_forward(rows)["folds"]
    assert folds[0]["eligible"] is False
    assert folds[1]["selected_pair"] == "E1_T1"
    assert folds[1]["selected"]["base"]["fill_rate"] == 1.0


def test_v242_baseline_uses_effective_fill_and_dollar_adverse_not_r():
    plan = {"plan_id": "P", "plan_at": AT.isoformat(),
            "signal_expires_at": (AT + timedelta(hours=1)).isoformat()}
    trade = {"plan_id": "P", "year": 2024, "cost_mode": "BASE", "slot": 1,
             "state": "WIN", "reason": "TARGET_HIT", "mae_r": 0.5,
             "risk_pips": 1200.0, "entry_at": (AT + timedelta(minutes=5)).isoformat()}
    report = baseline_from_v242_shards([{"year": 2024, "price_end": "2025-02-01",
                                         "plans": [plan], "trades": [trade]}])
    cell = report["eras"]["2019_2024"]["L1"]
    assert cell["filled"] == cell["tp"] == 1
    assert cell["tp_with_adverse_at_most_5_usd"] == 0  # 0.5 R = $6


def test_missing_structural_target_is_no_order_opportunity():
    plan = {
        "plan_id": "NO_TP", "plan_at": AT.isoformat(),
        "signal_expires_at": (AT + timedelta(hours=1)).isoformat(),
        "direction": "SHORT", "stop": 111,
        "children": [{"slot": 1, "reference_price": 100, "planned_target": None}],
    }
    frame = pd.DataFrame([
        {"timestamp": AT + timedelta(minutes=1), "open": 99, "high": 101, "low": 98, "close": 99},
        {"timestamp": AT + timedelta(days=31), "open": 99, "high": 100, "low": 98, "close": 99},
    ])
    result = replay_plan(plan, frame)
    assert set(result["pairs"]) == {"E1_T1", "E1_T2", "E2_T1", "E2_T2"}
    assert result["pairs"]["E1_T1"]["base"]["reason"] == "NO_VALID_STRUCTURAL_PAIR"
    assert metrics([result], "E1_T1", "base")["joint_success_per_opportunity"] == 0
