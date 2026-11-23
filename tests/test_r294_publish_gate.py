"""Publisher verifies R29.4 H4 BUY without turning WAIT into BUY."""
from datetime import UTC,datetime,timedelta
import pytest
import r294_frozen_h4_buy_shadow as frozen
import r294_publish_gate as pub


def sample(now,score=.56,gate=True):
    issued=now-timedelta(minutes=1)
    closed=now-timedelta(minutes=20)
    return {
        "contract":frozen.CONTRACT,"model_id":frozen.MODEL_ID,
        "source":frozen.SOURCE,"symbol":"XAUUSD","tf":"H4","side":"BUY",
        "research_only":True,"execution_authority":False,
        "execution_influence":False,"forward_validated":False,
        "generated_at":issued.isoformat(),
        "observed_at":(issued-timedelta(seconds=15)).isoformat(),
        "candle_closed_at":closed.isoformat(),
        "target_close_at":(closed+timedelta(hours=4)).isoformat(),
        "direction":"BUY" if score>=.54 and gate else "WAIT",
        "reason":"H4_BUY_FROZEN_R292_TRIGGER" if score>=.54 and gate
                 else "BELOW_THRESHOLD_OR_GATE",
        "buy_head":{
            "model":"ridge","feature_group":"broad_context",
            "threshold":.54,"gate":"trend_impulse",
            "probability":score,"gate_pass":gate,
            "triggered":score>=.54 and gate,
        },
        "provenance":{
            "status":"PASS","selected_policy":dict(frozen.POLICY),
            "validation":dict(frozen.VAL2025),
            "training_end_exclusive":"2025-01-01T00:00:00+00:00",
            "feature_columns":[f"f{i}" for i in range(50)],
            "evidence_sha256":frozen.ARTIFACT_SHA,
        },
        "historical_2026_policy":{"n":23,"correct":14},
        "historical_pooled":{"n":126,"correct":79},
    }


@pytest.mark.parametrize("score,gate,expected",[
    (.55,True,"BUY"),(.53,True,"WAIT"),(.60,False,"WAIT")
])
def test_pass_exact_side_when_candle_fresh(score,gate,expected):
    now=datetime(2026,11,23,12,20,tzinfo=UTC)
    x=sample(now,score,gate)
    assert pub.validate(x,now=now)["direction"]==expected


def test_refuse_forged_trigger_and_unvalidated_history():
    now=datetime(2026,11,23,12,20,tzinfo=UTC)
    x=sample(now)
    x["direction"]="SELL"
    with pytest.raises(ValueError,match="SIGNAL_INCONSISTENT"):
        pub.validate(x,now=now)
    x=sample(now)
    x["provenance"]["validation"]["correct"]=42
    with pytest.raises(ValueError,match="PROVENANCE"):
        pub.validate(x,now=now)


def test_refuse_expired_or_stale_or_unclosed_source():
    now=datetime(2026,11,23,12,20,tzinfo=UTC)
    x=sample(now)
    x["target_close_at"]=(now-timedelta(minutes=1)).isoformat()
    with pytest.raises(ValueError,match="STALE_OR_UNCLOSED"):
        pub.validate(x,now=now)
    x=sample(now)
    x["observed_at"]=(now-timedelta(minutes=8)).isoformat()
    with pytest.raises(ValueError,match="STALE_OR_UNCLOSED"):
        pub.validate(x,now=now)
    x=sample(now)
    x["candle_closed_at"]=(now+timedelta(minutes=5)).isoformat()
    with pytest.raises(ValueError,match="STALE_OR_UNCLOSED"):
        pub.validate(x,now=now)


def test_never_reclassify_research_into_execution_authority():
    now=datetime(2026,11,23,12,20,tzinfo=UTC)
    x=sample(now)
    x["execution_authority"]=True
    with pytest.raises(ValueError,match="CONTRACT_MISMATCH"):
        pub.validate(x,now=now)
