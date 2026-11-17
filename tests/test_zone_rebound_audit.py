from pathlib import Path
import sys
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from research.zone_rebound.audit import outcome, confirmed_pivots, select, confluence_count, MIN


def tape():
    t=np.arange(70,dtype=np.int64)*MIN;o=np.full(70,100.);h=o+.05;l=o-.05;c=o.copy()
    return t,o,h,l,c


def test_touch_bar_extremes_cannot_count_as_a_bounce():
    t,o,h,l,c=tape();h[0]=101.
    q=outcome(t,o,h,l,c,0,100.,1,1.)
    assert q['result']=='TIMEOUT' and not q['correct']


def test_ambiguous_bar_is_adverse_first_for_both_sides():
    t,o,h,l,c=tape();h[1]=100.5;l[1]=99.5
    for side in [1,-1]:
        q=outcome(t,o,h,l,c,0,100.,side,1.)
        assert q['result']=='ADVERSE' and not q['correct']


def test_direction_is_symmetric_and_gaps_are_not_successes():
    t,o,h,l,c=tape();h[2]=100.3
    assert outcome(t,o,h,l,c,0,100.,1,1.)['correct']
    assert outcome(t,o,200-l,200-h,200-c,0,100.,-1,1.)['correct']
    t[4:]+=MIN
    assert outcome(t,o,h,l,c,0,100.,1,1.)['result']=='DATA_GAP'


def test_confirmed_pivot_appears_only_after_right_wing_closes():
    idx=pd.date_range('2020-01-01',periods=10,freq='h',tz='UTC')
    lows=[8,7,4,6,7,8,7,6,8,9];f=pd.DataFrame({'low':lows,'high':np.array(lows)+2},index=idx)
    p=confirmed_pivots(f,1)
    assert p.index[0]==idx[4] and p.price.iloc[0]==4
    assert confirmed_pivots(f.iloc[:4],1).empty
    changed=f.copy();changed.loc[idx[5]:,'low']=0.
    pd.testing.assert_frame_equal(confirmed_pivots(changed,1).loc[:idx[4]],p.loc[:idx[4]],check_freq=False)


def test_selection_is_unchanged_when_validation_outcomes_are_reversed():
    rows=[]
    for year in [2020,2023,2025]:
        for side in ['BUY','SELL']:
            for zone in ['A','B']:
                for i in range(120):
                    good=i<(80 if zone=='A' else 65)
                    rows.append(dict(zone=zone,side=side,phase='ASIA',year=year,adx=10.,slope=1.,h1=1.,h4=1.,confluence=2,premium_discount=True,correct_0_25=good,correct_0_1=good,correct_0_5=good,outcome_0_25='BOUNCE' if good else 'ADVERSE',mfe_close_atr=.3))
    e=pd.DataFrame(rows);_,a=select(e)
    changed=e.copy();changed.loc[changed.year>=2023,'correct_0_25']=~changed.loc[changed.year>=2023,'correct_0_25'];_,b=select(changed)
    assert [x['rule'] for x in a]==[x['rule'] for x in b]

def test_confluence_does_not_count_multiple_settings_of_one_family_twice():
    candidates=[('KELTNER_M15_2',100.,110.,0.,0.),('KELTNER_M15_2.5',100.05,110.05,0.,0.),('PREVIOUS_DAY_HL',100.1,110.1,0.,0.)]
    assert confluence_count(candidates,1,100.,1.)==2
    assert confluence_count(candidates,-1,110.,1.)==2
