from pathlib import Path
import sys
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from research.zone_rebound.exhaustion_r2 import label, prospective_indices, area_events, context, confirmed_events


def tape():
    idx=pd.date_range('2025-01-06',periods=90,freq='min',tz='UTC');o=np.full(90,100.)
    return pd.DataFrame({'open':o,'high':o+.02,'low':o-.02,'close':o,'spread':.1},index=idx)


def event(kind='CONFIRMED',side=1):
    return pd.DataFrame([dict(i=0,side=side,atr_h1=1.,reference=100.,kind=kind)])


def test_same_bar_ambiguity_is_adverse_first_and_area_touch_high_is_ignored():
    d=tape();d.iloc[0,d.columns.get_loc('high')]=100.3
    assert label(d,event())['STRICT'][0]
    assert not label(d,event('AREA'))['STRICT'][0]
    d.iloc[0,d.columns.get_loc('low')]=99.7
    assert not label(d,event())['STRICT'][0]


def test_buy_sell_symmetry_and_complete_window_required_even_for_early_winner():
    d=tape();d.iloc[2,d.columns.get_loc('high')]=100.3
    assert label(d,event())['STRICT'][0]
    mirror=d.copy();mirror['high']=200-d.low;mirror['low']=200-d.high;mirror['close']=200-d.close
    assert label(mirror,event(side=-1))['STRICT'][0]
    d=d.drop(d.index[35]);assert not label(d,event())['complete'][0]
    assert not label(d,event())['STRICT'][0]


def test_wider_adverse_budget_is_distinct_from_immediately_correct_direction():
    d=tape();d.iloc[1,d.columns.get_loc('low')]=99.6;d.iloc[2,d.columns.get_loc('high')]=100.3
    out=label(d,event());assert not out['STRICT'][0] and out['WIDE'][0]


def test_cooldown_and_daily_limit_do_not_depend_on_outcome():
    q=pd.DataFrame({'time_ns':np.arange(8)*30*60_000_000_000,'day':[1]*8,'future_win':[False,True]*4})
    assert prospective_indices(q,np.ones(8,bool)).tolist()==[0,2]
    q.future_win=~q.future_win
    assert prospective_indices(q,np.ones(8,bool)).tolist()==[0,2]


def test_candidate_features_do_not_change_when_future_candles_change():
    idx=pd.date_range('2025-01-01',periods=16000,freq='min',tz='UTC');c=2000+3*np.sin(np.arange(len(idx))/30)+np.sin(np.arange(len(idx))/7)
    d=pd.DataFrame({'open':c,'high':c+.7,'low':c-.7,'close':c+.1,'spread':.3},index=idx)
    a=confirmed_events(d,context(d),5);cut=idx[-500]
    changed=d.copy();changed.loc[cut:,'high']+=100;changed.loc[cut:,'low']-=100;changed.loc[cut:,'close']+=50
    b=confirmed_events(changed,context(changed),5)
    names=['time_ns','side','family','stretch','rsi_fast','rsi_h1','adx','slope']
    aa=a[a['time_ns']<cut.value][names].sort_values(['time_ns','side','family']).reset_index(drop=True)
    bb=b[b['time_ns']<cut.value][names].sort_values(['time_ns','side','family']).reset_index(drop=True)
    assert len(aa)>0
    pd.testing.assert_frame_equal(aa,bb)


def test_2025_outcomes_do_not_influence_rule_selection(monkeypatch):
    from research.zone_rebound import exhaustion_r2 as mod
    monkeypatch.setattr(mod,'EXTENSIONS',(0.,));monkeypatch.setattr(mod,'RSI_FILTERS',('NONE',));monkeypatch.setattr(mod,'REGIMES',('ALL',));monkeypatch.setattr(mod,'SESSIONS',('ALL',))
    rows=[]
    for family in ['A','B']:
        for yr,n in [(2020,160),(2023,120),(2025,120)]:
            for j in range(n):
                at=pd.Timestamp(f'{yr}-01-01',tz='UTC').value+j*1440*60_000_000_000
                good=j%10<(7 if family=='A' else 6)
                row=dict(kind='CONFIRMED',tf=1,family=family,side=1,stretch=1.,rsi_fast=25.,rsi_h1=25.,adx=10.,slope=.1,phase='ASIA',year=yr,day=at//(1440*60_000_000_000),time_ns=at,complete=True,mfe_60_atr=.5,mae_60_atr=.5,bounce_already_atr=.1)
                for scenario in mod.SCENARIOS:row[scenario]=good;row[scenario+'_timeout']=False
                rows.append(row)
    e=pd.DataFrame(rows);_,a=mod.search(e)
    other=e.copy()
    for scenario in mod.SCENARIOS:other.loc[other.year==2025,scenario]=~other.loc[other.year==2025,scenario]
    _,b=mod.search(other)
    assert [x['rule'] for x in a]==[x['rule'] for x in b]


def test_pre_touch_features_do_not_use_the_touch_candle_close(tmp_path):
    idx=pd.date_range('2025-01-01',periods=16000,freq='min',tz='UTC');c=2000+3*np.sin(np.arange(len(idx))/30)
    d=pd.DataFrame({'open':c,'high':c+.2,'low':c-.2,'close':c+.05,'spread':.3},index=idx);touch=idx[-5]
    p=tmp_path/'areas.csv';pd.DataFrame([dict(zone='TEST',side='BUY',phase='ASIA',touch=touch.isoformat(),year=2025,entry_reference=2000.,atr_h1=3.)]).to_csv(p,index=False)
    a=area_events(d,context(d),p)
    changed=d.copy();changed.loc[touch:,'close']+=500;changed.loc[touch:,'high']+=500
    b=area_events(changed,context(changed),p)
    fields=['stretch','rsi_fast','rsi_h1','adx','slope']
    pd.testing.assert_frame_equal(a[fields],b[fields])
