"""R28 + cTrader + zone + M15/M5 entry study: fail closed regression."""
from datetime import UTC, datetime, timedelta
import pandas as pd
import pytest

from fx_scanner import r281_smc_entry_engine as engine


NOW=pd.Timestamp("2026-11-23T11:21:30+00:00")


def model(*,d1="SELL",h4="SELL",h1="SELL",w1="BUY",expiry=None):
    out={}
    for tf,side in (("D1",d1),("H4",h4),("H1",h1),("W1",w1)):
        out[tf]={"state":"RECONSTRUCTED_SHADOW","direction":side,
                 "target":(expiry or NOW+pd.Timedelta(days=1)).isoformat(),
                 "execution_authority":False}
    return out


def market():
    idx=pd.date_range(end=pd.Timestamp("2026-11-23T11:20:00+00:00"),
                      periods=1620,freq="min")
    v=pd.Series(3604.,index=idx)
    v.loc[v.index<pd.Timestamp("2026-11-23T11:00:00+00:00")]=3604.
    v.loc[pd.Timestamp("2026-11-23T11:05:00+00:00")]=3601.
    v.loc[pd.Timestamp("2026-11-23T11:06:00+00:00"):pd.Timestamp("2026-11-23T11:09:00+00:00")]=3599.
    v.loc[pd.Timestamp("2026-11-23T11:10:00+00:00"):pd.Timestamp("2026-11-23T11:13:00+00:00")]=3597.
    v.loc[pd.Timestamp("2026-11-23T11:14:00+00:00")]=3594.
    v.loc[pd.Timestamp("2026-11-23T11:15:00+00:00"):]=3588.
    frame=pd.DataFrame({"open":v.values,"high":v.values+.1,"low":v.values-.1,
                        "close":v.values},index=idx)
    return {"as_of":NOW-pd.Timedelta(seconds=1),"frame":frame,
            "bid":3588.,"ask":3588.2,"quote_as_of":NOW-pd.Timedelta(seconds=1)}


def zone():
    return {"zone_id":"real_research_geometry_test","direction":"SELL",
            "timeframe":"H1","low":3599.,"high":3602.,
            "available_at":"2026-11-23T11:00:00+00:00","atr":15.,
            "structural_bos":True,"lifecycle":"RETESTED","touch_count":1}


def test_no_direction_comes_from_eight_historical_accuracy_records():
    m=model(d1="BUY",h4="SELL")
    res=engine.evaluate_entry(m,market(),now=NOW)
    assert res["status"]=="WAIT" and res["reason"]=="R28_D1_H4_CONFLICT"
    assert res["entry_reference"] is None
    assert res["execution_authority"] is False
    m=model()
    m["H4"]["target"]=(NOW-pd.Timedelta(minutes=1)).isoformat()
    res=engine.evaluate_entry(m,market(),now=NOW)
    assert res["reason"]=="R28_D1_H4_MISSING_OR_EXPIRED"


def test_stale_broker_data_blocks_every_entry():
    m=market()
    m["as_of"]=NOW-pd.Timedelta(minutes=4)
    assert engine.evaluate_entry(model(),m,now=NOW)["reason"]=="BROKER_M1_STALE"
    m=market()
    m["frame"]=m["frame"].iloc[:-10]
    assert engine.evaluate_entry(model(),m,now=NOW)["reason"]=="LAST_M1_NOT_FRESH"


def test_full_closed_candle_chain_gives_research_levels_not_execution(monkeypatch):
    monkeypatch.setattr(engine,"detect",lambda rows,tf,now:[zone()] if tf=="H1" else [])
    x=engine.evaluate_entry(model(),market(),now=NOW)
    assert x["status"]=="M5_BOS_CONFIRMED",x
    assert x["side"]=="SELL"
    assert x["entry_reference"]==3588.
    assert x["sl_reference"]==3605.
    assert x["tp_1_5r_reference"]==pytest.approx(3562.5)
    assert x["tp_2r_reference"]==pytest.approx(3554.)
    assert x["context"]["weekly_countertrend"] is True
    assert x["confirmation_at"]=="2026-11-23T11:20:00+00:00"
    assert x["replay_verified"] is False
    assert x["execution_authority"] is False and x["execution_influence"] is False


def test_h1_wait_cannot_promote_zone_to_entry(monkeypatch):
    monkeypatch.setattr(engine,"detect",lambda rows,tf,now:[zone()] if tf=="H1" else [])
    m=model()
    m["H1"]={"state":"MODEL_ABSTAIN","direction":"WAIT","target":None,
             "execution_authority":False}
    x=engine.evaluate_entry(m,market(),now=NOW)
    assert x["status"]=="WAIT"
    assert x["reason"]=="R28_H1_NOT_CONFIRMED"
    assert x["entry_reference"] is None


def test_price_gap_before_first_touch_is_never_accepted(monkeypatch):
    monkeypatch.setattr(engine,"detect",lambda rows,tf,now:[zone()] if tf=="H1" else [])
    m=market()
    m["frame"]=m["frame"].drop(pd.Timestamp("2026-11-23T11:02:00+00:00"))
    x=engine.evaluate_entry(model(),m,now=NOW)
    assert x["status"]=="WAIT_ZONE_GAP"
    assert x["entry_reference"] is None


def test_expired_m5_bos_is_not_reused(monkeypatch):
    monkeypatch.setattr(engine,"detect",lambda rows,tf,now:[zone()] if tf=="H1" else [])
    late=NOW+pd.Timedelta(minutes=15)
    m=market()
    extra_idx=pd.date_range(start=m["frame"].index[-1]+pd.Timedelta(minutes=1),
                            end=late.floor("min")-pd.Timedelta(minutes=1),freq="min")
    extra=pd.DataFrame({"open":3588.,"high":3588.1,"low":3587.9,"close":3588.},index=extra_idx)
    m["frame"]=pd.concat([m["frame"],extra])
    m["as_of"]=late-pd.Timedelta(seconds=1)
    m["quote_as_of"]=late-pd.Timedelta(seconds=1)
    x=engine.evaluate_entry(model(),m,now=late)
    assert x["entry_reference"] is None
    assert x["status"]!="M5_BOS_CONFIRMED"


def test_no_zone_does_not_invent_numeric_entry(monkeypatch):
    monkeypatch.setattr(engine,"detect",lambda rows,tf,now:[])
    x=engine.evaluate_entry(model(),market(),now=NOW)
    assert x["status"]=="WAIT"
    assert x["reason"]=="NO_VALID_CLOSED_H1_H4_BOS_ZONE"
    assert all(x[k] is None for k in ("entry_reference","sl_reference",
                                     "tp_1_5r_reference","tp_2r_reference"))


def test_entry_ui_is_routed_and_does_not_mutate_frozen_v1():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    src=(root/"main.py").read_text()
    assert '"Titik Entry R28"' in src
    assert "render_r281_smc_entry()" in src
    engine_source=(root/"src/fx_scanner/r281_smc_entry_engine.py").read_text()
    assert "create_order" not in engine_source and "place_order" not in engine_source
    assert "NO_EXECUTION = False" in engine_source
