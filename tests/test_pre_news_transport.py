from datetime import timedelta
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fx_scanner.pre_news_transport import CONTRACT, MAX_BYTES, fetch_pre_news_snapshot, validate_snapshot
from test_pre_news_expectation import NOW, snapshot


def payload():
    return dict(snapshot(), contract=CONTRACT, published_at=NOW.isoformat(), execution_authority=False, execution_influence=False)


def test_new_feed_does_not_require_primary_trading_heartbeat():
    data = payload()
    urls = []
    def opener(request, **kwargs):
        urls.append(request.full_url)
        return io.BytesIO(json.dumps(data).encode())
    assert fetch_pre_news_snapshot(now=NOW, opener=opener) == data
    assert len(urls) == 1
    assert 'scanner-pre-news-snapshots' in urls[0]


@pytest.mark.parametrize('change', [dict(contract='OLD'),dict(execution_authority=True),dict(execution_influence=True),dict(published_at=(NOW-timedelta(minutes=16)).isoformat())])
def test_rejects_stale_or_invalid_publication(change):
    data = payload()
    data.update(change)
    with pytest.raises(ValueError):
        validate_snapshot(data, now=NOW)


def test_stale_mutable_cdn_uses_immutable_latest_revision():
    old=payload()
    old['published_at']=(NOW-timedelta(hours=1)).isoformat()
    responses = iter([old, {'object':{'sha':'a'*40}}, payload()])
    urls=[]
    def opener(request, **kwargs):
        urls.append(request.full_url)
        return io.BytesIO(json.dumps(next(responses)).encode())
    assert fetch_pre_news_snapshot(now=NOW, opener=opener)['published_at'] == NOW.isoformat()
    assert '/'+('a'*40)+'/' in urls[-1]


def test_reject_oversized_snapshot():
    def opener(*args, **kwargs):
        return io.BytesIO(b'x'*(MAX_BYTES+1))
    with pytest.raises(ValueError, match='too large'):
        fetch_pre_news_snapshot(now=NOW, opener=opener)


def test_publisher_allowlist_keeps_source_time_and_drops_private_details():
    path=Path(__file__).resolve().parents[1]/'scripts/publish_pre_news_snapshot.py'
    spec=importlib.util.spec_from_file_location('publish_pre_news',path)
    publisher=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    rows=snapshot()['heartbeats']
    for row in rows:
        row['details']['token']='PRIVATE_SENTINEL'
        row['details']['account']='PRIVATE_SENTINEL'
    class Client:
        def table(self, name): return self
        def select(self, columns): return self
        def eq(self, key, value): self.worker=value; return self
        def order(self, *args, **kwargs): return self
        def limit(self, count): return self
        def execute(self): return SimpleNamespace(data=[r for r in rows if r['worker_name']==self.worker])
    data=publisher.build_snapshot(Client(),now=NOW)
    assert 'PRIVATE_SENTINEL' not in json.dumps(data)
    assert len(data['heartbeats'])==2
    macro=data['heartbeats'][1]['details']['evaluation']
    assert macro['components']['US2Y']['observed_at']
    assert macro['dxy_intraday']['current_at']
    from fx_scanner.pre_news_expectation import evaluate_pre_news
    assert evaluate_pre_news(data,now=NOW)['state']=='PRE_NEWS'
    # Failed Yahoo DXY can be replaced by validated complete broker-basket data.
    from fx_scanner.dxy_broker_context import evaluate_broker_dxy
    from test_dxy_broker_context import basket
    broker = evaluate_broker_dxy(now=NOW, basket=basket())
    recovered = publisher.build_snapshot(Client(), now=NOW, broker_dxy=broker)
    assert recovered['heartbeats'][1]['details']['evaluation']['dxy_intraday']['source'] == 'CTRADER_SYNTHETIC_USDX_6FX'
    assert evaluate_pre_news(recovered, now=NOW)['state'] == 'PRE_NEWS'


def test_macro_validation_has_no_execution_import_dependency():
    import subprocess, sys
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,'-c',"from fx_scanner.config import load_project_config; load_project_config(None); import sys; assert not any(n.startswith('fx_scanner.execution') for n in sys.modules)"],cwd=root,env=__import__('os').environ|{'PYTHONPATH':str(root/'src')},capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_stale_feed_returns_context_but_never_a_current_bias():
    from fx_scanner.pre_news_expectation import evaluate_pre_news
    old=payload();old['published_at']=(NOW-timedelta(hours=1)).isoformat()
    responses=iter([old,{'object':{'sha':'b'*40}},old])
    def opener(*args,**kwargs):return io.BytesIO(json.dumps(next(responses)).encode())
    out=fetch_pre_news_snapshot(now=NOW,opener=opener)
    assert out['publication_fresh'] is False
    view=evaluate_pre_news(out,now=NOW)
    assert view['state']=='DATA INCOMPLETE'
    assert view['xau_bias']=='UNAVAILABLE'
    assert view['event'] is not None
    assert 'PUBLICATION_STALE' in view['reasons']


def test_stale_context_survives_reference_network_failure():
    from urllib.error import URLError
    old=payload();old['published_at']=(NOW-timedelta(hours=1)).isoformat()
    count=[0]
    def opener(*args,**kwargs):
        count[0]+=1
        if count[0]==2:raise URLError('network unavailable')
        return io.BytesIO(json.dumps(old).encode())
    out=fetch_pre_news_snapshot(now=NOW,opener=opener)
    assert out['publication_fresh'] is False
    assert out['published_at']==old['published_at']
