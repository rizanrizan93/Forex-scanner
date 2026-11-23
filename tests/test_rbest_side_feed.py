"""Candidate consumer must never convert archival accuracy to live prediction."""
from datetime import UTC,datetime,timedelta
import copy
import pytest

from fx_scanner.rbest_side_feed import (
    CANDIDATES,CONTRACT,SOURCE,KNOWN_R11_TRAIN_HASH,KNOWN_R11_VAL_HASH,
    KNOWN_R25_VALIDATION,validate,blank
)
from fx_scanner.rbest_side_dashboard import candidate_runtime_rows


def specimen(now):
    pub=now-timedelta(minutes=2)
    rows={}
    for tf in CANDIDATES:
        if tf in ("D1","W1"):
            rows[tf]={
                "direction":"WAIT","reason":"INDEPENDENT_MODEL_NOT_INFERENCED",
                "state":"NOT_INFERENCED","execution_authority":False,
            }
            continue
        hours=1 if tf=="H1" else 4
        closed=now-timedelta(minutes=12)
        buy_n,buy_k=KNOWN_R25_VALIDATION[tf]
        rows[tf]={
            "direction":"SELL","state":"RESEARCH_SHADOW",
            "reason":"RESEARCH_CANDIDATE_SIGNAL",
            "generated_at":pub.isoformat(),
            "closed_at":closed.isoformat(),
            "target_close_at":(closed+timedelta(hours=hours)).isoformat(),
            "observed_at":(pub-timedelta(seconds=20)).isoformat(),
            "last_close":3610.,"execution_authority":False,
            "sides":{
                "BUY":{
                    "version":"R25","active":False,"score":0.54,
                    "threshold":.55,"gate":"vol_high","gate_pass":True,
                    "parity":{"parity":"PASS","n":buy_n,"correct":buy_k},
                },
                "SELL":{
                    "version":"R11","active":True,
                    "parity":{
                        "parity":"PASS",
                        "historical_train_sha256":KNOWN_R11_TRAIN_HASH[tf],
                        "historical_validation_sha256":KNOWN_R11_VAL_HASH[tf],
                    }
                },
            },
        }
    return {
        "contract":CONTRACT,"source":SOURCE,"symbol":"XAUUSD",
        "research_only":True,"execution_authority":False,
        "execution_influence":False,
        "as_of":pub.isoformat(),"candidate_lineage":copy.deepcopy(CANDIDATES),
        "rows":rows,
    }


def test_only_verified_h1_h4_active_side_is_displayed():
    now=datetime(2026,11,23,10,22,tzinfo=UTC)
    output=validate(specimen(now),now=now)
    assert [output[k]["direction"] for k in ("H1","H4")]==["SELL","SELL"]
    assert [output[k]["state"] for k in ("D1","W1")]==["NOT_INFERENCED"]*2
    assert all(v["execution_authority"] is False for v in output.values())


def test_expired_h1_cannot_be_reused_after_next_candle_close():
    now=datetime(2026,11,23,10,22,tzinfo=UTC)
    document=specimen(now)
    document["rows"]["H1"]["closed_at"]=(now-timedelta(hours=1,minutes=5)).isoformat()
    document["rows"]["H1"]["target_close_at"]=(now-timedelta(minutes=5)).isoformat()
    result=validate(document,now=now)
    assert result["H1"]["direction"]=="WAIT"
    assert result["H1"]["reason"]=="TARGET_CANDLE_EXPIRED"
    assert result["H4"]["direction"]=="SELL"


def test_bad_parity_or_forged_d1_candidate_aborts_whole_packet():
    now=datetime(2026,11,23,10,22,tzinfo=UTC)
    document=specimen(now)
    document["rows"]["H4"]["sides"]["SELL"]["parity"]["historical_train_sha256"]="FAKE"
    with pytest.raises(ValueError,match="PARITY_FAILED"):
        validate(document,now=now)
    document=specimen(now)
    document["rows"]["W1"]["direction"]="BUY"
    with pytest.raises(ValueError,match="FORGED"):
        validate(document,now=now)


def test_both_heads_triggering_cannot_be_called_buy_or_sell():
    now=datetime(2026,11,23,10,22,tzinfo=UTC)
    document=specimen(now)
    document["rows"]["H4"]["sides"]["BUY"]["active"]=True
    with pytest.raises(ValueError,match="CONFLICT_RESOLUTION"):
        validate(document,now=now)
    document["rows"]["H4"]["direction"]="WAIT"
    document["rows"]["H4"]["reason"]="SIDE_CONFLICT"
    result=validate(document,now=now)
    assert result["H4"]["state"]=="MODEL_ABSTAIN"
    assert result["H4"]["direction"]=="WAIT"


def test_eight_lane_table_never_upgrades_unimplemented_d1_w1():
    archive={
        "entries":[
            {"tf":tf,"side":side,"version":CANDIDATES[tf][side],
             "accuracy":.60,"correct":60,"n":100,"run_url":"https://github.com/example"}
            for tf in ("H1","H4","D1","W1") for side in ("BUY","SELL")
        ]
    }
    now=datetime(2026,11,23,10,22,tzinfo=UTC)
    best=validate(specimen(now),now=now)
    legacy={tf:blank("TARGET_CANDLE_EXPIRED") for tf in CANDIDATES}
    got=candidate_runtime_rows(best,archive,legacy)
    assert len(got)==8
    assert got[1]["Hasil kandidat"]=="AKTIF · SHADOW"
    assert got[0]["Hasil kandidat"]=="TIDAK TERPICU"
    assert got[5]["Hasil kandidat"]=="BELUM ADA MODEL INFERENSI"
    assert got[6]["Hasil kandidat"]=="BELUM ADA MODEL INFERENSI"
    assert got[0]["Akurasi historis"]=="60.00%"


def test_source_code_shows_model_absence_not_fake_winner():
    from pathlib import Path
    d=Path(__file__).resolve().parents[1]/"src/fx_scanner/frozen_direction_research_dashboard.py"
    content=d.read_text()
    assert "render_best_candidate_block" in content
    assert "fetch_rbest" in content
    assert "read_rbest.clear()" in content
