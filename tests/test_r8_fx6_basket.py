import numpy as np
import pandas as pd
import pytest
from scripts.r8_fx6_basket import WEIGHTS,CONST,reconstruct
from scripts.r8_replay_r6_usd import macro_at_events

def inputs():
    times=pd.date_range('2019-01-02T10:00:00Z',periods=66,freq='min')
    prices={'EURUSD':1.14,'USDJPY':109.0,'GBPUSD':1.28,'USDCAD':1.35,'USDSEK':8.95,'USDCHF':.99}
    return {p:pd.DataFrame({'timestamp':times.strftime('%Y-%m-%dT%H:%M:%SZ'),
                            'close':np.full(len(times),v)})
            for p,v in prices.items()}

def test_six_pair_formula_and_strict_common_index():
    v=inputs();x=reconstruct(v)
    expected=CONST*np.prod([v[p].close.iloc[0]**w for p,w in WEIGHTS.items()])
    assert len(x)==66
    assert abs(x.close.iloc[0]/expected-1)<1e-12
    assert x.timestamp.iloc[0]=='2019-01-02T10:00:00Z'

def test_no_forward_fill_of_missing_minutes():
    v=inputs();v['USDSEK']=v['USDSEK'].drop(index=[15])
    x=reconstruct(v)
    assert len(x)==65
    assert '2019-01-02T10:15:00Z' not in set(x.timestamp)

def test_absent_fx_pair_rejected():
    v=inputs();v.pop('USDCHF')
    with pytest.raises(ValueError,match='SIX_FX'):reconstruct(v)

def test_latency_avoids_current_unfinished_candle():
    v=inputs();x=reconstruct(v)
    # Existing candles through 11:05 open: last close is 11:06
    # at 11:06, 1-minute delay => last usable close at 11:05.
    t=int(pd.Timestamp('2019-01-02T11:06:00Z').value)
    e=pd.DataFrame({'entry_ns':[t]})
    f=macro_at_events(x,e,delay_minutes=1,source_contract='R8_RECONSTRUCTED_DXY_6FX_HISTDATA_V1')
    assert f.macro_ready.iloc[0]
    assert f.quote_age_minutes.iloc[0]>=1

def test_untrusted_local_timestamp_rejected():
    x=reconstruct(inputs());x.loc[0,'timestamp']='2019-01-02T10:00:00'
    t=int(pd.Timestamp('2019-01-02T11:06:00Z').value)
    with pytest.raises(ValueError,match='FX6_UTC'):macro_at_events(x,pd.DataFrame({'entry_ns':[t]}),source_contract='R8_RECONSTRUCTED_DXY_6FX_HISTDATA_V1')
