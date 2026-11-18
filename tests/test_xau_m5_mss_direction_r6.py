"""R6 M5 event timing, sweep geometry, no-lookahead and no broker hooks."""
import numpy as np
import pandas as pd
import pytest
from research.zone_rebound.xau_m5_mss_direction_r6 import (
    MODES,CONFIRMS,HORIZONS,policies,_sweep_masks,_events,_attach_outcome,
    replay_year,aggregate,EXECUTION_AUTHORITY,EXECUTION_INFLUENCE)

def m5_sweep(side):
    idx=pd.date_range('2025-01-06T00:05:00Z',periods=24,freq='5min')
    m=pd.DataFrame({'open':10.,'high':10.1,'low':9.9,'close':10.},index=idx)
    i=19
    if side==1:
        m.loc[idx[i],['open','high','low','close']]=[10.,10.2,9.0,10.]
        m.loc[idx[i+1],['open','high','low','close']]=[10.,10.6,10.0,10.5]
    else:
        m.loc[idx[i],['open','high','low','close']]=[10.,11.,9.8,10.]
        m.loc[idx[i+1],['open','high','low','close']]=[10.,10.,9.4,9.5]
    return m,idx[i],idx[i+1]

@pytest.mark.parametrize('side',[1,-1])
def test_causal_sweep_and_confirmation(side):
    m,sweep,confirmation=m5_sweep(side)
    buys,sells=_sweep_masks(m,'SWEEP12')
    assert bool((buys if side==1 else sells)[19])
    a=_events(m,'SWEEP12','RECLAIM_CLOSE')
    assert any((a.entry_ns==sweep.value)&(a.side==side))
    b=_events(m,'SWEEP12','MSS3')
    assert any((b.entry_ns==confirmation.value)&(b.side==side))

def test_future_bar_change_does_not_change_earlier_signal():
    m,sweep,confirm=m5_sweep(1)
    before=_events(m,'SWEEP12','RECLAIM_CLOSE')
    b=m.copy();b.iloc[21:,:]=[10.,50.,1.,45.]
    after=_events(b,'SWEEP12','RECLAIM_CLOSE')
    k=sweep.value
    p=before[before.entry_ns<=k][['entry_ns','side','sweep_ns']].reset_index(drop=True)
    q=after[after.entry_ns<=k][['entry_ns','side','sweep_ns']].reset_index(drop=True)
    pd.testing.assert_frame_equal(p,q)

def test_entry_at_m5_completion_next_m1_not_sweep_time():
    m,sweep,confirm=m5_sweep(1)
    a=_events(m,'SWEEP12','MSS3')
    assert (a.entry_ns>=a.sweep_ns).all()
    assert bool((a.entry_ns==confirm.value).any())

def test_missing_m1_price_is_not_counted():
    idx=pd.date_range('2025-01-06T00:00:00Z',periods=400,freq='min')
    x=np.arange(400,dtype=float)*.001+10.
    d=pd.DataFrame({'open':x,'high':x+.1,'low':x-.1,'close':x},index=idx)
    e=pd.DataFrame({'entry_ns':[idx[50].value],'side':[1],'sweep_ns':[idx[49].value]})
    ok=_attach_outcome(d,e,60)
    assert bool(ok.complete.iloc[0])
    bad=_attach_outcome(d.drop(idx[85]),e,60)
    assert not bool(bad.complete.iloc[0])
    assert np.isnan(bad.delta.iloc[0])

def test_replay_contract_and_no_live_authority():
    assert len(policies())==72
    assert HORIZONS==(60,240)
    assert EXECUTION_AUTHORITY is False and EXECUTION_INFLUENCE is False
    with pytest.raises(ValueError,match='COMPLETE_2019_2026'):
        aggregate([])
