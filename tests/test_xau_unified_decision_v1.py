from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from fx_scanner.xau_unified_decision_v1 import evaluate_unified

NOW = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)


def fixture():
    stamp = NOW.isoformat()
    technical = {
        "contract": "RIZAN_XAU_TECHNICAL_V1_READONLY", "as_of_utc": stamp,
        "execution_authority": False, "execution_influence": False,
        "direction": "BUY", "errors": [],
        "BUY": {
            "state": "SETUP_CONFIRMED",
            "items": [{"state": "PASS"} for _ in range(6)],
            "plan": {"reference_close": 3900, "invalidation": 3890,
                     "target_liquidity": 3925, "rr_before_costs": 2.5,
                     "fvg": [3898, 3901], "valid_until": stamp},
        },
        "SELL": {
            "state": "WAIT_SETUP",
            "items": [{"state": "FAIL"} for _ in range(6)],
            "plan": None,
        },
    }
    checklist = {
        "contract": "RIZAN_XAU_DECISION_CHECKLIST_V1", "as_of_utc": stamp,
        "execution_authority": False, "execution_influence": False,
        "BUY": {"state": "ALL_CONDITIONS_MET_SHADOW_ONLY",
                "items": [{"state": "PASS"} for _ in range(6)]},
        "SELL": {"state": "WAIT", "items": [{"state": "FAIL"} for _ in range(6)]},
    }
    usd = {
        "contract": "RIZAN_USD_LEAD_V1_RESEARCH_ONLY", "as_of_utc": stamp,
        "execution_authority": False, "execution_influence": False,
        "usd_direction": "DOWN_WATCH",
        "usd_down": {"status": "USD_DIRECTION_WATCH_ONLY"},
        "usd_up": {"status": "WAIT"},
    }
    yield_pressure = {
        "contract": "RIZAN_US10Y_YIELD_PRESSURE_NOWCAST_V1_READONLY",
        "as_of_utc": stamp, "execution_authority": False,
        "execution_influence": False, "yield_direction": "DOWN",
        "state": "CONCORDANT_PROXY",
    }
    return dict(technical=technical, checklist=checklist, usd=usd,
                yield_pressure=yield_pressure, now=NOW)


def test_confluence_is_read_only_and_never_native_order_evidence():
    p = evaluate_unified(**fixture())
    assert p["decision"] == "BUY"
    assert p["BUY"]["state"] == "READY_SHADOW"
    assert p["SELL"]["state"] != "READY_SHADOW"
    assert p["order_enabled"] is False
    assert p["execution_authority"] is False
    assert p["missed_order_verdict"] == "NOT_EVALUATED"
    assert p["frozen_v1_native_signal"] == "NOT_EVALUATED"


@pytest.mark.parametrize("which", ["technical", "checklist", "usd", "yield_pressure"])
def test_stale_or_wrong_contract_source_cannot_promote(which):
    data = fixture()
    data[which] = deepcopy(data[which])
    data[which]["as_of_utc"] = (NOW - timedelta(minutes=3)).isoformat()
    p = evaluate_unified(**data)
    assert p["decision"] == "WAIT"
    assert p["BUY"]["state"] == "WAIT_DATA"
    data[which]["as_of_utc"] = NOW.isoformat()
    data[which]["contract"] = "WRONG"
    assert evaluate_unified(**data)["decision"] == "WAIT"


def test_missing_live_risk_keeps_shadow_checklist_unknown():
    data = fixture()
    data["checklist"]["BUY"]["items"][-1]["state"] = "UNKNOWN"
    p = evaluate_unified(**data)
    assert p["decision"] == "WAIT"
    assert p["BUY"]["unknown"] == 1
    assert p["BUY"]["gates"][1]["state"] == "UNKNOWN"


def test_opposite_yield_or_usd_blocks_buy():
    for field in ("yield", "usd"):
        data = fixture()
        if field == "yield":
            data["yield_pressure"]["yield_direction"] = "UP"
        else:
            data["usd"]["usd_direction"] = "UP_WATCH"
            data["usd"]["usd_up"]["status"] = "USD_DIRECTION_WATCH_ONLY"
            data["usd"]["usd_down"]["status"] = "WAIT"
        p = evaluate_unified(**data)
        assert p["decision"] == "WAIT"
        assert p["BUY"]["state"] == "WAIT_CONFLICT"


def test_daily_only_usd_rates_cannot_pass_intraday_lead():
    data = fixture()
    data["usd"]["usd_down"]["status"] = "USD_DAILY_RATES_WATCH_ONLY"
    assert evaluate_unified(**data)["BUY"]["gates"][2]["state"] == "UNKNOWN"


def test_incomplete_technical_or_expired_m5_cannot_pass():
    data = fixture()
    data["technical"]["BUY"]["items"][4]["state"] = "UNKNOWN"
    data["technical"]["BUY"]["state"] = "WAIT_CANDLE"
    p = evaluate_unified(**data)
    assert p["decision"] == "WAIT"
    assert p["BUY"]["technical_plan"] is None


def test_fabricated_positive_without_plan_cannot_pass():
    data = fixture()
    data["technical"]["BUY"]["plan"] = None
    p = evaluate_unified(**data)
    assert p["decision"] == "WAIT"
    assert p["BUY"]["gates"][0]["state"] == "UNKNOWN"


def test_future_dated_and_execution_enabled_are_rejected():
    for field in ("checklist", "technical"):
        data = fixture()
        data[field]["as_of_utc"] = (NOW + timedelta(minutes=1)).isoformat()
        assert evaluate_unified(**data)["decision"] == "WAIT"
        data[field]["as_of_utc"] = NOW.isoformat()
        data[field]["execution_authority"] = True
        assert evaluate_unified(**data)["decision"] == "WAIT"
