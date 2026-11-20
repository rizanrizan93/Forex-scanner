"""Causal safeguards for research-only XAU direction, no live execution."""
import numpy as np
import pandas as pd
import pytest
from research.zone_rebound.h1h4_direction_r1 import (
    validate_m1,completed_bars,candidates,apply_policy,replay,
    EXECUTION_AUTHORITY,EXECUTION_INFLUENCE)
from scripts.research_xau_h1h4_direction_r1 import aggregate,wilson_lower

def tape(n=60*350):
    t=pd.date_range('2025-01-01',periods=n,freq='min',tz='UTC')
    price=2000+np.arange(n)*.005+2*np.sin(np.arange(n)/80)
    op=price;cl=price+.04*np.sin(np.arange(n)/9)
    return pd.DataFrame({'open':op,'high':np.maximum(op,cl)+.15,
        'low':np.minimum(op,cl)-.15,'close':cl},index=t)

def test_only_complete_hour_and_missing_m1_rejected():
    d=tape(121);h=completed_bars(d,60)
    assert list(h.index)==[pd.Timestamp('2025-01-01T01:00Z'),pd.Timestamp('2025-01-01T02:00Z')]
    g=completed_bars(d.drop(d.index[17]),60)
    assert list(g.index)==[pd.Timestamp('2025-01-01T02:00Z')]

def test_duplicate_and_corrupted_candles_rejected():
    d=tape(65)
    with pytest.raises(ValueError,match='DUPLICATE'):
        validate_m1(pd.concat([d,d.iloc[:1]]))
    bad=d.copy();bad.loc[bad.index[2],'low']=bad.high.iloc[2]+1
    with pytest.raises(ValueError,match='INVALID'):
        validate_m1(bad)

def test_future_price_changes_never_repaint_prior_H1_signal():
    d=tape();cut=pd.Timestamp('2025-01-10T00:00Z')
    old=candidates(d,timeframe=60)
    assert len(old)>0
    changed=d.copy();future=changed.index>cut
    changed.loc[future,['open','high','low','close']]+=300
    new=candidates(changed,timeframe=60)
    cols=['buy_score','sell_score','buy_reason','sell_reason','h4_bull','h4_bear']
    pd.testing.assert_frame_equal(old.loc[old.index<=cut,cols],new.loc[new.index<=cut,cols])

def test_buy_sell_and_wait_symmetric():
    ts=pd.to_datetime(['2025-03-03T10:00Z','2025-03-03T11:00Z','2025-03-03T12:00Z'])
    x=pd.DataFrame({'buy_score':[6,0,5],'sell_score':[0,6,5],
        'buy_reason':['SWEEP_RECLAIM_LOW']*3,
        'sell_reason':['SWEEP_RECLAIM_HIGH']*3,
        'h4_bull':[True,False,True],'h4_bear':[False,True,False]},index=ts)
    y=apply_policy(x,threshold=4)
    assert list(y.direction)==['BUY','SELL','WAIT']
    assert list(y.side)==[1,-1,0]

def test_same_minute_both_target_and_adverse_counts_loss_for_buy_and_sell():
    d=tape(300);ts=d.index[60]
    sig=pd.DataFrame({'decision_ts':[ts],'timeframe':[60],'side':[1],
        'score':[6],'atr':[5.],'reason':['TEST']})
    d.loc[d.index[64],['high','low']]=[2030.,1970.]
    assert replay(d,sig).iloc[0]['hit10_before_adverse10']==False
    sig.loc[0,'side']=-1
    assert replay(d,sig).iloc[0]['hit10_before_adverse10']==False

def test_forward_gap_not_a_winning_trade():
    d=tape(300);ts=d.index[60]
    sig=pd.DataFrame({'decision_ts':[ts],'timeframe':[60],'side':[-1],
        'score':[6],'atr':[5.],'reason':['TEST']})
    result=replay(d.drop(d.index[65]),sig)
    assert result.status.iloc[0]=='GAP'
    assert pd.isna(result.correct_net.iloc[0])

def test_minimum_sides_and_wilson_are_conservative():
    assert wilson_lower(8,10)<.8
    assert wilson_lower(0,0)==0

def test_aggregate_requires_full_unique_2019_2026_shards():
    with pytest.raises(ValueError,match='EIGHT_UNIQUE'):aggregate([])

def test_H4_candidates_and_readonly_flags():
    h4=candidates(tape(),timeframe=240)
    assert not h4.empty and 'buy_score' in h4 and 'sell_score' in h4
    assert EXECUTION_AUTHORITY is False and EXECUTION_INFLUENCE is False
