"""Zones are independent by source timeframe AND by frozen model side."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fx_scanner.best_candidate_direction import item
from fx_scanner.independent_timeframe_zones import independent_zones

NOW=datetime(2026,11,23,13,20,tzinfo=UTC)


def direction(tf,side,status="ACTIVE_SHADOW"):
    return item(
        tf,side,status,
        "RESEARCH_CANDIDATE_SIGNAL",
        issued=(NOW-timedelta(minutes=2)).isoformat(),
        target=(NOW+timedelta(hours=4)).isoformat(),
    )


def primary(h1="SELL",h4="BUY",d1="BUY",w1="WAIT"):
    p={
        "H1":direction("H1",h1),
        "H4":direction("H4",h4),
        "D1":direction("D1",d1,"PARTIAL_HEAD"),
        "W1":direction("W1",w1,"NOT_INFERENCED" if w1=="WAIT" else "ACTIVE_SHADOW"),
    }
    return p


def zone(tf,side,lo,hi,invalid,**kw):
    closed={"H1":NOW-timedelta(minutes=20),
            "H4":NOW-timedelta(hours=1,minutes=20),
            "D1":NOW-timedelta(hours=13,minutes=20),
            "W1":NOW-timedelta(hours=13,minutes=20)}[tf]
    z={
        "zone_id":f"{tf}_{side}","timeframe":tf,"direction":side,
        "source_type":"BASE_DISPLACEMENT",
        "structural_bos":True,"lifecycle":"FRESH",
        "risk_state":"NORMAL","eligible":True,
        "touch_count":0,"probability":None,
        "low":lo,"high":hi,"invalidation":invalid,
        "available_at":(closed-timedelta(hours=2)).isoformat(),
    }
    return {**z,**kw}


def snapshot(*zones):
    return {
        "contract":"RIZAN_XAU_MANUAL_REVERSAL_MAP_V2",
        "source":"CTRADER_MARKET_DATA_READ_ONLY",
        "symbol":"XAUUSD","execution_authority":False,
        "execution_influence":False,"state":"MAP_AVAILABLE","fresh":True,
        "as_of":(NOW-timedelta(seconds=10)).isoformat(),
        "price_observed_at":(NOW-timedelta(minutes=1)).isoformat(),
        "price":3600.,
        "timeframe_fresh":{"H1":True,"H4":True,"D1":True,"W1":True},
        "timeframe_closed_at":{
            "H1":(NOW-timedelta(minutes=20)).isoformat(),
            "H4":(NOW-timedelta(hours=1,minutes=20)).isoformat(),
            "D1":(NOW-timedelta(hours=13,minutes=20)).isoformat(),
            "W1":(NOW-timedelta(hours=13,minutes=20)).isoformat(),
        },
        "zones":list(zones),
    }


def test_h1_sell_h4_buy_are_independent_and_do_not_veto_each_other():
    p=primary()
    snap=snapshot(
        zone("H1","SELL",3606,3611,3616),
        zone("H4","BUY",3584,3590,3579),
        zone("D1","BUY",3480,3550,3470),
        zone("W1","SELL",3700,3750,3760),
    )
    out=independent_zones(p,snap,now=NOW)
    assert out["H1"]["direction"]=="SELL" and out["H1"]["state"]=="WATCH_ZONE"
    assert out["H1"]["zones"][0]["tf"]=="H1"
    assert out["H1"]["zones"][0]["direction"]=="SELL"
    assert out["H1"]["zones"][0]["low"]==3606
    assert out["H4"]["direction"]=="BUY" and out["H4"]["state"]=="WATCH_ZONE"
    assert out["H4"]["zones"][0]["tf"]=="H4"
    assert out["H4"]["zones"][0]["direction"]=="BUY"
    assert out["H4"]["zones"][0]["low"]==3584
    assert out["D1"]["state"]=="WATCH_ZONE" and out["D1"]["direction"]=="BUY"
    assert out["W1"]["state"]=="WAIT_DIRECTION" and out["W1"]["zones"]==[]
    assert all(r["entry_reference"] is None and r["sl_reference"] is None
               and r["execution_authority"] is False for r in out.values())


def test_each_tf_can_independently_buy_or_sell_after_future_model_proof():
    p=primary(h1="BUY",h4="SELL",w1="SELL")
    s=snapshot(
        zone("H1","BUY",3580,3595,3575),
        zone("H4","SELL",3610,3625,3630),
        zone("D1","BUY",3480,3550,3470),
        zone("W1","SELL",3700,3750,3760),
    )
    out=independent_zones(p,s,now=NOW)
    assert [out[tf]["direction"] for tf in ("H1","H4","D1","W1")]==[
        "BUY","SELL","BUY","SELL"]
    assert all(out[tf]["state"]=="WATCH_ZONE" for tf in out)
    assert {tf:out[tf]["zones"][0]["tf"] for tf in out} == {tf:tf for tf in out}


def test_cannot_reuse_opposite_tf_zone_when_same_tf_absent():
    p=primary()
    out=independent_zones(p,snapshot(
        zone("H1","SELL",3606,3611,3616),
        zone("H4","SELL",3606,3611,3616)),now=NOW)
    assert out["H1"]["state"]=="WATCH_ZONE"
    assert out["H4"]["state"]=="WAIT_ZONE"
    assert not out["H4"]["zones"]


def test_expired_direction_stale_source_or_untrusted_packet_fail_closed():
    p=primary()
    p["H1"]["target"]=NOW.isoformat()
    out=independent_zones(p,snapshot(zone("H1","SELL",3606,3611,3616)),now=NOW)
    assert out["H1"]["state"]=="WAIT_DIRECTION"
    assert out["H1"]["direction"]=="WAIT"
    p=primary()
    snap=snapshot(zone("H1","SELL",3606,3611,3616))
    snap["as_of"]=(NOW-timedelta(minutes=20)).isoformat()
    out=independent_zones(p,snap,now=NOW)
    assert out["H1"]["state"]=="WAIT_DATA" and not out["H1"]["zones"]
    snap=snapshot(zone("H1","SELL",3606,3611,3616))
    snap["execution_authority"]=True
    assert not independent_zones(p,snap,now=NOW)["H1"]["zones"]


def test_zone_requires_valid_closed_bos_lifecycle_freshness_and_structure():
    p=primary()
    cases=[
        {"structural_bos":False},
        {"risk_state":"PENDING_PARENT_CLOSE"},
        {"touch_count":3},
        {"source_type":"UNKNOWN"},
        {"probability":.92},
        {"eligible":False},
        {"invalidation":3608},
        {"available_at":(NOW+timedelta(minutes=3)).isoformat()},
        {"lifecycle":"DEGRADED"},
    ]
    for change in cases:
        z=zone("H1","SELL",3606,3611,3616,**change)
        row=independent_zones(p,snapshot(z),now=NOW)["H1"]
        assert row["state"]=="WAIT_ZONE",change
        assert row["zones"]==[]


def test_source_candle_must_be_fresh_and_matches_own_timeframe():
    p=primary()
    s=snapshot(zone("H1","SELL",3606,3611,3616))
    s["timeframe_fresh"]["H1"]=False
    assert independent_zones(p,s,now=NOW)["H1"]["reason"]=="SOURCE_TIMEFRAME_CANDLE_NOT_FRESH"
    s=snapshot(zone("H1","SELL",3606,3611,3616))
    s["timeframe_closed_at"]["H1"]=(NOW-timedelta(hours=3)).isoformat()
    assert independent_zones(p,s,now=NOW)["H1"]["reason"]=="SOURCE_TIMEFRAME_CANDLE_INVALID"


def test_scanner_ui_routes_all_four_timeframe_zones_and_preserves_no_orders():
    root=Path(__file__).resolve().parents[1]
    ui=(root/"src/fx_scanner/r281_smc_entry_dashboard.py").read_text()
    main=(root/"main.py").read_text()
    assert "independent_zones(primary,snapshot,now=now)" in ui
    assert "for tf in TFS:" in ui
    assert "source_closed_at" in ui
    assert '"Zona Entry TF"' in main
    assert "render_r281_smc_entry()" in main
    assert "evaluate_best_entry(primary,market,now=now)" not in ui
    assert "execute_order" not in ui and "place_order" not in ui
