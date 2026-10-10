"""Safety checks for research-only layering, including ambiguous M1 fills."""

import numpy as np
import pandas as pd
import pytest

from fx_scanner.distributed_layer_replay import (
    Variant,
    integer_allocation,
    opportunities,
    reversal_features,
    simulate_basket,
)


def xau_trace(side=1):
    at = pd.Timestamp("2025-01-02 12:00", tz="UTC")
    trace = pd.DataFrame(
        {
            "open": [2000.0, 1998.0, 1999.0, 1999.0, 1999.0],
            "high": [2000.1, 1998.4, 1999.2, 1999.2, 2000.0],
            "low": [1999.9, 1997.9, 1998.9, 1998.9, 1990.0],
            "close": [2000.0, 1998.3, 1999.1, 1999.1, 1991.0],
            "spread": 0.25,
            "roll": 0,
            "buy_confirm": [False, False, True, True, False],
            "sell_confirm": [False, False, True, True, False],
        },
        index=pd.date_range(at, periods=5, freq="min"),
    )
    if side == -1:
        op = 4000 - trace.open.copy()
        high, low = 4000 - trace.low.copy(), 4000 - trace.high.copy()
        trace["open"], trace["high"], trace["low"] = op, high, low
        trace["close"] = 4000 - trace.close
    trace["confirm_at"] = [
        pd.NaT,
        pd.NaT,
        at + pd.Timedelta(minutes=2),
        at + pd.Timedelta(minutes=2),
        pd.NaT,
    ]
    opportunity = {"at": at, "side": side, "atr": 1.0, "anchor": np.nan}
    return trace, opportunity


@pytest.mark.parametrize("side", [1, -1])
def test_confirmed_add_uses_current_quote_not_previous_trough(side):
    trace, opp = xau_trace(side)
    result = simulate_basket(
        trace, opp, "XAUUSD", 1000, Variant("CONFIRMED_MORE", 0.15, 1, True, True)
    )
    adds = [f for f in result["fills"] if f["stage"] > 0]
    assert len(adds) == 1  # One addition per completed confirmation.
    f = adds[0]
    at = pd.Timestamp(f["at"])
    expected = trace.loc[at, "open"] + (0.25 if side == 1 else 0) + side * 0.05
    assert f["entry"] == pytest.approx(expected)
    assert result["max_risk_percent"] <= 12.5 + 1e-9
    assert result["max_margin_percent"] <= 50 + 1e-9
    planned = sum(
        x["children"] * (side * (x["entry"] - result["stop"]) + 0.05)
        for x in result["fills"]
    )
    assert planned <= result["risk_budget"] + 1e-8


def test_invalidating_gap_cancels_unfilled_children():
    trace, opp = xau_trace()
    trace.loc[trace.index[1], ["open", "high", "low", "close"]] = [
        1990.0,
        1991.0,
        1989.0,
        1990.0,
    ]
    result = simulate_basket(trace, opp, "XAUUSD", 1000, Variant("UNIFORM", 0.25, 0))
    assert len(result["fills"]) == 1
    assert result["exit_reason"] == "STOP"
    assert result["pnl"] < -result["risk_budget"] / 4


def test_stop_first_charges_children_filled_before_intrabar_invalidation():
    trace, opp = xau_trace()
    trace.loc[trace.index[0], ["high", "low"]] = [2030.0, 1990.0]
    result = simulate_basket(trace, opp, "XAUUSD", 1000, Variant("UNIFORM", 0.25, 0))
    assert result["exit_reason"] == "STOP"
    assert len(result["fills"]) == 4
    assert result["pnl"] <= 0


def test_target_and_pending_limit_ambiguous_order_does_not_grant_extra_winner():
    trace, opp = xau_trace()
    trace.loc[trace.index[0], ["high", "low"]] = [2030.0, 1998.0]
    result = simulate_basket(trace, opp, "XAUUSD", 1000, Variant("UNIFORM", 0.25, 0))
    assert result["exit_reason"] == "TARGET"
    assert len(result["fills"]) == 1


def test_native_minimum_child_size_prevents_splitting_single_child():
    trace, opp = xau_trace()
    result = simulate_basket(
        trace, opp, "XAUUSD", 100, Variant("CONFIRMED_MORE", 0.15, 1, True, True)
    )
    assert result["baseline_children"] == result["children"] == 1
    assert len(result["fills"]) == 1


def test_reversal_features_do_not_read_future_bars():
    ix = pd.date_range("2025-01-01", periods=60 * 60, freq="min", tz="UTC")
    price = 2000 + np.sin(np.arange(len(ix)) / 17) + np.arange(len(ix)) * 0.01
    raw = pd.DataFrame(
        {"open": price, "high": price + 0.1, "low": price - 0.1, "close": price + 0.05},
        index=ix,
    )
    cutoff = ix[2500]
    before = reversal_features(raw.loc[:cutoff], "XAUUSD")
    changed = raw.copy()
    changed.loc[changed.index > cutoff] *= 10
    after = reversal_features(changed, "XAUUSD")
    pd.testing.assert_frame_equal(before, after.loc[before.index])


def test_xau_requires_original_frozen_stream_not_proxy():
    with pytest.raises(ValueError, match="ARCHIVED_SIGNALS"):
        opportunities(pd.DataFrame(), "XAUUSD")


@pytest.mark.parametrize("total", [1, 2, 3, 4, 10, 195])
@pytest.mark.parametrize("power", [0, 1, 2])
def test_integer_allocation_conserves_children(total, power):
    allocation = integer_allocation(total, power)
    assert sum(allocation) == total
    assert allocation[0] >= 1
    assert all(x >= 0 for x in allocation)


def test_full_initial_keeps_baseline_children_and_adds_inside_frozen_cap():
    trace, opp = xau_trace()
    base = simulate_basket(trace, opp, "XAUUSD", 1000, Variant("BASELINE"))
    layered = simulate_basket(
        trace,
        opp,
        "XAUUSD",
        1000,
        Variant("FULL", 0.15, 1, True, True, initial_full=True),
    )
    assert layered["fills"][0]["children"] == base["children"]
    assert layered["children"] > base["children"]
    assert layered["stop"] == base["stop"]
    assert layered["target"] == base["target"]
    assert layered["max_risk_percent"] <= 12.5
    assert layered["max_margin_percent"] <= 50
