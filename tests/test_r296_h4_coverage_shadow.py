"""R29.6 frozen R29.1 H4 BUY two-lane research guards."""
from datetime import UTC,datetime,timedelta
from pathlib import Path
import copy
import pytest

import r296_h4_coverage_live_shadow as core
import r296_publish_gate as pub


def fake(now):
    closed=now-timedelta(minutes=20)
    q={
       "contract":core.CONTRACT,"model_id":core.MODEL_ID,
       "symbol":"XAUUSD","tf":"H4","side":"BUY",
       "source":core.SOURCE,"research_only":True,
       "execution_authority":False,"execution_influence":False,
       "forward_validated":False,
       "generated_at":(now-timedelta(minutes=1)).isoformat(),
       "observed_at":(now-timedelta(minutes=1,seconds=10)).isoformat(),
       "candle_closed_at":closed.isoformat(),
       "target_close_at":(closed+timedelta(hours=4)).isoformat(),
       "historical_pooled":{"n":332,"correct":199},
       "lanes":{}
    }
    for i,(name,policy) in enumerate(pub.POLICIES.items()):
       score=.61 if i==0 else .48
       active=score>=policy["threshold"]
       q["lanes"][name]={
         "policy":policy,"score":score,"gate_pass":True,
         "triggered":active,"direction":"BUY" if active else "WAIT",
         "reason":"FROZEN_H4_BUY_TRIGGER" if active else "FROZEN_GATE_OR_SCORE_NOT_MET",
         "proof":{
           "status":"PASS","policy":policy,"source_json_sha256":core.SOURCE_SHA,
           "validation":pub.VAL[name],
           "original_evaluation":pub.EVAL[name],
           "feature_columns":[f"x{j}" for j in range(32)],
           "year_policy":2025 if i==0 else 2026,
         }
       }
    return q


def test_original_annual_freeze_from_immutable_artifact():
    lock=core.locked()
    assert lock["historical_pooled"]["correct"]==199
    assert lock["historical_pooled"]["n"]==332
    assert lock["annual_policies"]["2026"]["policy"]==pub.POLICIES["ORIGINAL_2026_SELECTION"]
    assert lock["annual_policies"]["2025"]["policy"]==pub.POLICIES["HIGH_COVERAGE_2025_CARRY"]
    assert lock["annual_policies"]["2026"]["evaluation"]["n"]==13


def test_publish_allows_high_coverage_trigger_without_forging_other_side():
    now=datetime(2026,11,23,12,51,tzinfo=UTC)
    x=pub.validate(fake(now),now=now)
    assert x["lanes"]["HIGH_COVERAGE_2025_CARRY"]["direction"]=="BUY"
    assert x["lanes"]["ORIGINAL_2026_SELECTION"]["direction"]=="WAIT"
    assert x["execution_authority"] is False


def test_publish_rejects_false_buy_and_broker_stale():
    now=datetime(2026,11,23,12,51,tzinfo=UTC)
    x=fake(now)
    x["lanes"]["ORIGINAL_2026_SELECTION"]["direction"]="BUY"
    with pytest.raises(ValueError,match="FORGED_DIRECTION"):
        pub.validate(x,now=now)
    x=fake(now)
    x["target_close_at"]=now.isoformat()
    with pytest.raises(ValueError,match="CANDLE_STALE"):
        pub.validate(x,now=now)
    x=fake(now)
    x["observed_at"]=(now-timedelta(minutes=9)).isoformat()
    with pytest.raises(ValueError,match="CANDLE_STALE"):
        pub.validate(x,now=now)


def test_cannot_write_to_cbot_or_live_order_endpoint():
    source=(Path(__file__).resolve().parents[1]/
            "scripts/r296_h4_coverage_live_shadow.py").read_text()
    for token in ("place_order(","execute_market_order(","modify_position(",
                  "bridge/order","streamlit","git push"):
        assert token not in source
    assert "2025 carry" in source.lower() or "2025 high" in source.lower()
