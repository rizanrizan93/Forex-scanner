"""Forward-outcome test: synthetic paths verify first-touch semantics, not alpha."""
import numpy as np
import pandas as pd
from scripts.replay_rejection_v2_outcomes import future, wilson, replay

def make(vals):
    n=len(next(iter(vals.values())))
    idx=pd.date_range('2023-09-04',periods=n,freq='min',tz='UTC')
    return pd.DataFrame(vals,index=idx)

def test_buy_target_first():
    d=make({'open':[100]*62,'high':[100]*1+[104]*60+[100],'low':[100]*62,'close':[100]*62})
    r=future(d,0,'BUY',60,3,3)
    assert r['state']=='TARGET_FIRST'

def test_sell_target_first():
    d=make({'open':[100]*62,'high':[100]*62,'low':[100]*1+[96]*60+[100],'close':[100]*62})
    r=future(d,0,'SELL',60,3,3)
    assert r['state']=='TARGET_FIRST'

def test_same_bar_is_adverse_first_conservative():
    d=make({'open':[100]*62,'high':[100]+[104]*60+[100],
            'low':[100]+[96]*60+[100],'close':[100]*62})
    assert future(d,0,'BUY',60,3,3)['state']=='ADVERSE_FIRST'
    assert future(d,0,'SELL',60,3,3)['state']=='ADVERSE_FIRST'

def test_adverse_before_target_failure():
    d=make({'open':[100]*62,'high':[100]*2+[104]*59+[100],
            'low':[100]+[96]+[100]*60,'close':[100]*62})
    assert future(d,0,'BUY',60,3,3)['state']=='ADVERSE_FIRST'

def test_missing_future_is_censored_not_winner():
    d=make({'open':[100]*62,'high':[104]*62,'low':[100]*62,'close':[100]*62})
    d=d.drop(d.index[15])
    assert future(d,0,'BUY',60,3,3) is None

def test_wilson_small_n_not_certain():
    assert wilson(1,1)[0]<50
    assert wilson(0,0)==[None,None]

def test_replay_short_source_no_false_n():
    n=4000
    ix=pd.date_range('2023-09-04',periods=n,freq='min',tz='UTC')
    x=4000+np.arange(n)*.001
    d=pd.DataFrame({'open':x-.01,'high':x+.04,'low':x-.04,'close':x},index=ix)
    r=replay(d,{'source':'SYNTHETIC'},limit=100)
    assert r['evaluated_closes']==0
    assert r['results']['EARLY_ENTRY_PROXY']['BUY']['n']==0
