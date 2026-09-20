from pathlib import Path

from fx_scanner.research_xau_100usd_bootstrap_v89 import (
    ACCOUNT_LEVERAGE, COST_SCENARIO_ID, EXECUTION_INFLUENCE, FIXED_LOT,
    MAX_RISK_PCT, PLANNED_STOP_MARGIN_FLOOR_PCT, POLICY_EFFECT,
    PROMOTION_ELIGIBLE, STARTING_BALANCE_USD,
)

ROOT=Path(__file__).resolve().parents[1]

def test_v89_contract():
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert STARTING_BALANCE_USD==100.0
    assert ACCOUNT_LEVERAGE==100.0
    assert FIXED_LOT==0.01
    assert PLANNED_STOP_MARGIN_FLOOR_PCT==150.0
    assert MAX_RISK_PCT==5.0
    assert COST_SCENARIO_ID=="V24_STRESS_4675"

def test_v89_has_no_execution_or_dynamic_sizing():
    src=(ROOT/"src/fx_scanner/research_xau_100usd_bootstrap_v89.py").read_text()
    runtime=(ROOT/"src/fx_scanner/research_xau_100usd_bootstrap_v89_runtime.py").read_text()
    combined=src+"\n"+runtime
    assert "send_new_order" not in combined
    assert "claim_signal_for_execution" not in combined
    assert '"dynamic_sizing": False' in src
    assert '"calendar_era_routing": False' in src
