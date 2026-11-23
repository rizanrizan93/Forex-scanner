"""Atomic R25/R11 SHADOW publisher rejects absent, stale or forged heads."""
from datetime import UTC,datetime,timedelta
import json
import pytest
from rbest_publish_shadow import compose,CONTRACT,REPORTS


def fixture(tmp_path,now):
    for tf,f in REPORTS.items():
        h=1 if tf=="H1" else 4
        q={
            "contract":"RIZAN_BEST_SIDE_SHADOW_V1","tf":tf,
            "research_only":True,"source":"CTRADER_MARKET_DATA_READ_ONLY",
            "execution_authority":False,"execution_influence":False,
            "generated_at":now.isoformat(),
            "observed_at":(now-timedelta(seconds=15)).isoformat(),
            "candle_closed_at":(now-timedelta(minutes=10)).isoformat(),
            "target_close_at":(now-timedelta(minutes=10)+timedelta(hours=h)).isoformat(),
            "direction":"SELL","reason":"RESEARCH_CANDIDATE_SIGNAL",
            "last_close":3600.,
            "sides":{
                "BUY":{"version":"R25","active":False,"parity":{"parity":"PASS"}},
                "SELL":{"version":"R11","active":True,"parity":{"parity":"PASS"}},
            },
        }
        (tmp_path/f).write_text(json.dumps(q))
    return tmp_path


def test_publish_r25_r11_only_and_preserve_unavailable_d1_w1(tmp_path):
    now=datetime(2026,11,23,10,20,tzinfo=UTC)
    r=compose(fixture(tmp_path,now),now=now)
    assert r["contract"]==CONTRACT
    assert r["rows"]["H1"]["direction"]=="SELL"
    assert r["rows"]["H4"]["direction"]=="SELL"
    for tf in ("D1","W1"):
        assert r["rows"][tf]["direction"]=="WAIT"
        assert r["rows"][tf]["state"]=="NOT_INFERENCED"
    assert r["execution_authority"] is False


def test_conflict_refuses_to_fabricate_side(tmp_path):
    now=datetime(2026,11,23,10,20,tzinfo=UTC)
    fixture(tmp_path,now)
    path=tmp_path/REPORTS["H4"]
    q=json.loads(path.read_text())
    q["sides"]["BUY"]["active"]=True
    path.write_text(json.dumps(q))
    with pytest.raises(ValueError,match="CONFLICT_RESOLUTION"):
        compose(tmp_path,now=now)


def test_expired_source_no_longer_trade_direction(tmp_path):
    now=datetime(2026,11,23,10,20,tzinfo=UTC)
    fixture(tmp_path,now)
    path=tmp_path/REPORTS["H1"]
    q=json.loads(path.read_text())
    q["candle_closed_at"]=(now-timedelta(hours=1,minutes=5)).isoformat()
    q["target_close_at"]=(now-timedelta(minutes=5)).isoformat()
    path.write_text(json.dumps(q))
    out=compose(tmp_path,now=now)
    assert out["rows"]["H1"]["direction"]=="WAIT"
    assert out["rows"]["H1"]["reason"]=="TARGET_CANDLE_EXPIRED"
    assert out["rows"]["H4"]["direction"]=="SELL"


def test_missing_proof_or_side_mismatch_aborts_atomic_packet(tmp_path):
    now=datetime(2026,11,23,10,20,tzinfo=UTC)
    fixture(tmp_path,now)
    path=tmp_path/REPORTS["H4"]
    q=json.loads(path.read_text())
    q["sides"]["SELL"]["parity"]["parity"]="FAIL"
    path.write_text(json.dumps(q))
    with pytest.raises(ValueError,match="SIDE_PROOF"):
        compose(tmp_path,now=now)
