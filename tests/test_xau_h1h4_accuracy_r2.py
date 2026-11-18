"""Focused R2 causal research tests; no LIVE system imports."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest
from research.zone_rebound.h1h4_accuracy_r2 import (
    FEATURES,make_features,synthetic_tape,EXECUTION_AUTHORITY,EXECUTION_INFLUENCE)
from scripts.research_xau_h1h4_accuracy_r2 import (
    propose,evaluate,wilson,load_dataset,MIN_VAL)

def tape():
    return synthetic_tape(60*24*32)

def test_two_horizons_and_features_are_finite_for_some_rows():
    d=tape()
    h1=make_features(d,2024,60)
    h4=make_features(d,2024,240)
    assert len(h1)>50 and len(h4)>20
    assert set(FEATURES).issubset(h1)
    assert h1['complete'].sum()>50 and h4['complete'].sum()>20
    assert h1.timeframe.eq(60).all() and h4.timeframe.eq(240).all()

def test_future_candles_cannot_change_a_prior_signal_feature():
    d=tape();cut=pd.Timestamp('2024-01-22T00:00:00Z')
    before=make_features(d,2024,60)
    changed=d.copy();sel=changed.index>cut
    changed.loc[sel,['open','high','low','close']]+=500
    after=make_features(changed,2024,60)
    old=before[before.timestamp<=cut.value//60_000_000_000]
    new=after[after.timestamp<=cut.value//60_000_000_000]
    pd.testing.assert_frame_equal(old[['timestamp']+FEATURES],new[['timestamp']+FEATURES])

def test_h1_and_h4_gaps_censored_not_wins():
    d=tape()
    x=make_features(d,2024,60)
    lost_ts=pd.Timestamp('2024-01-20T10:20:00Z')
    broken=make_features(d.drop(lost_ts),2024,60)
    affected=broken[broken.timestamp==pd.Timestamp('2024-01-20T10:00Z').value//60_000_000_000]
    assert len(affected)==1 and not bool(affected.complete.iloc[0])
    assert pd.isna(affected.gross_forward_usd.iloc[0])
    # Source H1 candle with one M1 missing can never be published.
    missing_bar_end=pd.Timestamp('2024-01-20T11:00Z').value//60_000_000_000
    assert missing_bar_end not in set(broken.timestamp)

def test_side_gating_wait_vs_buy_sell():
    df=pd.DataFrame({
        'h4_ema20_slope':[2.,-2.,2.],
        'h4_ema20_dev':[2.,-2.,-2.],
        'tf_ema20_slope':[2.,-2.,0.],
        'tf_return3':[2.,-2.,0.],
        'tf_adx':[.5,.5,.5]})
    p=np.array([.75,.25,.51])
    assert propose(df,p,.6,'ALL').tolist()==[1,-1,0]
    assert propose(df,p,.6,'HTF_ALIGN').tolist()==[1,-1,0]
    assert propose(df,p,.6,'TF_MOMENTUM').tolist()==[1,-1,0]
    assert propose(df,np.array([.75,.25,.85]),.6,'HTF_ALIGN').tolist()==[1,-1,0]

def test_same_bar_direction_after_cost_and_n():
    df=pd.DataFrame({'year':[2024,2024,2024,2024],
        'complete':[True,True,False,True],
        'gross_forward_usd':[1.,-1.,np.nan,.1]})
    out=evaluate(df,np.array([1,-1,1,1]),(2024,))
    assert out['buy']['signals']==3
    assert out['buy']['evaluated']==2
    assert out['buy']['wins']==1
    assert out['sell']['wins']==1

def test_wilson_and_complete_eight_years():
    assert wilson(6,10)<.6
    with pytest.raises(ValueError,match='EIGHT_YEAR'):load_dataset([])

def test_never_executes():
    assert EXECUTION_AUTHORITY is False and EXECUTION_INFLUENCE is False
    assert MIN_VAL[60]>=25
