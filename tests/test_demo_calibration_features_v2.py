from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fx_scanner.demo_calibration_features_v2 import build_signal_feature_snapshot_v2, classify_regime_v2
from fx_scanner.models import Bar
from fx_scanner.technical import DisplacementSignal, StructureSnapshot

UTC = timezone.utc

def _snapshot(*, trend, bos=None, mss=None, displacement=None):
    return StructureSnapshot(trend=trend,last_swing_high=1.12,last_swing_low=1.08,bos=bos,mss=mss,displacement=displacement,fvg=None,sweep=None)

def _analysis(*, h1, m15, m5, direction="LONG"):
    return SimpleNamespace(symbol="EURUSD",direction=direction,setup_type="TREND_CONTINUATION",trigger_confirmed=True,h1=h1,m15=m15,m5=m5,stale_timeframes=(),conviction_components={"structure":72.0,"execution_quality":81.0},computed_guards={"STRUCTURE_INVALID":False,"CHASE_BLOCK":False})

def _bars(tf,count=20):
    step={"H1":3600,"M15":900,"M5":300}[tf]; start=datetime(2026,9,4,10,0,tzinfo=UTC); rows=[]
    for index in range(count):
        base=1.10+0.0002*index
        rows.append(Bar(symbol="EURUSD",timeframe=tf,timestamp=start+timedelta(seconds=step*index),open=base,high=base+.001,low=base-.0008,close=base+.0004,tick_count=100+index,spread_avg=.0001,spread_max=.0002))
    return tuple(rows)

def test_regime_v2_distinguishes_strong_trend_range_and_transition():
    d=DisplacementSignal("BULLISH",2.0,1.4,.9,1.2,True)
    strong=_analysis(h1=_snapshot(trend="BULLISH",bos="BULLISH"),m15=_snapshot(trend="BULLISH",bos="BULLISH"),m5=_snapshot(trend="BULLISH",bos="BULLISH",displacement=d))
    assert classify_regime_v2(strong)=="TREND_STRONG"
    ranged=_analysis(h1=_snapshot(trend="RANGE"),m15=_snapshot(trend="RANGE"),m5=_snapshot(trend="RANGE"))
    assert classify_regime_v2(ranged)=="RANGE"
    transition=_analysis(h1=_snapshot(trend="RANGE"),m15=_snapshot(trend="RANGE",bos="BULLISH",displacement=d),m5=_snapshot(trend="RANGE"))
    assert classify_regime_v2(transition)=="TRANSITION"

def test_regime_v2_marks_opposing_h1_with_lower_transition_as_reversal():
    d=DisplacementSignal("BULLISH",2.0,1.4,.9,1.2,True)
    a=_analysis(h1=_snapshot(trend="BEARISH",bos="BEARISH"),m15=_snapshot(trend="RANGE",mss="BULLISH",displacement=d),m5=_snapshot(trend="BULLISH",bos="BULLISH",displacement=d))
    assert classify_regime_v2(a)=="REVERSAL"

def test_signal_snapshot_captures_calibration_dimensions_without_inventing_execution_features():
    d=DisplacementSignal("BULLISH",2.0,1.4,.9,1.2,True)
    a=_analysis(h1=_snapshot(trend="BULLISH",bos="BULLISH"),m15=_snapshot(trend="BULLISH",bos="BULLISH"),m5=_snapshot(trend="BULLISH",bos="BULLISH",displacement=d))
    row={"id":"sig-v3","run_id":"run-v3","observed_at":datetime(2026,9,4,13,30,tzinfo=UTC).isoformat(),"symbol":"EURUSD","direction":"LONG","setup_type":"TREND_CONTINUATION","final_score":64.5,"entry_low":1.101,"entry_high":1.102,"sl":1.098,"tp1":1.106,"tp2":1.109,"rr1":1.4,"rr2":2.4,"active_guards":[],"data_coverage":.95}
    geometry={"entry_mode":"HL_PULLBACK","confirmation":"BOS","pullback_atr":.35,"zone_distance_atr":.20,"fvg_status":"OPEN","fvg_age_minutes":15.0}
    sessions={"sessions":{"LONDON":{"timezone":"UTC","start":"07:00","end":"16:00"},"NEW_YORK":{"timezone":"UTC","start":"13:00","end":"22:00"}}}
    s=build_signal_feature_snapshot_v2(analysis=a,bars_by_timeframe={"H1":_bars("H1"),"M15":_bars("M15"),"M5":_bars("M5")},signal_row=row,geometry_payload=geometry,session_config=sessions,atr_period=14)
    assert s["snapshot_version"]==3
    assert s["regime"]=="TREND_STRONG" and s["session"]=="LONDON_NY_OVERLAP"
    assert s["atr_m5"]>0 and s["atr_pct_m5"]>0
    assert s["evidence_scores"]=={"structure":72.0,"execution_quality":81.0}
    assert s["entry_mode"]=="HL_PULLBACK" and s["pullback_atr"]==.35
    assert s["nearest_directional_liquidity"]==1.12
    assert s["liquidity_distance_atr_m5"] is not None and s["liquidity_distance_atr_m5"]>0
    assert s["calibration_dimensions"]["symbol"]=="EURUSD"
    assert s["calibration_dimensions"]["direction"]=="LONG"
    assert s["calibration_dimensions"]["regime"]=="TREND_STRONG"
    assert s["spread_pips_at_entry"] is None and s["live_entry_drift_r"] is None
    assert s["entry_execution_snapshot_required"] is True
    assert s["policy_effect"]=="OBSERVATION_ONLY" and s["snapshot_complete_for_regime"] is True
