from pathlib import Path
import tempfile
import pandas as pd
import pytest
from normalize_bid_ask import normalize_bid_ask

def test_bid_ask_join_and_manifest():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)
        t=pd.date_range('2026-04-01',periods=1500,freq='min',tz='UTC')
        bid=pd.DataFrame({'timestamp':t,'open':1.10,'high':1.11,'low':1.09,'close':1.10})
        ask=bid.copy()
        for c in ('open','high','low','close'):ask[c]+=0.0002
        bid.to_csv(p/'bid.csv',index=False);ask.to_csv(p/'ask.csv',index=False)
        q=normalize_bid_ask(p/'bid.csv',p/'ask.csv',p/'out.csv','2026-04-01','2026-04-03')
        assert q['data_ready'] and q['rows']==1500
        assert abs(q['mean_spread_open']-.0002)<1e-9
        assert (pd.read_csv(p/'out.csv').spread>=0).all()

def test_mismatching_bid_ask_fail_closed():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)
        x={'timestamp':['2026-04-01T00:00:00Z'],'open':[1.1],'high':[1.2],'low':[1.0],'close':[1.1]}
        pd.DataFrame(x).to_csv(p/'bid.csv',index=False)
        x['timestamp']=['2026-04-01T00:01:00Z']
        pd.DataFrame(x).to_csv(p/'ask.csv',index=False)
        with pytest.raises(ValueError,match='No matching'):
            normalize_bid_ask(p/'bid.csv',p/'ask.csv',p/'out.csv','2026-04-01','2026-04-03')
