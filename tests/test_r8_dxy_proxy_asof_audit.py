"""R8 causal DXY provenance tests: synthetic fixtures only, no performance claims."""
import hashlib
import pandas as pd
import pytest
from research.zone_rebound.r8_dxy_proxy_asof_audit import inspect_dxy_csv,event_direction

def fixture(tmp_path):
    t=pd.date_range('2026-11-19 00:00:00+00:00',periods=180,freq='min')
    d=pd.DataFrame({'timestamp':[x.isoformat() for x in t],
                    'open':[100+i*.001 for i in range(len(t))],
                    'high':[100.01+i*.001 for i in range(len(t))],
                    'low':[99.99+i*.001 for i in range(len(t))],
                    'close':[100+i*.001 for i in range(len(t))]})
    p=tmp_path/'dollaridxusd.csv';d.to_csv(p,index=False)
    return p,d

def test_provenance_and_point_in_time(tmp_path):
    p,d=fixture(tmp_path)
    sha=hashlib.sha256(p.read_bytes()).hexdigest()
    report,frames=inspect_dxy_csv(p,observed_at='2026-11-19 03:00:00+00:00',
                                  source_url='https://datafeed.dukascopy.com/example',
                                  sha256=sha)
    assert report['sha256']==sha
    assert report['proxy_not_ice_dxy'] is True
    assert report['complete_bars']['60']==3
    events=[{'timestamp':'2026-11-19 02:37:00+00:00','side':'BUY'}]
    out=event_direction(events,frames)
    assert out[0]['dxy_5m_asof']=='2026-11-19T02:35:00+00:00'
    assert out[0]['dxy_15m_asof']=='2026-11-19T02:30:00+00:00'
    assert out[0]['dxy_60m_asof']=='2026-11-19T02:00:00+00:00'

def test_wrong_sha_rejected(tmp_path):
    p,_=fixture(tmp_path)
    with pytest.raises(ValueError,match='SHA256'):
        inspect_dxy_csv(p,observed_at='2026-11-19 03:00:00+00:00',
                        source_url='https://datafeed.dukascopy.com/example',sha256='0'*64)

def test_stale_rejected(tmp_path):
    p,_=fixture(tmp_path)
    with pytest.raises(ValueError,match='stale'):
        inspect_dxy_csv(p,observed_at='2026-11-19 04:00:00+00:00',
                        source_url='https://datafeed.dukascopy.com/example')

def test_missing_minute_not_used_for_complete_tf(tmp_path):
    p,d=fixture(tmp_path)
    d=d.drop(index=120)
    d.to_csv(p,index=False)
    report,frames=inspect_dxy_csv(p,observed_at='2026-11-19 03:00:00+00:00',
                                  source_url='https://datafeed.dukascopy.com/example')
    assert report['non_contiguous_m1_intervals']==1
    assert report['complete_bars']['60']==2
