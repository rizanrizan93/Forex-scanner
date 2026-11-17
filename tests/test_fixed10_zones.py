import numpy as np
import pandas as pd
from research.zone_rebound.fixed10 import MIN, labels, formations, first_touches, release_index, macro_features, select_indices


def tape():
    idx=pd.date_range('2025-01-06',periods=242,freq='min',tz='UTC')
    return pd.DataFrame(dict(open=100.,high=100.1,low=99.9,close=100.,spread=.5),index=idx)


def event(side=1):
    return pd.DataFrame([dict(i=0,side=side,reference=100.,spread=.5)])


def test_fixed_dollar_target_not_atr_and_touch_extreme_ignored():
    d=tape();d.loc[d.index[0],'high']=115
    assert not labels(d,event())['H240_A10'][0]
    d.loc[d.index[3],'high']=110
    assert labels(d,event())['H60_A10'][0]
    assert not labels(d,event(),cost=True)['H60_A10'][0]


def test_same_bar_adverse_first_and_wider_budget_separate():
    d=tape();d.loc[d.index[2],['low','high']]=[89.,111.]
    out=labels(d,event())
    assert not out['H60_A10'][0] and out['H60_A20'][0]


def test_mirror_buy_sell_and_complete_window_even_for_early_win():
    d=tape();d.loc[d.index[1],'high']=111
    mirror=d.copy();mirror['high']=200-d.low;mirror['low']=200-d.high
    assert labels(d,event())['H240_A10'][0]
    assert labels(mirror,event(-1))['H240_A10'][0]
    broken=d.drop(d.index[100]);out=labels(broken,event())
    assert out['H60_A10'][0] and not out['H240_A10'][0]


def test_fred_release_lags_respect_us_holiday_and_dst():
    # July4 holiday: Thursday July2 +2 federal business days is Tuesday July7.
    assert release_index(['2026-07-02'])[0]==pd.Timestamp('2026-07-07 21:00Z')
    assert release_index(['2026-01-05'])[0]==pd.Timestamp('2026-01-07 22:00Z')
    assert release_index(['2026-01-05'],broad=True)[0]==pd.Timestamp('2026-01-19 22:00Z')


def test_eur_close_only_after_minute_finishes_and_no_macro_lookahead():
    idx=pd.date_range('2025-01-06',periods=100,freq='min',tz='UTC')
    eur=pd.DataFrame({'close':1+np.arange(100)/10000},index=idx)
    t=idx[70].value;e=pd.DataFrame(dict(time_ns=[t],side=[1]))
    fred=pd.DataFrame({'observation_date':pd.date_range('2024-11-01',periods=90).strftime('%Y-%m-%d')})
    for k in ['DFII10','DGS2','DGS10','DTWEXBGS']:fred[k]=np.arange(90,dtype=float)
    a=macro_features(e.copy(),eur,fred)
    changed=eur.copy();changed.loc[idx[70]:,'close']+=500
    later=fred.copy();later.loc[later.observation_date>='2025-01-04',['DFII10','DGS2','DGS10','DTWEXBGS']]+=500
    b=macro_features(e.copy(),changed,later)
    pd.testing.assert_frame_equal(a,b)


def test_future_price_cannot_change_published_zone_geometry():
    idx=pd.date_range('2025-01-01',periods=300,freq='15min',tz='UTC');c=100+4*np.sin(np.arange(300)/7)
    f=pd.DataFrame(dict(open=c-.1,high=c+.6,low=c-.6,close=c+.1),index=idx)
    a=formations(f,15);cut=idx[230];other=f.copy();other.loc[cut:,'high']+=100;other.loc[cut:,'close']+=50
    b=formations(other,15)
    aa=a[a.pub_ns<cut.value].reset_index(drop=True);bb=b[b.pub_ns<cut.value].reset_index(drop=True)
    assert len(aa)>0;pd.testing.assert_frame_equal(aa,bb)
    # A pivot is not visible until the second candle to its right has closed.
    piv=a[a.family=='CONFIRMED_PIVOT'];assert ((piv.pub_ns-piv.origin_ns)==3*15*MIN).all()


def test_first_return_no_origin_touch_and_distal_gap_rejected():
    d=tape();d.loc[d.index[2],'low']=94
    z=pd.DataFrame([dict(pub_ns=d.index[1].value,origin_ns=d.index[0].value,tf=15,side=1,lo=90.,hi=95.,family='X',strength=1.)])
    e,_=first_touches(d,z);assert e.i.tolist()==[2]
    d.loc[d.index[2],'open']=89
    e,a=first_touches(d,z);assert not len(e) and a['gap_through_distal']==1


def test_cooldown_prospective_four_hours_and_two_per_day():
    q=pd.DataFrame(dict(time_ns=np.arange(10)*60*MIN,day=[1]*10))
    assert select_indices(q,np.ones(10,bool)).tolist()==[0,4]


def test_rule_selection_does_not_use_2025_outcomes(monkeypatch):
    from research.zone_rebound import fixed10 as mod
    monkeypatch.setattr(mod,'REGIMES',('ALL',));monkeypatch.setattr(mod,'MACROS',('NONE',))
    rows=[]
    for family in ['A','B']:
        for year,n in [(2020,160),(2023,120),(2025,120)]:
            for j in range(n):
                t=pd.Timestamp(f'{year}-01-01',tz='UTC').value+j*1440*MIN
                row=dict(family=family,tf=15,side=1,phase='ASIA',year=year,day=t//(1440*MIN),time_ns=t,
                         target_minutes=30.,mae_before_target=2.,mfe_240=12.,complete_60=True,complete_240=True)
                for sc in mod.SCENARIOS:row[sc]=j%10<(7 if family=='A' else 6);row[sc+'_timeout']=False
                rows.append(row)
    e=pd.DataFrame(rows);_,a,_=mod.search(e);changed=e.copy()
    for sc in mod.SCENARIOS:changed.loc[changed.year==2025,sc]=~changed.loc[changed.year==2025,sc]
    _,b,_=mod.search(changed)
    assert [x['rule'] for x in a]==[x['rule'] for x in b]
