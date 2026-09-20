from fx_scanner.research_xau_capital_ladder_v90 import STARTING_BALANCES,MIN_LOT,LOT_STEP,MAX_LOT,MAX_RISK_PCT,TARGET_BALANCE,POLICY_EFFECT,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE,_lot_floor
def test_v90_contract():
    assert STARTING_BALANCES==(100.0,110.0,115.0,120.0,125.0,150.0,175.0,200.0,250.0,300.0,400.0,500.0,550.0,600.0,650.0,700.0,750.0,800.0,900.0)
    assert MIN_LOT==0.01 and LOT_STEP==0.01 and MAX_LOT==0.50
    assert MAX_RISK_PCT==5.0 and TARGET_BALANCE==1000.0
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
def test_lot_floor():
    assert _lot_floor(0.009)==0.0
    assert _lot_floor(0.019)==0.01
    assert _lot_floor(0.509)==0.50
