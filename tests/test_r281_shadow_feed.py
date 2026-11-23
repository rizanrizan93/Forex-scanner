"""R28.1 dashboard only admits unexpired and provenance-verified SHADOW."""
from datetime import UTC,datetime,timedelta
import base64
import json

import pytest

from fx_scanner.r281_shadow_feed import validate, blank, fetch, API_URL, CONTRACT, SOURCE, PARITY_SAMPLES


def payload(now):
    published=now-timedelta(minutes=2)
    closed=now-timedelta(minutes=10)
    targets={"H1":timedelta(hours=1),"H4":timedelta(hours=4),
             "D1":timedelta(days=1),"W1":timedelta(days=7)}
    rows={}
    for tf,delta in targets.items():
        rows[tf]={
            "execution_authority": False,"execution_influence": False,
            "model_sha256":"a"*64, "model_id":"R281_RECONSTRUCTED_2026_"+tf,
            "historical_2025_parity":PARITY_SAMPLES[tf],
            "state":"R281_RECONSTRUCTED_SHADOW","direction":"SELL",
            "closed_at":closed.isoformat(),
            "target_close_at":(closed+delta).isoformat(),
            "observed_at":(published-timedelta(seconds=30)).isoformat(),
            "last_close":3800.0,"buy_head_score":.42,"sell_head_score":.58,
        }
    return {"contract":CONTRACT, "symbol":"XAUUSD","source":SOURCE,
            "as_of":published.isoformat(),
            "model_lineage":"R28.1_RECONSTRUCTED_SHADOW_NOT_FROZEN_LIVE",
            "historical_parity":"PASS_ALL_FOUR_2025",
            "execution_authority":False,"execution_influence":False,
            "research_only":True,"rows":rows}


def test_r281_shadow_direction_is_shown_only_with_correct_provenance():
    now=datetime(2026,11,23,1,30,tzinfo=UTC)
    out=validate(payload(now),now=now)
    assert set(out)==set(PARITY_SAMPLES)
    assert all(out[tf]["direction"]=="SELL" for tf in PARITY_SAMPLES)
    assert all(out[tf]["state"]=="RECONSTRUCTED_SHADOW" for tf in PARITY_SAMPLES)
    assert all(out[tf]["execution_authority"] is False for tf in PARITY_SAMPLES)


def test_r281_never_shows_expired_or_fake_broker_signal():
    now=datetime(2026,11,23,1,30,tzinfo=UTC)
    doc=payload(now)
    doc["rows"]["H1"]["target_close_at"]=(now-timedelta(seconds=1)).isoformat()
    out=validate(doc,now=now)
    assert out["H1"]["direction"]=="WAIT"
    assert out["W1"]["direction"]=="SELL"
    doc=payload(now)
    doc["rows"]["H4"]["model_sha256"]="broken"
    with pytest.raises(ValueError,match="LINEAGE"):
        validate(doc,now=now)
    doc=payload(now)
    doc["execution_authority"]=True
    with pytest.raises(ValueError,match="CONTRACT"):
        validate(doc,now=now)


def test_r281_unverified_snapshot_does_not_convert_to_technical_buy():
    assert blank()["direction"]=="WAIT"
    now=datetime(2026,11,23,1,30,tzinfo=UTC)
    doc=payload(now)
    doc["rows"]["D1"]["observed_at"]=(now-timedelta(minutes=20)).isoformat()
    assert validate(doc,now=now)["D1"]["direction"]=="WAIT"


def test_wait_retains_the_actual_publisher_reason_and_expiry():
    now=datetime(2026,11,23,1,30,tzinfo=UTC)
    doc=payload(now)
    doc["rows"]["D1"].update(state="WAIT_DATA",direction="WAIT",reason="TARGET_CANDLE_EXPIRED")
    doc["rows"]["H1"]["target_close_at"]=(now-timedelta(seconds=1)).isoformat()
    out=validate(doc,now=now)
    assert out["D1"]["reason"]==out["H1"]["reason"]=="TARGET_CANDLE_EXPIRED"
    assert out["D1"]["issued"]==doc["as_of"]


@pytest.mark.parametrize("reason",["HEAD_CONFLICT","BELOW_THRESHOLD"])
def test_model_abstention_is_distinct_from_missing_data(reason):
    now=datetime(2026,11,23,1,30,tzinfo=UTC)
    doc=payload(now)
    doc["rows"]["H4"].update(state="R281_MODEL_ABSTAIN",direction="WAIT",reason=reason)
    out=validate(doc,now=now)["H4"]
    assert out["state"]=="MODEL_ABSTAIN" and out["reason"]==reason
    assert out["direction"]=="WAIT" and out["target"]
    doc["rows"]["H4"]["target_close_at"]=(now-timedelta(seconds=1)).isoformat()
    expired=validate(doc,now=now)["H4"]
    assert expired["state"]=="WAIT_DATA" and expired["reason"]=="TARGET_CANDLE_EXPIRED"


def test_dashboard_uses_model_only_and_does_not_fetch_other_predictions():
    from streamlit.testing.v1 import AppTest
    source = '''
from datetime import UTC,datetime
import fx_scanner.frozen_direction_research_dashboard as dashboard
from fx_scanner.r281_shadow_feed import blank
def model():
    rows={tf:blank("TARGET_CANDLE_EXPIRED") for tf in dashboard.TFS}
    rows["H1"].update(direction="SELL",state="RECONSTRUCTED_SHADOW",reason="RESEARCH_SIGNAL")
    return rows
def unexpected():
    raise AssertionError("Other prediction/chart sources must not be fetched")
dashboard.fetch_r281=model
dashboard.load_context_sources=unexpected
dashboard.render_frozen_direction_research()
'''
    app=AppTest.from_string(source,default_timeout=12).run()
    assert not app.exception
    board=app.dataframe[0].value
    assert board.loc[0,"Arah R28.1"]=="SELL"
    assert board.loc[0,"Panduan setup"]=="PANTAU SETUP SELL"
    assert board.loc[0,"BUY terbaik (historis)"]=="53.06% · R25"
    assert board.loc[1,"Status"]=="WAIT DATA"
    assert board.loc[1,"Panduan setup"]=="TUNGGU"
    candidate_table=app.dataframe[1].value
    assert len(candidate_table)==8
    assert candidate_table.loc[0,"Versi riset"]=="R25"
    assert candidate_table.loc[6,"Akurasi historis"]=="68.75%"
    assert set(candidate_table["Status"])=={"BENCHMARK · BELUM LIVE"}
    assert "Target close prediksi sudah berakhir" in board.loc[1,"Keterangan"]
    assert [x.value for x in app.metric]==["SELL","WAIT","WAIT","WAIT"]
    text="\n".join(str(x.value) for x in app.caption)
    assert "5 indikator" not in text and "skor bukti" not in text


def test_all_eight_candidates_are_historical_and_not_converted_to_live_signals():
    import json
    from pathlib import Path
    from fx_scanner.frozen_direction_research_dashboard import (
        candidate_rows, candidate_summary, setup_watch_label
    )
    p=Path(__file__).resolve().parents[1]/"research/direction_benchmark_lock_r281_20261122.json"
    lock=json.loads(p.read_text())
    rows=candidate_rows(lock)
    assert [(r["TF"],r["Kandidat"]) for r in rows]==[
        ("H1","BUY"),("H1","SELL"),("H4","BUY"),("H4","SELL"),
        ("D1","BUY"),("D1","SELL"),("W1","BUY"),("W1","SELL")]
    assert [r["Versi riset"] for r in rows]==[
        "R25","R11","R25","R11","R28.1","R18","R27","R24"]
    assert rows[6]["Benar / sampel"]=="33/48"
    assert rows[7]["Akurasi historis"]=="62.50%"
    assert all("BELUM LIVE" in r["Status"] for r in rows)
    assert all(r["Bukti replay"].startswith("https://github.com/") for r in rows)
    summary=candidate_summary(lock)
    assert summary["D1"]["BUY"]=="56.52% · R28.1"
    assert summary["W1"]["SELL"]=="62.50% · R24"
    assert setup_watch_label({"state":"WAIT_DATA","direction":"BUY"})=="TUNGGU"
    assert setup_watch_label({"state":"MODEL_ABSTAIN","direction":"SELL"})=="TUNGGU"
    assert setup_watch_label({"state":"RECONSTRUCTED_SHADOW","direction":"BUY"})=="PANTAU SETUP BUY"
    assert setup_watch_label({"state":"RECONSTRUCTED_SHADOW","direction":"SELL"})=="PANTAU SETUP SELL"


def test_raw_github_cdn_failure_falls_back_to_same_provenance_checked_api_packet():
    now=datetime(2026,11,23,1,30,tzinfo=UTC)
    document=payload(now)
    encoded=base64.b64encode(json.dumps(document).encode()).decode()
    response=json.dumps({"encoding":"base64","content":encoded}).encode()
    urls=[]
    class Resp:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def read(self, cap): return response
    def opener(request, timeout):
        urls.append(request.full_url)
        if "raw.githubusercontent.com" in request.full_url:
            raise OSError("CDN temporarily unavailable")
        assert request.full_url==API_URL
        return Resp()
    result=fetch(now=now,opener=opener)
    assert len(urls)==2
    assert all(result[tf]["direction"]=="SELL" for tf in PARITY_SAMPLES)
    assert all(not result[tf]["execution_authority"] for tf in PARITY_SAMPLES)


def test_api_fallback_never_approves_forged_snapshot():
    now=datetime(2026,11,23,1,30,tzinfo=UTC)
    doc=payload(now)
    doc["execution_authority"]=True
    response=json.dumps({"encoding":"base64","content":base64.b64encode(json.dumps(doc).encode()).decode()}).encode()
    class Resp:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def read(self, cap): return response
    def opener(request, timeout):
        if "raw.githubusercontent.com" in request.full_url:
            raise OSError("raw down")
        return Resp()
    with pytest.raises(ValueError,match="CONTRACT"):
        fetch(now=now,opener=opener)
