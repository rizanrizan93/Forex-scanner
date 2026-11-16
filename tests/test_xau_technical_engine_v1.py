from datetime import UTC, datetime, timedelta
from math import sin, pi
from copy import deepcopy
from fx_scanner.xau_technical_engine_v1 import evaluate_technical, sequence, compare_macro
from fx_scanner.xau_decision_checklist_v1 import CANDLE_CONTRACT
NOW=datetime(2026,11,16,4,tzinfo=UTC)


def fixture():
    f={'contract':CANDLE_CONTRACT,'symbol':'XAUUSD','account_suffix':'7903',
       'source':'CTRADER_MARKET_DATA_READ_ONLY','execution_authority':False,
       'execution_influence':False,'as_of':NOW.isoformat(),'bars':{}}
    for tf,n,span in [('H1',210,3600),('M15',70,900),('M5',30,300)]:
        rows=[]
        for i in range(n):
            price=80+i*.2+2*sin(i*pi/4) if tf=='H1' else 112
            rows.append({'open':price,'close':price+.2,'high':price+1,'low':price-1,
                         'closed_at':(NOW-timedelta(seconds=(n-1-i)*span)).isoformat()})
        f['bars'][tf]=rows
    # Wide M15 range provides discount location and opposing liquidity.
    for b in f['bars']['M15']:
        b.update(open=112,close=112,high=130,low=100)
    vals=[(102,104,100,102)]*25+[(100,101,98,100.5),(100,107,100,106),(106,108,104,107),(106,108,104.5,107),(103,106,102,104.5)]
    for b,(o,h,l,c) in zip(f['bars']['M5'],vals):
        b.update(open=o,high=h,low=l,close=c)
    return f


def test_buy_full_chain_and_levels():
    r=evaluate_technical(fixture(),now=NOW)
    assert r['BUY']['passed']==6, r['BUY']
    assert r['direction']=='BUY'
    p=r['BUY']['plan']
    assert p['invalidation']<p['reference_close']<p['target_liquidity']
    assert p['rr_before_costs']>=2
    assert not r['execution_authority']


def test_sell_mirror_chain():
    f=fixture()
    for rows in f['bars'].values():
        for b in rows:
            o,h,l,c=[b[k] for k in ('open','high','low','close')]
            b.update(open=300-o,high=300-l,low=300-h,close=300-c)
    r=evaluate_technical(f,now=NOW)
    assert r['direction']=='SELL',r['SELL']


def test_stale_forming_wrong_source_and_gap_fail_closed():
    for mutation in ('stale','forming','source','gap','nan'):
        f=fixture()
        if mutation=='stale': f['as_of']=(NOW-timedelta(hours=1)).isoformat()
        if mutation=='forming': f['bars']['M5'][-1]['closed_at']=(NOW+timedelta(minutes=5)).isoformat()
        if mutation=='source': f['source']='UNVERIFIED'
        if mutation=='gap': f['bars']['M5'][-1]['closed_at']=(NOW-timedelta(minutes=5)).isoformat()
        if mutation=='nan': f['bars']['M5'][-1]['close']=float('nan')
        r=evaluate_technical(f,now=NOW)
        assert r['direction']=='WAIT'
        assert r['BUY']['state']=='WAIT_DATA'
        assert all(x['state']=='UNKNOWN' for x in r['BUY']['items'])


def test_invalidated_sweep_and_no_retest_block_setup():
    for low,close in [(97,104.5),(105,106)]:
        f=fixture()
        f['bars']['M5'][-1].update(low=low,open=105 if low==105 else 103,close=close)
        r=evaluate_technical(f,now=NOW)
        assert r['direction']=='WAIT'
        assert r['BUY']['plan'] is None


def test_macro_cannot_promote_incomplete_technical():
    assert compare_macro({'direction':'WAIT'},{'usd_direction':'UP_WATCH'}, {'state':'CONCORDANT_PROXY','yield_direction':'UP'}).startswith('WAIT')
    assert compare_macro({'direction':'BUY'},{'usd_direction':'UP_WATCH'}, {'state':'CONCORDANT_PROXY','yield_direction':'UP'}).startswith('KONFLIK')
    assert compare_macro({'direction':'SELL'},{'usd_direction':'UP_WATCH'}, {'state':'CONCORDANT_PROXY','yield_direction':'UP'}).startswith('SELARAS')
    assert compare_macro({'direction':'SELL'},{'usd_direction':'UP_WATCH'}, {'state':'ZN_PROXY_ONLY','yield_direction':'UP'}).startswith('WAIT')


def test_setup_expires_at_next_m5_close_even_if_transport_still_fresh():
    r=evaluate_technical(fixture(),now=NOW+timedelta(minutes=5))
    assert r['direction']=='WAIT'
    assert r['BUY']['plan'] is None


def test_boundary_wait_keeps_valid_h1_without_reusing_old_m5_setup():
    f = fixture()
    f['as_of'] = (NOW+timedelta(minutes=5)).isoformat()
    r = evaluate_technical(f, now=NOW+timedelta(minutes=5, seconds=30))
    assert r['BUY']['state'] == 'WAIT_CANDLE'
    assert r['BUY']['items'][0]['state'] == 'PASS'
    assert all(x['state'] == 'UNKNOWN' for x in r['BUY']['items'][1:])
    assert r['direction'] == 'WAIT'
    assert r['BUY']['plan'] is None
    # A prolonged collection failure is still a genuine data outage.
    r = evaluate_technical(f, now=NOW+timedelta(minutes=7))
    assert r['BUY']['state'] == 'WAIT_DATA'
    assert r['BUY']['plan'] is None


def test_higher_timeframes_use_actual_session_bars_without_gap_fill():
    f=fixture()
    for tf in ('H1','M15'):
        for b in f['bars'][tf][:-10]:
            b['closed_at']=(datetime.fromisoformat(b['closed_at'])-timedelta(days=2)).isoformat()
    r=evaluate_technical(f,now=NOW)
    assert r['direction']=='BUY'
    assert not r['errors']
