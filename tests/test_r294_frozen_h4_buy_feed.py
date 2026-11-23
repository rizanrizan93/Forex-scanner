"""R29.2 H4 frozen live-shadow packet may display BUY only with proof."""
import copy
from datetime import UTC,datetime,timedelta
import pytest
from fx_scanner.r294_frozen_h4_buy_feed import validate,CONTRACT,MODEL_ID,POLICY,ARTIFACT_SHA


def specimen(now,*,score=.56,gate=True):
    published=now-timedelta(minutes=2)
    closed=now-timedelta(minutes=25)
    return {
        "contract":CONTRACT,"model_id":MODEL_ID,"symbol":"XAUUSD",
        "source":"CTRADER_MARKET_DATA_READ_ONLY","tf":"H4","side":"BUY",
        "research_only":True,"execution_authority":False,
        "execution_influence":False,"forward_validated":False,
        "generated_at":published.isoformat(),
        "observed_at":(published-timedelta(seconds=30)).isoformat(),
        "candle_closed_at":closed.isoformat(),
        "target_close_at":(closed+timedelta(hours=4)).isoformat(),
        "direction":"BUY" if score>=.54 and gate else "WAIT",
        "reason":"H4_BUY_FROZEN_R292_TRIGGER" if score>=.54 and gate
                 else "BELOW_THRESHOLD_OR_GATE",
        "historical_pooled":{"n":126,"correct":79},
        "historical_2026_policy":{"n":23,"correct":14},
        "provenance":{
            "status":"PASS",
            "selected_policy":dict(POLICY),
            "validation":{"n":63,"correct":41},
            "training_end_exclusive":"2025-01-01T00:00:00+00:00",
            "evidence_sha256":ARTIFACT_SHA,
            "feature_columns":[f"feat{i}" for i in range(78)],
        },
        "buy_head":{
            "model":"ridge","feature_group":"broad_context",
            "threshold":.54,"gate":"trend_impulse",
            "probability":score,"gate_pass":gate,
            "triggered":bool(score>=.54 and gate),
        },
    }


@pytest.mark.parametrize("score,gate,direction,state",[
    (.55,True,"BUY","RESEARCH_SHADOW"),
    (.53,True,"WAIT","MODEL_ABSTAIN"),
    (.70,False,"WAIT","MODEL_ABSTAIN"),
])
def test_frozen_h4_buy_requires_exact_gate_and_score(score,gate,direction,state):
    now=datetime(2026,11,23,12,31,tzinfo=UTC)
    result=validate(specimen(now,score=score,gate=gate),now=now)
    assert result["direction"]==direction
    assert result["state"]==state
    assert result["execution_authority"] is False
    assert result["pooled_historical_accuracy"]==.626984
    assert result["frozen_2026_historical_accuracy"]==.608696


def test_candle_expiry_and_no_stale_direction():
    now=datetime(2026,11,23,12,31,tzinfo=UTC)
    x=specimen(now)
    x["candle_closed_at"]=(now-timedelta(hours=4)).isoformat()
    x["target_close_at"]=now.isoformat()
    out=validate(x,now=now)
    assert out["direction"]=="WAIT"
    assert out["state"]=="WAIT_DATA"
    assert out["reason"]=="TARGET_CANDLE_EXPIRED"


def test_forged_model_frozen_parity_or_execution_denied():
    now=datetime(2026,11,23,12,31,tzinfo=UTC)
    x=specimen(now)
    x["provenance"]["validation"]["correct"]=42
    with pytest.raises(ValueError,match="MODEL_PROOF_INVALID"):
        validate(x,now=now)
    x=specimen(now)
    x["execution_authority"]=True
    with pytest.raises(ValueError,match="MODEL_CONTRACT_INVALID"):
        validate(x,now=now)
    x=specimen(now,score=.52)
    x["direction"]="BUY"
    with pytest.raises(ValueError,match="SIGNAL_INCONSISTENT"):
        validate(x,now=now)


def test_exact_2026_config_not_pooled_annual_forecast():
    now=datetime(2026,11,23,12,31,tzinfo=UTC)
    x=specimen(now)
    x["provenance"]["selected_policy"]["threshold"]=.50
    with pytest.raises(ValueError,match="MODEL_PROOF_INVALID"):
        validate(x,now=now)
    x=specimen(now)
    x["historical_pooled"]["correct"]=80
    with pytest.raises(ValueError,match="BENCHMARK_MISMATCH"):
        validate(x,now=now)


def test_mobile_dashboard_displays_only_research_but_no_order_authority():
    from pathlib import Path
    path=(Path(__file__).resolve().parents[1]/
          "src/fx_scanner/frozen_direction_research_dashboard.py")
    s=path.read_text()
    assert "render_h4_buy(st,r294,wib)" in s
    assert "read_r294.clear()" in s
    assert 'pd.Timestamp(r294["target"])' in s
    assert "r294.get(\"target\")" in s
