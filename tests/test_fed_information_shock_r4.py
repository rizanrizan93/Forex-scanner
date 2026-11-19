"""R4 official TIPS/OIS/stock shock interpretation: symmetric and fail closed."""
from scripts.replay_fed_information_shock_r4 import (
    normalize_market, classify,shock_type,RULES,
)

def row(v=1.0):
    return {
      "MP2":.03*v,"OIS1Y":.023*v,"OIS2Y":.019*v,
      "UST2Y":.04*v,"UST10Y":.022*v,
      "TIPS5Y":.025*v,"TIPS10Y":.02*v,
      "SP500":-.25*v,"SPFUT":-.24*v,"DXY":.22*v,
    }

def test_official_interest_rates_in_pp_to_bp_and_stocks_percent():
    d=normalize_market(row())
    assert d["MP2"]==3
    assert d["TIPS10Y"]==2
    assert d["OIS1Y"]==2.3
    assert d["DXY"]==.22
    assert d["SP500"]==-.25
    assert d["IMPLIED_BREAKEVEN10_CHANGE_BP"]==.2

def test_hawkish_pure_policy_like_sell_is_symmetric_with_dovish_buy():
    up=normalize_market(row())
    down=normalize_market(row(-1))
    assert shock_type(up)=="POLICY_LIKE"
    assert shock_type(down)=="POLICY_LIKE"
    for rule in RULES:
        assert classify(up,rule)=="SELL",rule
        assert classify(down,rule)=="BUY",rule

def test_fed_information_shock_not_treated_as_pure_tightening():
    d=row();d["SP500"]=.22
    f=normalize_market(d)
    assert shock_type(f)=="INFORMATION_LIKE"
    assert classify(f,"POLICY_MP2_TIPS10_DXY_SP500_VETO").startswith("WAIT")
    assert classify(f,"POLICY_MP2_UST2Y_SP500_VETO").startswith("WAIT")

def test_dovish_information_shock_not_treated_as_pure_easing():
    d=row(-1);d["SP500"]=-.2
    f=normalize_market(d)
    assert shock_type(f)=="INFORMATION_LIKE"
    assert classify(f,"POLICY_MP2_UST2Y_SP500_VETO").startswith("WAIT")

def test_missing_tips_never_substitute_nominal_yield():
    d=row();d["TIPS10Y"]=None
    f=normalize_market(d)
    assert classify(f,"MP2_TIPS10_DXY")=="WAIT_MISSING"
    assert f["IMPLIED_BREAKEVEN10_CHANGE_BP"] is None

def test_speech_no_preannouncement_shock_not_inferred():
    f=normalize_market({"MP2":None,"OIS1Y":None,"TIPS10Y":None,
                        "DXY":None,"SP500":None})
    assert shock_type(f)=="UNKNOWN_MISSING"
    assert classify(f,"MP2_ONLY")=="WAIT_MISSING"

def test_breakeven_change_negative_when_real_yield_rises_faster():
    d=row()
    d["UST10Y"]=.01
    d["TIPS10Y"]=.03
    assert normalize_market(d)["IMPLIED_BREAKEVEN10_CHANGE_BP"]==-2

def test_small_market_moves_abstain():
    f=normalize_market({k:0 for k in row()})
    assert all(classify(f,k)=="WAIT_CONFLICT_OR_TOO_SMALL" for k in RULES)
