from copy import deepcopy

from fx_scanner.xau_weighted_opportunity_v1 import evaluate_opportunity


def sample():
    tkeys = ("h1", "location", "sweep", "mss", "fvg", "rr")
    ckeys = ("macro", "h1", "m15", "m5", "v404", "risk")
    tech = {
        "direction": "BUY", "errors": [],
        "BUY": {"state": "SETUP_CONFIRMED",
                "plan": {"reference_close": 3900, "invalidation": 3890,
                         "target_liquidity": 3925},
                "items": [{"key": k, "state": "PASS"} for k in tkeys]},
        "SELL": {"state": "WAIT_SETUP", "plan": None,
                 "items": [{"key": k, "state": "FAIL"} for k in tkeys]},
    }
    checklist = {
        "BUY": {"items": [{"key": k, "state": "PASS"} for k in ckeys]},
        "SELL": {"items": [{"key": k, "state": "FAIL"} for k in ckeys]},
    }
    unified = {
        "execution_authority": False, "order_enabled": False,
        "sources_valid": {k: True for k in ("technical", "checklist", "usd", "yield")},
        "BUY": {"gates": [{"state": "PASS"}, {"state": "PASS"},
                          {"state": "PASS"}, {"state": "PASS"}]},
        "SELL": {"gates": [{"state": "FAIL"}, {"state": "FAIL"},
                           {"state": "FAIL"}, {"state": "FAIL"}]},
    }
    return {"unified": unified, "technical": tech, "checklist": checklist}


def test_full_confluence_is_shadow_only():
    r = evaluate_opportunity(**sample())
    assert r["BUY"]["state"] == "CONFIRMED_SHADOW"
    assert r["BUY"]["score"] == 100
    assert r["BUY"]["coverage"] == 100
    assert r["preferred"] == "BUY"
    assert r["order_enabled"] is False
    assert r["missed_order_verdict"] == "NOT_EVALUATED"


def test_unknown_macro_and_legacy_zone_do_not_suppress_preparation():
    p = sample()
    p["technical"]["BUY"]["items"][-1]["state"] = "FAIL"
    p["technical"]["BUY"]["state"] = "WAIT_SETUP"
    p["technical"]["BUY"]["plan"] = None
    for g in p["unified"]["BUY"]["gates"][2:]:
        g["state"] = "UNKNOWN"
    for c in p["checklist"]["BUY"]["items"][-2:]:
        c["state"] = "UNKNOWN"
    r = evaluate_opportunity(**p)
    assert r["BUY"]["state"] == "ARMED_SHADOW"
    assert 55 <= r["BUY"]["score"] <= 65
    assert r["BUY"]["coverage"] < 100
    assert r["BUY"]["risk"] == "UNKNOWN"
    assert r["preferred"] == "BUY"


def test_stale_or_missing_candle_never_promotes_setup():
    p = sample()
    p["unified"]["sources_valid"]["technical"] = False
    r = evaluate_opportunity(**p)
    assert r["BUY"]["state"] == "WAIT_DATA"
    assert r["BUY"]["score"] <= 60
    assert r["preferred"] == "WAIT"
    p = sample()
    p["technical"]["BUY"]["state"] = "WAIT_CANDLE"
    assert evaluate_opportunity(**p)["BUY"]["state"] == "WAIT_DATA"


def test_macro_opposition_does_not_arm_an_entry():
    p = sample()
    p["unified"]["BUY"]["gates"][2]["state"] = "FAIL"
    r = evaluate_opportunity(**p)
    assert r["BUY"]["state"] == "WATCH_CONFLICT"
    assert r["preferred"] == "WAIT"


def test_invalid_risk_blocks_confirmed_and_armed():
    p = sample()
    p["checklist"]["BUY"]["items"][-1]["state"] = "FAIL"
    r = evaluate_opportunity(**p)
    assert r["BUY"]["state"] == "WAIT_RISK"
    assert r["preferred"] == "WAIT"


def test_no_source_contract_authority_can_produce_signal():
    p = sample()
    p["unified"]["execution_authority"] = True
    r = evaluate_opportunity(**p)
    assert r["BUY"]["state"] == "WAIT_DATA"
    assert r["preferred"] == "WAIT"


def test_missing_or_duplicate_keys_are_unknown_not_pass():
    p = sample()
    p["checklist"]["BUY"]["items"][1]["key"] = "m15"
    r = evaluate_opportunity(**p)
    assert r["BUY"]["coverage"] < 100
    assert r["BUY"]["state"] != "CONFIRMED_SHADOW"
