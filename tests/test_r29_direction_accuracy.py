from datetime import UTC, datetime

import numpy as np
import pandas as pd

from r29_direction_accuracy import metrics, chronological_masks, policies


def test_conflicting_heads_are_not_counted_as_correct_predictions():
    result=metrics(np.array([1,0,1]),np.array([True,True,False]),np.array([False,True,True]))
    assert result['conflicts']==1 and result['n']==2
    assert result['BUY']['correct']==1 and result['SELL']['correct']==0
    assert result['accuracy']==.5 and result['coverage']==2/3


def test_outcomes_crossing_split_boundary_are_purged():
    times=pd.to_datetime(['2022-12-30','2022-12-31','2023-01-01','2024-12-31','2025-01-01','2025-12-31'],utc=True)
    maturity=times+pd.Timedelta(days=1)
    tr,va,refit,te=chronological_masks(times,maturity,np.ones(6,bool),2025)
    assert tr.tolist()==[True,False,False,False,False,False]
    assert va.tolist()==[False,False,True,False,False,False]
    assert te.tolist()==[False,False,False,False,True,False]
    assert not np.any(tr&va) and not np.any(va&te)
    assert all(maturity[refit]<pd.Timestamp('2025-01-01',tz='UTC'))


def test_validation_selection_can_choose_distinct_buy_sell_specialists():
    y=np.array([1]*20+[0]*20)
    buy=np.array([.8]*20+[.5]*20)
    sell=np.array([.5]*20+[.2]*20)
    selected=policies(y,{'buy_specialist':buy,'sell_specialist':sell},minimum=8)
    assert selected is not None
    assert selected['policy']['BUY']['model']=='buy_specialist'
    assert selected['policy']['SELL']['model']=='sell_specialist'
    assert selected['validation']['accuracy']==1
    assert selected['validation']['coverage']==1


def test_tiny_high_accuracy_subset_cannot_bypass_coverage_floor():
    y=np.array([1]*100+[0]*100)
    p=np.full(200,.5);p[:2]=.99;p[-2:]=.01
    selected=policies(y,{'rare':p},minimum=8)
    assert selected is None or selected['validation']['n']>=40


def test_empty_prediction_set_has_no_accuracy_claim():
    r=metrics(np.array([0,1]),np.zeros(2,bool),np.zeros(2,bool))
    assert r['accuracy'] is None and r['wilson_lower95'] is None and r['coverage']==0
