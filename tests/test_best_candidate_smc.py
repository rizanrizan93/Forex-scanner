"""BEST candidate SMC bridge: no archived direction is ever an entry."""
from datetime import UTC,datetime,timedelta
import pandas as pd
import pytest

from fx_scanner.best_candidate_direction import VERSIONS
from fx_scanner.best_candidate_smc import best_direction, evaluate_best_entry

NOW=datetime(2026,11,23,12,45,tzinfo=UTC)

def head(tf,side,status="ACTIVE_SHADOW",expiry=None):
    return {
        "tf":tf,"direction":side,"status":status,
        "target":(expiry or NOW+timedelta(hours=4)).isoformat(),
        "issued":(NOW-timedelta(minutes=3)).isoformat(),
        "sources":VERSIONS[tf].copy(),
        "research_only":True,"execution_authority":False,
        "execution_influence":False,
    }

def board(h1="SELL",h4="SELL",d1="WAIT",w1="WAIT",partial=False):
    return {
        "H1":head("H1",h1) if h1!="WAIT" else head("H1","WAIT","WAIT_MODEL"),
        "H4":head("H4",h4) if h4!="WAIT" else head("H4","WAIT","WAIT_MODEL"),
        "D1":head("D1",d1,"PARTIAL_HEAD" if partial else "ACTIVE_SHADOW")
             if d1!="WAIT" else head("D1","WAIT","NOT_INFERENCED"),
        "W1":head("W1",w1) if w1!="WAIT" else head("W1","WAIT","NOT_INFERENCED")
    }

def test_no_d1_only_watch_h4_no_levels():
    x=board()
    side,reason,ctx=best_direction(x,NOW)
    assert (side,reason)==("SELL","BEST_DIRECTION_INCOMPLETE_WATCH_ONLY")
    assert ctx["h1_confirmed"] is True and ctx["d1_confirmed"] is False
    rep=evaluate_best_entry(x,None,now=NOW)
    assert rep["side"]=="SELL" and rep["status"]=="WAIT"
    assert rep["watch_only"] is True
    assert all(rep[k] is None for k in
               ("entry_reference","sl_reference","tp_1_5r_reference","tp_2r_reference"))
    assert rep["execution_authority"] is False

def test_h1_opposing_h4_refuses_any_zone():
    x=board(h1="BUY")
    side,reason,ctx=best_direction(x,NOW)
    assert side=="WAIT" and reason=="BEST_H1_OPPOSING"
    assert evaluate_best_entry(x,None,now=NOW)["side"]=="WAIT"

def test_partial_d1_cannot_unlock_entry_even_when_aligned():
    x=board(h1="BUY",h4="BUY",d1="BUY",partial=True)
    side,reason,ctx=best_direction(x,NOW)
    assert side=="BUY" and reason=="BEST_DIRECTION_INCOMPLETE_WATCH_ONLY"
    assert ctx["d1_partial"] and not ctx["d1_confirmed"]

def test_full_independent_d1_must_align_before_levels():
    x=board(h1="SELL",h4="SELL",d1="SELL")
    assert best_direction(x,NOW)[1]=="BEST_DIRECTION_ALIGNED"
    x["D1"]["direction"]="BUY"
    assert best_direction(x,NOW)[:2]==("WAIT","BEST_D1_OPPOSING")

def test_expired_h4_and_forged_authority_fail_closed():
    x=board()
    x["H4"]["target"]=(NOW-timedelta(seconds=1)).isoformat()
    assert best_direction(x,NOW)[0]=="WAIT"
    x=board()
    x["H4"]["execution_influence"]=True
    assert best_direction(x,NOW)[0]=="WAIT"
    x=board()
    x["H4"]["sources"]={"BUY":"R28.1","SELL":"R11"}
    assert best_direction(x,NOW)[0]=="WAIT"

def test_w1_opposition_is_disclosed_not_converted_to_forecast():
    x=board(w1="BUY")
    side,reason,ctx=best_direction(x,NOW)
    assert side=="SELL" and ctx["weekly_countertrend"] is True

def test_smc_ui_uses_best_side_feed_and_never_legacy_default_direction():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    p=(root/"src/fx_scanner/r281_smc_entry_dashboard.py").read_text()
    assert "select_best_candidate_direction(best,h4buy,r281,now=now)" in p
    assert "independent_zones(primary,snapshot,now=now)" in p
    assert "evaluate_best_entry(primary,market,now=now)" not in p
    assert "evaluate_entry(shadow,market" not in p

def test_incomplete_direction_scrubs_zone_and_never_unlocks_numeric_entry(monkeypatch):
    # A real closed M1 zone is evaluated; WATCH-only must scrub nested values.
    import fx_scanner.r281_smc_entry_engine as engine
    def zone():
        return {"zone_id":"best_only","direction":"SELL","timeframe":"H1",
                "low":3599.,"high":3602.,"available_at":"2026-11-23T12:00:00+00:00",
                "atr":15.,"structural_bos":True,"lifecycle":"RETESTED",
                "touch_count":1}
    monkeypatch.setattr(engine,"detect",lambda rows,tf,now:[zone()] if tf=="H1" else [])
    frame_idx=pd.date_range(end=pd.Timestamp("2026-11-23T12:44:00+00:00"),
                            periods=1700,freq="min")
    prices=pd.Series(3604.,index=frame_idx)
    prices.loc[prices.index>=pd.Timestamp("2026-11-23T12:10:00+00:00")]=3600.
    prices.loc[prices.index>=pd.Timestamp("2026-11-23T12:30:00+00:00")]=3597.
    frame=pd.DataFrame({"open":prices,"high":prices+.1,"low":prices-.1,
                        "close":prices},index=frame_idx)
    market={"frame":frame,"as_of":NOW-timedelta(seconds=1),
            "bid":3597.,"ask":3597.2,"quote_as_of":NOW-timedelta(seconds=1)}
    report=evaluate_best_entry(board(),market,now=NOW)
    assert report["watch_only"] is True
    assert report["execution_authority"] is False
    assert report["status"]!="M5_BOS_CONFIRMED"
    for k in ("entry_reference","sl_reference","tp_1_5r_reference","tp_2r_reference"):
        assert report[k] is None
        assert all(z[k] is None for z in report.get("candidates",[]))
