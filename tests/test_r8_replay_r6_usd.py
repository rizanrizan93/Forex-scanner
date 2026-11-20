import pandas as pd
import pytest
from scripts.r8_replay_r6_usd import evaluate_events,wilson,aggregate

def test_cohorts_and_buy_sell():
    e=pd.DataFrame({'entry_ns':[1,2,3,4],'side':[1,-1,1,-1],
                    'complete':[True]*4,'delta':[1,1,-1,1]})
    m=pd.DataFrame({'entry_ns':[1,2,3,4],'macro_ready':[True,True,True,False],
                    'return_5m_pct':[-.2,.3,.2,None],
                    'return_15m_pct':[-.1,.4,.2,None],
                    'return_60m_pct':[-.3,.1,.3,None]})
    z=evaluate_events(e,m,2019,60,1)
    def r(side,cohort):return next(x for x in z if x['side']==side and x['cohort']==cohort)
    assert (r('BUY','BASE_R6')['n'],r('BUY','BASE_R6')['wins'])==(2,1)
    assert (r('SELL','BASE_R6')['n'],r('SELL','BASE_R6')['wins'])==(2,2)
    assert (r('BUY','DXY_3_OF_3_ALIGNED')['n'],r('BUY','DXY_3_OF_3_ALIGNED')['wins'])==(1,1)
    assert r('SELL','DXY_AVAILABLE')['n']==1
    assert r('BUY','DXY_15_AND_60_OPPOSED')['wins']==0

def test_incomplete_forward_path_not_counted():
    e=pd.DataFrame({'entry_ns':[1,2],'side':[1,-1],'complete':[True,False],'delta':[1,100]})
    m=pd.DataFrame({'entry_ns':[1],'macro_ready':[False],'return_5m_pct':[None],
                    'return_15m_pct':[None],'return_60m_pct':[None]})
    r=evaluate_events(e,m,2026,240,1)
    assert next(x for x in r if x['cohort']=='BASE_R6' and x['side']=='SELL')['n']==0

def test_statistic_and_empty():
    assert wilson(0,0) is None
    assert 0<wilson(60,100)<.60

def test_aggregate_requires_8_shards():
    with pytest.raises(ValueError,match='EIGHT_YEAR'):aggregate([])
