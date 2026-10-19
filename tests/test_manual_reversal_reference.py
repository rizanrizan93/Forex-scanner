from datetime import UTC,datetime,timedelta
from pathlib import Path
import ast,json
import pandas as pd
import pytest
from fx_scanner.manual_reversal_map import CONTRACT,frame,project,build_plans,reversal_phase,validate,annotate_intraday_zone_risk,derive_h2_from_h1,derive_h12_from_h4

NOW=pd.Timestamp('2026-10-15T14:30Z')

def zone(tf='H1',side='BUY',low=98.,high=100.,**kw):
    return {'zone_id':f'{tf}-{side}-{low}','timeframe':tf,'direction':side,'low':low,'high':high,
        'invalidation':low-.1 if side=='BUY' else high+.1,'available_at':(NOW-pd.Timedelta(hours=4)).isoformat(),
        'touch_count':0,'role':'UTAMA' if tf in {'H4','H1'} else 'REAKSI / REFINEMENT',
        'structural_bos':True,'probability':None,**kw}

def candles():
    m15=[{'timestamp':NOW-pd.Timedelta(minutes=30),'open':99.4,'high':101.5,'low':99.,'close':101.},
         {'timestamp':NOW-pd.Timedelta(minutes=15),'open':101.,'high':102.5,'low':100.8,'close':102.1}]
    m5=[]
    for ts in pd.date_range(NOW-pd.Timedelta(minutes=40),NOW-pd.Timedelta(minutes=5),freq='5min'):
        op,cl,lo,hi=(100.8,102.,100.7,102.3) if ts==NOW-pd.Timedelta(minutes=15) else (102.,102.1,101.8,102.3) if ts>NOW-pd.Timedelta(minutes=15) else (100.7,100.8,100.5,101.2)
        m5.append({'timestamp':ts,'open':op,'high':hi,'low':lo,'close':cl})
    return {'M15':frame(m15,'M15',NOW),'M5':frame(m5,'M5',NOW),
        'H1':frame([{'timestamp':NOW-pd.Timedelta(hours=1),'open':102.,'high':103.,'low':101.,'close':102.1}],'H1',NOW),
        'H4':frame([{'timestamp':NOW-pd.Timedelta(hours=4),'open':102.,'high':103.,'low':101.,'close':102.1}],'H4',NOW)}

def test_filter_price_side_before_cap_keeps_valid_zone():
    z=project([zone(low=95.,high=97.),zone(low=100.5,high=101.),zone(low=101.,high=102.)],100.)
    assert any(x['eligible'] and x['low']==95. for x in z)

def test_target_already_passed_is_not_displayed_and_micro_target_not_promoted():
    rows=project([zone(),zone('M5','SELL',103.,104.),zone('H1','SELL',101.,102.),zone('H4','SELL',110.,112.)],105.)
    z=next(x for x in rows if x['direction']=='BUY')
    assert z['target_structural']==110. and z['tp1_reference']==110.

def test_h1_h4_anchor_is_not_replaced_by_nearest_m5():
    z=project([zone(),zone('M5',low=102.,high=102.2),zone('H4',low=96.,high=99.)],102.1)
    plan=build_plans(z,candles(),102.1,NOW)[0]
    assert plan['anchor']['timeframe']=='H1' and plan['context_h4']['timeframe']=='H4'
    only_micro=project([zone('M5',low=102.,high=102.2)],102.1)
    assert build_plans(only_micro,candles(),102.1,NOW)==[]

def test_confirmation_is_m15_then_later_m5_not_same_close():
    z=project([zone()],102.1)[0];f=candles();s=reversal_phase(z,f,102.1,NOW)
    assert s['phase']=='KONFIRMASI_STRUKTUR'
    assert pd.Timestamp(s['confirmation_m5_at'])>pd.Timestamp(s['rejection_m15_at'])
    f['M5'].loc[f['M5'].timestamp==NOW-pd.Timedelta(minutes=20),['high','close']]=[104.,103.]
    f['M5'].loc[f['M5'].timestamp>=NOW-pd.Timedelta(minutes=15),['high','close']]=[102.3,102.1]
    assert reversal_phase(z,f,102.1,NOW)['phase']=='MENUNGGU_BREAK_M5'

def test_new_contact_resets_old_confirmation_and_missing_data_cannot_confirm():
    z=project([zone()],102.1)[0];f=candles();f['M15'].loc[1,['open','high','low','close']]=[100.,101.,99.,99.5]
    assert reversal_phase(z,f,99.5,NOW)['phase']=='MENUNGGU_RECLAIM_M15'
    f['M5']=f['M5'].iloc[:1]
    assert reversal_phase(z,f,102.1,NOW)['phase']=='DATA_KONFIRMASI_BELUM_LENGKAP'

def test_sell_confirmation_is_symmetric_and_missing_m5_bar_cannot_confirm():
    f=candles()
    for tf in f:
        old=f[tf].copy()
        for key in ['open','close']:f[tf][key]=200.-old[key]
        f[tf]['high']=200.-old.low;f[tf]['low']=200.-old.high
    z=project([zone(side='SELL',low=100.,high=102.)],97.9)[0]
    assert reversal_phase(z,f,97.9,NOW)['phase']=='KONFIRMASI_STRUKTUR'
    f['M5']=f['M5'].loc[f['M5'].timestamp!=NOW-pd.Timedelta(minutes=25)].reset_index(drop=True)
    assert reversal_phase(z,f,97.9,NOW)['phase']=='MENUNGGU_BREAK_M5'

def test_confirmation_cancels_after_distal_break_and_does_not_invite_chasing():
    z=project([zone()],102.1)[0];f=candles()
    assert reversal_phase(z,f,105.,NOW)['phase']=='GERAK_SUDAH_BERJALAN'
    f['M5'].loc[f['M5'].index[-1],['open','high','low','close']]=[102.,102.2,97.,97.5]
    assert reversal_phase(z,f,102.1,NOW)['phase']=='KONFIRMASI_BATAL'

def test_major_conflict_blocks_confirmation_but_m5_cannot_be_major_conflict():
    rows=project([zone(),zone('H4','SELL',99.,101.)],100.)
    z=next(x for x in rows if x['direction']=='BUY')
    assert reversal_phase(z,candles(),100.,NOW)['phase']=='KONFLIK_H1_H4'
    rows=project([zone(),zone('M5','SELL',99.,101.)],100.)
    z=next(x for x in rows if x['direction']=='BUY')
    assert z['overlap'] and not z['major_conflict']

def test_old_confirmation_expires_and_no_future_forming_candle_is_used():
    z=project([zone()],102.1)[0];f=candles();later=NOW+pd.Timedelta(minutes=40)
    for tf,mins in [('M15',15),('M5',5)]:
        extra=[{'timestamp':ts,'open':102.,'high':102.3,'low':101.8,'close':102.1} for ts in pd.date_range(NOW,later-pd.Timedelta(minutes=mins),freq=f'{mins}min')]
        f[tf]=frame(f[tf].to_dict('records')+extra,tf,later)
    assert reversal_phase(z,f,102.1,later)['phase']=='KONFIRMASI_LAMA'
    native=candles()['M5'].to_dict('records');native.append({'timestamp':NOW,'open':102.,'high':120.,'low':90.,'close':119.})
    assert len(frame(native,'M5',NOW))==len(native)-1

def snapshot(now=None):
    now=pd.Timestamp(now or datetime.now(UTC));f=candles();zones=project([zone(),zone('H4','SELL',108.,110.)],102.1)
    for z in zones:z['available_at']=(now-pd.Timedelta(hours=4)).isoformat()
    anchor=next(z for z in zones if z['direction']=='BUY')
    return {'contract':CONTRACT,'symbol':'XAUUSD','as_of':now.isoformat(),'price_observed_at':now.isoformat(),
        'state':'MAP_AVAILABLE','price':102.1,'execution_authority':False,'execution_influence':False,'probability':None,
        'zones':zones,'plans':[{'direction':'BUY','anchor':anchor,'context_h4':None,'refinements':[],
            'target_reference':108.,'target_distance_usd':5.9,'invalidation_rule':'Close H1 melewati batas skenario.',
            'phase':'MENUNGGU_HARGA','rejection_m15_at':None,'confirmation_m5_at':None,
            'confirmation_reference':None,'execution_authority':False,'execution_influence':False,'probability':None}]}

def test_validation_rejects_trade_authority_probabilities_future_and_old_price():
    p=snapshot();assert validate(p)['fresh']
    p['price_observed_at']=(pd.Timestamp(p['as_of'])-pd.Timedelta(hours=1)).isoformat();assert not validate(p)['fresh']
    for field,value in [('execution_authority',True),('execution_influence',True),('probability',.9)]:
        p=snapshot();p[field]=value
        with pytest.raises(ValueError):validate(p)
    p=snapshot();p['plans'][0]['confirmation_m5_at']=(pd.Timestamp(p['as_of'])+pd.Timedelta(minutes=1)).isoformat()
    with pytest.raises(ValueError):validate(p)
    p=snapshot();p['plans'][0]['target_reference']=100.
    with pytest.raises(ValueError):validate(p)

def test_display_imports_cannot_reach_order_bridge_or_strategy_mutation():
    root=Path(__file__).resolve().parents[1]
    for path in [root/'src/fx_scanner/manual_reversal_map.py',root/'src/fx_scanner/manual_reversal_dashboard.py']:
        tree=ast.parse(path.read_text());imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        assert not any(any(k in name for k in ['execution','bridge','frozen','strategy','cli','storage']) for name in imports)
    text=(root/'.github/workflows/reversal-scanner-readonly.yml').read_text()
    assert 'runtime/manual_reversal_snapshot.json' in text and 'scanner-reversal-snapshots' in text
    assert 'workflow_dispatch:' in text and 'scripts/run_reversal_feed.py' in text
    publisher=(root/'scripts/run_reversal_feed.py').read_text()
    assert "item.get('execution_influence') is not False" in publisher


def test_unconfirmed_m15_close_beyond_h1_zone_quarantines_not_retires():
    z = project([zone()], 101.0)[0]
    rows = pd.DataFrame([{
        'timestamp': NOW-pd.Timedelta(minutes=15), 'open': 99.0,
        'high': 100.5, 'low': 97.2, 'close': 97.5,
    }])
    annotate_intraday_zone_risk([z], rows, 101.0)
    assert z['risk_state'] == 'PENDING_PARENT_CLOSE'
    assert z['touch_count'] == 1
    assert reversal_phase(z, candles(), 101.0, NOW)['phase'] == 'TEMBUS_SEMENTARA_TUNGGU_TF_ASAL'
    assert z['probability'] is None
    # A wick alone with the close back above invalidation is not a break.
    rows.loc[0, 'close'] = 101.0
    annotate_intraday_zone_risk([z], rows, 101.0)
    assert z['risk_state'] == 'NORMAL'


def test_repeated_m15_contact_degrades_h1_zone_without_inventing_probability():
    z = project([zone()], 101.0)[0]
    rows = pd.DataFrame([
        {'timestamp': NOW-pd.Timedelta(minutes=90-i*15),
         'open': 101., 'high': 101.5,
         'low': 99. if i in {0, 2, 4} else 100.5, 'close': 101.}
        for i in range(6)
    ]).sort_values('timestamp').reset_index(drop=True)
    annotate_intraday_zone_risk([z], rows, 101.0)
    assert z['touch_count'] == 3
    assert z['lifecycle'] == 'DEGRADED'
    assert z['risk_state'] == 'REPEATED_TESTS'
    assert z['probability'] is None


def test_h2_derived_only_from_two_completed_adjacent_h1_candles():
    base=pd.Timestamp('2026-10-15T10:00Z')
    rows=[
        {'timestamp':(base+pd.Timedelta(hours=k)).isoformat(),
         'open':100.+k, 'high':101.+k, 'low':99.+k, 'close':100.5+k}
        for k in [0,1,2,3]]
    derived=derive_h2_from_h1(rows,base+pd.Timedelta(hours=4))
    assert len(derived)==2
    assert derived[0]['timestamp']==base.isoformat()
    assert derived[0]['low']==99. and derived[0]['high']==102.
    assert len(derive_h2_from_h1(rows,base+pd.Timedelta(hours=3)))==1
    missing=[x for x in rows if x['timestamp'] != (base+pd.Timedelta(hours=1)).isoformat()]
    assert len(derive_h2_from_h1(missing,base+pd.Timedelta(hours=4)))==1


def test_h12_derived_only_from_three_closed_h4_bars():
    base=pd.Timestamp('2026-10-15T00:00Z')
    rows=[{'timestamp':(base+pd.Timedelta(hours=4*k)).isoformat(),
           'open':100.,'high':102.,'low':98.,'close':101.} for k in range(6)]
    assert len(derive_h12_from_h4(rows,base+pd.Timedelta(hours=24)))==2
    missing=rows[:2]+rows[3:]
    assert len(derive_h12_from_h4(missing,base+pd.Timedelta(hours=24)))==1


def test_h2_promotes_only_with_overlapping_h1_support():
    z=project([zone(),zone('H2',low=99.,high=101.),zone('H4',low=95.,high=97.)],102.1)
    f=candles()
    f['H2']=frame([{'timestamp':NOW-pd.Timedelta(hours=2),
                    'open':102., 'high':103., 'low':101., 'close':102.1}], 'H2', NOW)
    p=build_plans(z,f,102.1,NOW)[0]
    assert p['anchor']['timeframe']=='H2'
    assert p['contexts_htf']['H4']['timeframe']=='H4'
    z2=project([zone(),zone('H2',low=90.,high=92.)],102.1)
    assert build_plans(z2,f,102.1,NOW)[0]['anchor']['timeframe']=='H1'


def test_degraded_h2_does_not_replace_h1():
    z=project([zone(),zone('H2',low=99.,high=101.,touch_count=3,lifecycle='DEGRADED')],102.1)
    f=candles()
    f['H2']=frame([{'timestamp':NOW-pd.Timedelta(hours=2),
                    'open':102.,'high':103.,'low':101.,'close':102.1}], 'H2', NOW)
    assert build_plans(z,f,102.1,NOW)[0]['anchor']['timeframe']=='H1'


def test_new_high_timeframe_bars_must_be_closed_and_are_read_only():
    now=pd.Timestamp('2026-10-19T14:30Z')
    for tf, mins in [('D1',1440),('W1',10080)]:
        last={'timestamp':(now-pd.Timedelta(minutes=mins-10)).isoformat(),
              'open':100.,'high':101.,'low':99.,'close':100.}
        assert frame([last],tf,now).empty
    assert 'D1' in __import__('fx_scanner.manual_reversal_map',fromlist=['MINUTES']).MINUTES
    assert 'W1' in __import__('fx_scanner.manual_reversal_map',fromlist=['MINUTES']).MINUTES
