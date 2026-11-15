from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fx_scanner.xau_decision_checklist_v1 import (
    BROKER_CONTRACT, CANDLE_CONTRACT, adx14, closed_bars,
    evaluate_checklist, structure,
)


NOW = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)


def candles(tf: str, count: int, *, direction: int = 1):
    span = {"H1": 3600, "M15": 900, "M5": 300}[tf]
    return [{
        "closed_at": (NOW - timedelta(seconds=(count-i) * span)).isoformat(),
        "open": 3900 + direction * i * .40,
        "high": 3900 + direction * i * .40 + 1,
        "low": 3900 + direction * i * .40 - 1,
        "close": 3900 + direction * i * .40 + direction * .20,
    } for i in range(count)]


def public_bars():
    return {
        "contract": CANDLE_CONTRACT,
        "symbol": "XAUUSD",
        "account_suffix": "7903",
        "source": "CTRADER_MARKET_DATA_READ_ONLY",
        "execution_authority": False,
        "execution_influence": False,
        "bars": {"H1": candles("H1", 210),
                 "M15": candles("M15", 70),
                 "M5": candles("M5", 30)},
    }


def good_macro():
    return {"attribution_quality": {
        "quality_state": "ALIGNED_CONTEXT_ONLY",
        "quality_screened_bias": "BULLISH_XAU",
    }}


def good_decision():
    return {"state": "READY_CONFIRMED", "direction": "LONG",
            "entry_band": {"low": 3981, "high": 3982},
            "structural_invalidation": 3980,
            "targets": [3987]}


def good_spec():
    return {
        "contract": BROKER_CONTRACT, "source": "CTRADER_SYMBOL_READ_ONLY",
        "symbol": "XAUUSD", "account_suffix": "7903",
        "execution_authority": False, "execution_influence": False,
        "minimum_units": 1., "minimum_margin_usd": 20.,
        "roundtrip_cost_per_unit_usd": .8,
        "observed_at": (NOW - timedelta(seconds=60)).isoformat(),
    }


def test_unknown_data_cannot_be_reported_as_satisfied():
    s = evaluate_checklist(decision=good_decision(), macro_evaluation=good_macro(),
                           candle_feed=None, now=NOW, structure_fresh=False)
    assert s["BUY"]["passed"] == 1
    assert s["BUY"]["unknown"] == 5
    assert s["BUY"]["state"] == "WAIT"
    assert s["execution_authority"] is False
    assert s["order_enabled"] is False


def test_broker_candle_timestamp_must_be_closed_and_current():
    bad = public_bars()
    bad["bars"]["M15"][-1]["closed_at"] = (NOW + timedelta(minutes=1)).isoformat()
    result, error = closed_bars(bad, "M15", NOW)
    assert not result
    assert "belum tertutup" in error
    bad["bars"]["M15"][-1]["closed_at"] = (NOW - timedelta(hours=3)).isoformat()
    result, error = closed_bars(bad, "M15", NOW)
    assert not result
    assert error


def test_adx_direction_agreement():
    sample = public_bars()
    sample_bars, err = closed_bars(sample, "M15", NOW)
    assert err is None
    value = adx14(sample_bars)
    assert value and value["adx"] >= 25
    assert value["plus"] > value["minus"]


def test_both_sides_have_separate_conditions():
    rep = evaluate_checklist(decision=good_decision(), macro_evaluation=good_macro(),
                             candle_feed=public_bars(), broker_spec=good_spec(),
                             now=NOW, structure_fresh=True)
    assert rep["BUY"]["passed"] >= 4
    assert rep["SELL"]["items"][0]["state"] == "FAIL"
    assert rep["SELL"]["items"][1]["state"] == "FAIL"
    assert rep["SELL"]["items"][2]["state"] == "FAIL"
    assert rep["SELL"]["state"] == "WAIT"


def test_macro_conflict_does_not_pass():
    rep = evaluate_checklist(decision=good_decision(),
                             macro_evaluation={"attribution_quality": {
                                 "quality_state": "WAIT_INTRADAY_CONFIRMATION",
                                 "quality_screened_bias": "BULLISH_XAU"}},
                             now=NOW, structure_fresh=False)
    assert rep["BUY"]["items"][0]["state"] == "UNKNOWN"


def test_risk_broker_missing_never_passes_even_with_good_rr():
    rep = evaluate_checklist(decision=good_decision(), macro_evaluation=good_macro(),
                             now=NOW, structure_fresh=True)
    assert rep["BUY"]["items"][-1]["state"] == "UNKNOWN"


def test_risk_invalid_sl_fails():
    bad = good_decision()
    bad["structural_invalidation"] = 3999
    rep = evaluate_checklist(decision=bad, macro_evaluation=good_macro(),
                             broker_spec=good_spec(), now=NOW, structure_fresh=True)
    assert rep["BUY"]["items"][-1]["state"] == "FAIL"


def test_expired_data_never_passes():
    old = public_bars()
    old["bars"]["H1"] = candles("H1", 210)
    for row in old["bars"]["H1"]:
        row["closed_at"] = (datetime.fromisoformat(row["closed_at"]) -
                            timedelta(days=3)).isoformat()
    rep = evaluate_checklist(decision=good_decision(), macro_evaluation=good_macro(),
                             candle_feed=old, broker_spec=good_spec(), now=NOW,
                             structure_fresh=True)
    assert rep["BUY"]["items"][1]["state"] == "UNKNOWN"


def test_unvalidated_broker_spec_never_passes():
    spec = good_spec()
    spec["account_suffix"] = "OTHER"
    rep = evaluate_checklist(decision=good_decision(), macro_evaluation=good_macro(),
                             candle_feed=public_bars(), broker_spec=spec,
                             now=NOW, structure_fresh=True)
    assert rep["BUY"]["items"][-1]["state"] == "UNKNOWN"


def test_directional_bos_check():
    data = public_bars()
    bars, error = closed_bars(data, "M5", NOW)
    assert error is None
    ok, reason = structure(bars, "BUY")
    assert ok is True
    assert "BOS" in reason
    not_ok, _ = structure(bars, "SELL")
    assert not_ok


def test_feed_requires_correct_source_and_contract():
    sample = public_bars()
    sample["source"] = "RESEARCH_PUBLIC_CSV"
    data, error = closed_bars(sample, "H1", NOW)
    assert not data
    assert error
