from datetime import UTC,datetime,timedelta
from types import SimpleNamespace as N
import pandas as pd
import pytest
from fx_scanner.zone_v05 import confirmation,build_plan,blank,validate,MIN,HOUR,INF
from fx_scanner.zone_v05_quotes import spread_asof
T=pd.Timestamp('2026-01-23T09:00:00Z').value

def frames():
    m=pd.DataFrame({'timestamp':pd.to_datetime([T+i*MIN for i in range(41)],utc=True),'open':102.,'high':103.,'low':101.,'close':102.});m.loc[0,'low']=99.5
    five=pd.DataFrame({'closed_ns':[T+(i+1)*5*MIN for i in range(8)],'open':101.,'high':103.,'low':100.,'close':102.});five.loc[3,['close','high']]=[104.,104.5]
    fifteen=pd.DataFrame({'closed_ns':[T+15*MIN,T+30*MIN],'open':[100.,101.],'close':[102.,104.]})
    a=N(family=5,tf=60,lookback=20,direction=1,formed_ns=T-HOUR,low=99.,high=101.,atr=10.,strength=1.,touch_i=0,dead=INF)
    z=pd.DataFrame([dict(family=6,tf=60,direction=-1,formed_ns=T-HOUR,low=120.,high=121.,atr=10.,dead=INF)])
    return a,z,m,five,fifteen

def test_reclaim_is_not_entry_until_subsequent_m5_bos():
    a,z,m,five,fifteen=frames()
    assert confirmation(five,fifteen,T,T+15*MIN,1,101.)==(T+15*MIN,None)
    assert confirmation(five,fifteen,T,T+20*MIN,1,101.)==(T+15*MIN,T+20*MIN)

def test_entry_uses_next_open_and_old_signal_becomes_active_reference():
    a,z,m,five,fifteen=frames();en=pd.Timestamp(T+20*MIN,tz='UTC').isoformat()
    p=build_plan(a,z,m.iloc[:22],five,fifteen,T+22*MIN,{en:.3})
    assert p['state']=='ENTRY' and p['entry']==102. and p['planned_net_rr']>=1.5
    assert p['target']['low']==120. and p['tp']==119.75
    assert build_plan(a,z,m,five,fifteen,T+40*MIN,{en:.3})['state']=='AKTIF_REFERENSI'

def test_missing_spread_blocks_and_spent_target_cancels():
    a,z,m,five,fifteen=frames()
    assert build_plan(a,z,m,five,fifteen,T+22*MIN,{})['state']=='BLOCK'
    m.loc[12,'high']=121.
    assert build_plan(a,z,m,five,fifteen,T+22*MIN,{})['reason']=='TARGET_SUDAH_TERCAPAI'

def test_both_sides_same_minute_stop_first():
    a,z,m,five,fifteen=frames();en=pd.Timestamp(T+20*MIN,tz='UTC').isoformat();m.loc[21,['low','high']]=[90.,125.]
    p=build_plan(a,z,m,five,fifteen,T+22*MIN,{en:.3})
    assert p['state']=='SELESAI' and p['reason']=='SL_TERSENTUH'

def test_stale_snapshot_hides_entry_and_execution_guard():
    now=datetime.now(UTC);p=blank(now);p.update(evaluated_close_at=(now-timedelta(minutes=8)).isoformat(),plans=[{'state':'ENTRY'}])
    q=validate(p,now=now);assert not q['fresh'] and q['plans']==[]
    p['execution_authority']=True
    with pytest.raises(ValueError):validate(p,now=now)

def test_asof_quotes_reject_future_stale_crossed_truncated():
    def r(t,p,more=False):return N(tickData=[N(timestamp=t,tick=int(p*100000))],hasMore=more)
    assert spread_asof(r(9990,4000),r(9995,4000.3),10000)==pytest.approx(.3)
    assert spread_asof(r(10001,4000),r(9995,4000.3),10000) is None
    assert spread_asof(r(1,4000),r(1,4000.3),30000) is None
    assert spread_asof(r(9990,4001),r(9995,4000.3),10000) is None
    assert spread_asof(r(9990,4000,True),r(9995,4000.3),10000) is None

def test_forming_native_candle_is_excluded():
    from fx_scanner.zone_v05 import completed
    rows=[dict(timestamp='2026-01-23T09:00:00Z',open=100,high=101,low=99,close=100),dict(timestamp='2026-01-23T09:05:00Z',open=100,high=9999,low=1,close=9999)]
    assert len(completed(rows,'M5',pd.Timestamp('2026-01-23T09:06:00Z')))==1

def test_registry_preserves_formed_geometry_when_rolling_feed_changes():
    from fx_scanner.zone_v05 import preserve_registry,CONTRACT
    row=dict(formed_ns=T,direction=1,tf=60,family=5,style=0,lookback=20,low=99.,high=101.,atr=10.,strength=1.,base_ns=T,origin_eligible=True)
    prior=dict(contract=CONTRACT,node_registry=[row]);new=dict(row,low=99.01,high=101.01)
    z=preserve_registry(pd.DataFrame([new]),prior,T-HOUR)
    assert len(z)==1 and z.low.iloc[0]==99. and z.high.iloc[0]==101.


def test_sell_confirmation_requires_lower_break():
    five=pd.DataFrame({'closed_ns':[T+(i+1)*5*MIN for i in range(4)],'open':100.,'high':101.,'low':98.,'close':99.})
    five.loc[3,'close']=97.
    fifteen=pd.DataFrame({'closed_ns':[T+15*MIN],'open':[101.],'close':[99.]})
    assert confirmation(five,fifteen,T,T+20*MIN,-1,100.)==(T+15*MIN,T+20*MIN)


def test_panel_renders_watch_and_entry_as_research_without_orders():
    import json
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    now=pd.Timestamp.now(tz='UTC');a,z,m,five,fifteen=frames();en=pd.Timestamp(T+20*MIN,tz='UTC').isoformat()
    plan=build_plan(a,z,m.iloc[:22],five,fifteen,T+22*MIN,{en:.3})
    plan['confirmation_m5_at']=(now-pd.Timedelta(minutes=1)).isoformat()
    p=blank(now);p.update(evaluated_close_at=now.floor('5min').isoformat(),plans=[plan],decisions=[dict(side='BUY',result='ENTRY',reason='SYARAT_TERPENUHI')])
    source='from fx_scanner.zone_v05_dashboard import render_snapshot\nimport json\nrender_snapshot(json.loads('+repr(json.dumps(p))+'))'
    app=AppTest.from_string(source).run(timeout=15)
    assert not app.exception
    assert any('BUY · ENTRY' in x.value for x in app.markdown)
    assert any(x.label=='TP sebelum zona B' for x in app.metric)
    assert [x.label for x in app.button]==['Kunci zona BUY sebagai acuan']
    assert not app.checkbox


def test_old_confirmation_is_not_presented_as_current_cost_block():
    a,z,m,five,fifteen=frames()
    p=build_plan(a,z,m,five,fifteen,T+25*HOUR,{})
    assert p['state']=='BATAL' and p['reason']=='KONFIRMASI_LAMA_LEBIH_24_JAM'


def test_fresh_direct_snapshot_does_not_require_github_api():
    from unittest.mock import patch
    from fx_scanner import zone_v05_dashboard as panel
    now=pd.Timestamp.now(tz='UTC');p=blank(now);p['evaluated_close_at']=now.floor('5min').isoformat();p['supply_demand_policy']='BASE_BOS_STICKY_1'
    with patch.object(panel,'read_json',return_value=p),patch.object(panel,'latest_commit',side_effect=OSError('API unavailable')) as commit:
        assert panel.fetch()['fresh']
        commit.assert_not_called()


def test_consumer_expires_entry_even_when_cached_snapshot_is_within_grace():
    now=pd.Timestamp.now(tz='UTC');a,z,m,five,fifteen=frames();en=pd.Timestamp(T+20*MIN,tz='UTC').isoformat()
    plan=build_plan(a,z,m.iloc[:22],five,fifteen,T+22*MIN,{en:.3});plan['confirmation_m5_at']=(now-pd.Timedelta(minutes=6)).isoformat()
    p=blank(now);p.update(state='ENTRY',evaluated_close_at=(now-pd.Timedelta(minutes=6)).isoformat(),plans=[plan],decisions=[dict(side='BUY',result='ENTRY',reason='OK')])
    q=validate(p,now=now)
    assert q['fresh'] and q['plans'][0]['state']=='AKTIF_REFERENSI' and q['decisions'][0]['result']=='TIDAK_ENTRY'


def test_entry_open_uses_first_tick_and_only_ask_known_at_that_tick():
    from fx_scanner.zone_v05_quotes import entry_open_quote
    # Reverse-chronological delta encoding: first bid is 4000 at10005ms.
    b=N(tickData=[N(timestamp=10020,tick=400100000),N(timestamp=-15,tick=-100000)],hasMore=False)
    a=N(tickData=[N(timestamp=10015,tick=400120000),N(timestamp=-12,tick=-100000)],hasMore=False)
    p=entry_open_quote(b,a,10000,10030)
    assert p['price']==4000 and p['observed_ms']==10005 and p['spread']==pytest.approx(.2)
    b.hasMore=True
    assert entry_open_quote(b,a,10000,10030) is None


def test_missing_next_m1_requests_observed_open_quote_instead_of_waiting_one_minute():
    a,z,m,five,fifteen=frames()
    p=build_plan(a,z,m.iloc[:20],five,fifteen,T+20*MIN+5_000_000_000,{})
    assert p['state']=='WATCH' and p['open_quote_anchor']==pd.Timestamp(T+20*MIN,tz='UTC').isoformat()


def test_watch_zones_are_independent_of_entry_but_exclude_broken_and_future_nodes():
    from fx_scanner.zone_v05 import watch_zones
    z=pd.DataFrame([dict(family=5,tf=60,direction=d,formed_ns=at,low=lo,high=hi,dead=dead) for d,at,lo,hi,dead in [
        (1,T-HOUR,99.,100.,INF),(-1,T-HOUR,110.,111.,INF),
        (1,T-HOUR,103.,104.,T-1),(-1,T+HOUR,105.,106.,INF),
        (1,T-HOUR,107.,108.,INF)]])
    result=watch_zones(z,105.,T)
    assert [(x['side'],x['low']) for x in result]==[('BUY',99.),('SELL',110.)]
    assert all(x['state']=='WATCH_ZONE_ONLY' for x in result)


def test_stale_snapshot_cannot_show_watch_zones_as_current():
    now=datetime.now(UTC);p=blank(now);p.update(evaluated_close_at=(now-timedelta(minutes=8)).isoformat(),watch_zones=[dict(low=99,high=100)])
    assert validate(p,now=now)['watch_zones']==[]


def test_locked_zone_survives_reselection_stale_feed_and_reload_until_released():
    import json
    from streamlit.testing.v1 import AppTest
    now=pd.Timestamp.now(tz='UTC');p=blank(now)
    p.update(evaluated_close_at=now.floor('5min').isoformat(),watch_zones=[dict(side='SELL',timeframe='H1',low=4119.39,high=4124.25,formed_at=now.isoformat())])
    p['plans']=[dict(source=p['watch_zones'][0],state='WATCH',reason='MENUNGGU_KONFIRMASI')]
    source='import json\nfrom fx_scanner.zone_v05_dashboard import render_snapshot\nrender_snapshot(json.loads('+repr(json.dumps(p))+'))'
    app=AppTest.from_string(source).run(timeout=15)
    app.button[0].click().run()
    saved=dict(app.query_params)
    assert any(x.label=='Acuan tersimpan · H1' and x.value=='4,119.39–4,124.25' for x in app.metric)
    p['watch_zones'][0].update(low=4127.41,high=4132.02)
    p['evaluated_close_at']=(now-pd.Timedelta(minutes=20)).isoformat()
    reloaded=AppTest.from_string('import json\nfrom fx_scanner.zone_v05_dashboard import render_snapshot\nrender_snapshot(json.loads('+repr(json.dumps(p))+'))')
    reloaded.query_params.update(saved)
    reloaded.run(timeout=15)
    assert not reloaded.exception
    assert any(x.value=='4,119.39–4,124.25' for x in reloaded.metric)
    assert not any('4,132.02' in x.value for x in reloaded.metric)
    reloaded.button[0].click().run()
    assert not reloaded.metric and not reloaded.query_params


def test_reference_decoder_rejects_corrupt_or_wrong_side_geometry():
    import base64,json
    from fx_scanner.zone_v05_dashboard import decode_reference
    assert decode_reference('not-base64','BUY') is None
    ref=dict(source=dict(side='SELL',timeframe='H1',low=100,high=101,formed_at='2026-10-21T10:00:00+00:00'),saved_at='2026-10-21T10:00:00+00:00')
    encode=lambda:base64.urlsafe_b64encode(json.dumps(ref).encode()).decode()
    assert decode_reference(encode(),'BUY') is None
    ref['source']['high']=float('nan')
    assert decode_reference(encode(),'SELL') is None


def test_supply_demand_stays_fixed_until_source_close_invalidates_even_after_120h():
    from fx_scanner.zone_v05 import supply_demand,CONTRACT
    now=T+130*HOUR
    old=dict(id='saved',family=0,side='BUY',timeframe='H1',low=99.,high=100.,formed_at=pd.Timestamp(T,tz='UTC').isoformat(),selected_at=pd.Timestamp(T,tz='UTC').isoformat(),checked_close_at=pd.Timestamp(now-HOUR,tz='UTC').isoformat())
    q=pd.DataFrame(dict(time=pd.to_datetime([now-HOUR,now],utc=True),close=[102.,102.]))
    qs={60:q,240:q}
    z=pd.DataFrame([dict(family=f,style=0,lookback=20,tf=60,direction=1,formed_ns=now-HOUR,low=lo,high=lo+1) for f,lo in [(0,101.),(5,102.)]])
    prior=dict(contract=CONTRACT,supply_demand_zones=[old])
    zones,events=supply_demand(z,qs,103.,now,prior)
    assert zones[0]['id']=='saved' and zones[0]['low']==99. and not events
    q.loc[1,'close']=98.
    zones,events=supply_demand(z,qs,103.,now,prior)
    assert events[0]['id']=='saved' and events[0]['status']=='INVALID'
    assert not zones  # Both the saved zone and replacement were broken; EMA is excluded.
    q.loc[1,'close']=100.5
    zones,events=supply_demand(z,qs,103.,now,None)
    assert not zones
    z.loc[0,['lookback','low','high']]=[8,99.,100.]
    zones,events=supply_demand(z,qs,103.,now,None)
    assert zones[0]['low']==99. and zones[0]['family']==0


def test_feed_failure_preserves_saved_supply_demand_without_claiming_freshness():
    from fx_scanner.zone_v05 import evaluate,CONTRACT
    prior=dict(contract=CONTRACT,supply_demand_zones=[dict(id='saved',status='VALID')])
    result=evaluate({},previous=prior)
    assert result['supply_demand_zones']==[dict(id='saved',status='DATA_STALE')]


def test_dashboard_only_shows_v05_not_added_supply_demand_panel():
    import json
    from streamlit.testing.v1 import AppTest
    now=pd.Timestamp.now(tz='UTC');p=blank(now)
    a=dict(side='SELL',timeframe='H1',low=100.,high=102.,formed_at=now.isoformat(),selected_at=now.isoformat(),checked_close_at=now.isoformat(),status='VALID')
    p.update(evaluated_close_at=now.floor('5min').isoformat(),supply_demand_policy='BASE_BOS_STICKY_1',supply_demand_zones=[a],ema_bias={'H1':'SELL'})
    app=AppTest.from_string('import json\nfrom fx_scanner.zone_v05_dashboard import render_snapshot\nrender_snapshot(json.loads('+repr(json.dumps(p))+'))').run(timeout=15)
    assert not app.exception
    assert any('EMA V05' in x.value for x in app.subheader)
    assert not any('SUPPLY · area pantau SELL' in x.value for x in app.markdown)
    assert not app.metric and not app.button
    assert any('Belum ada setup ENTRY EMA V05' in x.value for x in app.info)


def test_watch_checklist_observes_candles_without_promoting_zone_to_entry():
    import json
    from streamlit.testing.v1 import AppTest
    from fx_scanner.zone_v05 import watch_checks,zone
    a,z,m,five,fifteen=frames();a.formed_ns=T
    obs=watch_checks(a,m.iloc[:22],five,fifteen,T+22*MIN)
    assert obs['first_touch_at']==pd.Timestamp(T,tz='UTC').isoformat()
    assert obs['confirmation_m5_at']==pd.Timestamp(T+20*MIN,tz='UTC').isoformat()
    assert obs['sl']==97.
    assert 'entry' not in obs
    missing=watch_checks(a,m.drop(index=2),five,fifteen,T+22*MIN)
    # A later missing M1 cannot erase a proven earlier first touch.
    assert missing['first_touch_at']==obs['first_touch_at']
    assert missing['confirmation_m5_at']==obs['confirmation_m5_at']
    assert missing['m1_audit']['unverified_minutes']==0
    now=pd.Timestamp.now(tz='UTC');p=blank(now);source=zone(a)
    p.update(evaluated_close_at=now.floor('5min').isoformat(),watch_zones=[source],watch_checks={source['id']:obs})
    app=AppTest.from_string('import json\nfrom fx_scanner.zone_v05_dashboard import render_snapshot\nrender_snapshot(json.loads('+repr(json.dumps(p))+'))').run(timeout=15)
    assert not app.exception
    assert any('Belum menjadi kandidat ENTRY' in x.value for x in app.markdown)
    assert sum('Teramati' in x.value for x in app.markdown)==3
    assert any(x.label=='SL skenario observasi' for x in app.metric)
    assert not any('BUY · ENTRY' in x.value for x in app.markdown)


def test_zone_fetch_uses_contents_api_when_raw_snapshot_is_stale():
    import base64,json
    from unittest.mock import patch
    from fx_scanner import zone_v05_dashboard as panel
    now=datetime.now(UTC);fresh=blank(now);fresh['evaluated_close_at']=now.isoformat()
    stale=dict(fresh,as_of=(now-timedelta(minutes=20)).isoformat(),evaluated_close_at=(now-timedelta(minutes=20)).isoformat())
    calls=[]
    def read(url):
        calls.append(url)
        if 'api.github.com' in url:return dict(encoding='base64',content=base64.b64encode(json.dumps(fresh).encode()).decode())
        return stale
    panel._api_snapshot.cache_clear()
    try:
        with patch.object(panel,'read_json',side_effect=read):
            assert panel.fetch()['fresh']
            assert panel.fetch()['fresh']
        assert sum('/contents/' in x for x in calls)==1
        assert any('rizan_minute=' in x for x in calls)
    finally:panel._api_snapshot.cache_clear()


def test_zone_fetch_never_turns_cached_stale_prices_into_entry():
    from unittest.mock import patch
    from fx_scanner import zone_v05_dashboard as panel
    now=datetime.now(UTC);stale=blank(now-timedelta(minutes=20));stale['evaluated_close_at']=stale['as_of']
    stale.update(plans=[dict(state='ENTRY')],watch_zones=[dict(low=100.,high=101.)])
    with patch.object(panel,'read_json',return_value=stale),patch.object(panel,'_api_snapshot',return_value=stale):
        result=panel.fetch()
    assert not result['fresh'] and not result['plans'] and not result['watch_zones']


def test_watch_m1_gap_before_touch_verified_by_outside_zone_m5():
    from fx_scanner.zone_v05 import watch_checks
    a,z,m,five,fifteen=frames()
    a.formed_ns=T
    m.loc[:,'low']=101.5
    m.loc[10,'low']=99.5
    five.loc[0,'low']=101.5  # Whole [T,T+5m) M5 bar excludes BUY zone <=101.
    obs=watch_checks(a,m.drop(index=2),five,fifteen,T+22*MIN)
    assert obs['first_touch_at']==pd.Timestamp(T+10*MIN,tz='UTC').isoformat()
    assert obs['m1_audit']['m1_missing_minutes']==1
    assert obs['m1_audit']['m5_excluded_missing_minutes']==1
    assert obs['m1_audit']['unverified_minutes']==0
    assert obs['reclaim_m15_at']==pd.Timestamp(T+15*MIN,tz='UTC').isoformat()


def test_watch_m1_ambiguous_gap_cannot_claim_first_touch_or_reclaim():
    from fx_scanner.zone_v05 import watch_checks
    a,z,m,five,fifteen=frames()
    a.formed_ns=T
    m.loc[:,'low']=101.5
    m.loc[10,'low']=99.5
    five.loc[0,'low']=100.  # M5 intersected zone during missing minute.
    obs=watch_checks(a,m.drop(index=2),five,fifteen,T+22*MIN)
    assert obs['observation_status']=='GAP_M1_SEBELUM_SENTUHAN'
    assert obs['observed_touch_at']==pd.Timestamp(T+10*MIN,tz='UTC').isoformat()
    assert obs['first_touch_at'] is None
    assert obs['confirmation_m5_at'] is None
    assert obs['m1_audit']['unverified_minutes']==1


def test_watch_m1_truncated_history_explicitly_reports_missing_origin():
    from fx_scanner.zone_v05 import watch_checks
    a,z,m,five,fifteen=frames()
    a.formed_ns=T
    m.loc[:,'low']=101.5
    m.loc[10,'low']=99.5
    obs=watch_checks(a,m.iloc[6:],five,fifteen,T+22*MIN)
    assert obs['observation_status']=='RIWAYAT_M1_BELUM_MENCAKUP_ZONA'
    assert obs['first_touch_at'] is None
    assert obs['m1_audit']['unverified_minutes']>=1


def test_watch_no_touch_with_safe_m1_gap_remains_waiting():
    from fx_scanner.zone_v05 import watch_checks
    a,z,m,five,fifteen=frames()
    a.formed_ns=T
    m.loc[:,'low']=101.5
    five.loc[0,'low']=101.5
    obs=watch_checks(a,m.drop(index=2),five,fifteen,T+22*MIN)
    assert obs['observation_status']=='MENUNGGU_SENTUHAN'
    assert obs['first_touch_at'] is None
    assert obs['m1_audit']['unverified_minutes']==0
    assert obs['m1_audit']['m5_excluded_missing_minutes']==1
