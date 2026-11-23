"""R28.1 dashboard only admits unexpired and provenance-verified SHADOW."""
from datetime import UTC,datetime,timedelta

import pytest

from fx_scanner.r281_shadow_feed import validate, blank, CONTRACT, SOURCE, PARITY_SAMPLES


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
    assert board.loc[1,"Status"]=="WAIT DATA"
    assert "Target close prediksi sudah berakhir" in board.loc[1,"Keterangan"]
    assert [x.value for x in app.metric]==["SELL","WAIT","WAIT","WAIT"]
    text="\n".join(str(x.value) for x in app.caption)
    assert "5 indikator" not in text and "skor bukti" not in text
