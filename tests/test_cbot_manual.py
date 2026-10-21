from datetime import datetime,UTC,timedelta
from copy import deepcopy
from unittest.mock import patch
import pytest
from fx_scanner.cbot_manual import project,validate,HASHES,macro_reason
NOW=datetime(2026,10,21,12,0,10,tzinfo=UTC)
def fixture():
 at=NOW.replace(second=0).isoformat();old=(NOW-timedelta(days=1)).isoformat()
 c={'symbol':'XAUUSD','bar_at':at,'session_open':True,'areas':[{'side':'BUY','low':4100.,'high':4100.,'condition':'Reclaim'}],'signal':{'at':at,'side':'BUY','atr':2.,'anchor':4098.,'distance':0},'target_r':5.5,'stop_atr':2.4,'depths':[0,.2,.4],'addition_confirmation':True}
 m={'as_of':NOW.isoformat(),'account_binding':'same-private-binding','quotes':{'XAUUSD':{'BID':{'price':4105.,'at':NOW.isoformat()},'ASK':{'price':4105.2,'at':NOW.isoformat()}}},'positions':[]}
 n={'as_of':NOW.isoformat(),'account_binding':'same-private-binding','states':{'XAUUSD':{'ContractHash':HASHES['XAUUSD'],'LastBarUtc':at}},'macro':{'ProducedUtc':NOW.isoformat(),'ForexFactoryOk':True,'BlsOk':True,'CoverageFromUtc':old,'CoverageToUtc':(NOW+timedelta(days=1)).isoformat(),'Dfii10':{'AvailableUtc':old,'Delta':-.01},'Dgs10':{'AvailableUtc':old,'Delta':.01},'Events':[]}}
 return c,m,n
def test_fx_levels_use_execution_cost_and_structural_stop():
 c,m,n=fixture();p=project([c],m,n,now=NOW);r=p['symbols'][0]
 assert r['status']=='ENTRY_MANUAL';assert r['entry']==pytest.approx(4105.3)
 assert r['sl']==4098.;assert r['tp']==pytest.approx(4105.3+7.3*5.5)
 assert r['layers'][1]['confirmation']
 assert p['execution_authority'] is False and p['execution_influence'] is False
 assert c['signal']['anchor']==4098. # projection never mutates inputs

def test_expiry_is_rechecked_when_dashboard_rerenders_cached_payload():
 c,m,n=fixture();p=project([c],m,n,now=NOW);r=validate(p,now=NOW+timedelta(seconds=51))['symbols'][0]
 assert r['status']=='WAIT' and r['entry'] is None and r['signal'] is None

def test_stale_publication_hides_prices_and_positions():
 c,m,n=fixture();p=project([c],m,n,now=NOW);q=validate(p,now=NOW+timedelta(minutes=2))
 assert not q['fresh'];assert not q['symbols'][0]['areas'];assert q['symbols'][0]['entry'] is None

def test_macro_gate_blocks_sell_against_negative_dgs10():
 c,m,n=fixture();c['signal'].update(side='SELL',anchor=4110.)
 n['macro']['Dgs10']['Delta']=-.01
 r=project([c],m,n,now=NOW)['symbols'][0];assert r['status']=='BLOCK';assert 'yield' in r['reason']

def test_news_and_missing_checkpoint_do_not_become_entry():
 c,m,n=fixture();n['states']={};n['macro']['Events']=[{'Category':'CPI','AtUtc':(NOW+timedelta(hours=1)).isoformat()}]
 r=project([c],m,n,now=NOW)['symbols'][0];assert r['status']=='BLOCK';assert 'Berita besar' in r['reason']

def test_cbot_position_is_not_displayed_as_new_entry():
 c,m,n=fixture();m['positions']=[dict(symbol='XAUUSD',side='BUY',entry=4100.,sl=4090.,tp=4155.)]
 r=project([c],m,n,now=NOW)['symbols'][0];assert r['status']=='POSISI_AKTIF' and r['entry'] is None

def test_immutable_source_manifest():
 from scripts.run_cbot_manual import verify
 verify()

def test_reader_denies_every_order_message():
 from scripts.collect_cbot_manual import Reader
 from types import SimpleNamespace
 reader=object.__new__(Reader)
 for name in ['ProtoOANewOrderReq','ProtoOAAmendPositionSLTPReq','ProtoOACancelOrderReq','ProtoOAClosePositionReq']:
  with pytest.raises(RuntimeError,match='READ_ONLY_PROTOCOL_GUARD'):reader._send_sync(SimpleNamespace(DESCRIPTOR=SimpleNamespace(name=name)))

def test_cbots_tab_is_lazy_and_zone_tab_stays_clean():
 from pathlib import Path
 from streamlit.testing.v1 import AppTest
 from fx_scanner import cbot_manual_dashboard as panel
 p=project([],{'as_of':datetime.now(UTC).isoformat()},{},now=datetime.now(UTC))
 def fake_fetch():return p
 with patch.object(panel,'fetch',new=fake_fetch),patch('runpy.run_path') as run:
  app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'main.py'));app.session_state['rizan_pair']='cBots';app.run(timeout=15)
  assert not app.exception;assert any(t.label=='cBots' for t in app.tabs);run.assert_not_called()
  assert not app.expander;assert any('cBots' in h.value for h in app.subheader)


def test_mismatched_account_and_foreign_exposure_block_manual_entry():
 c,m,n=fixture();m['account_binding']='different';m['foreign_exposure']=True
 r=project([c],m,n,now=NOW)['symbols'][0]
 assert r['status']=='BLOCK' and 'akun yang sama' in r['reason'] and 'posisi asing' in r['reason']


def test_btc_five_second_signal_is_never_relabelled_fresh():
 c,m,n=fixture();c.update(symbol='BTCUSD',bar_at=NOW.replace(second=0).isoformat());c['signal'].update(atr=100,distance=200,anchor=80000)
 r=project([c],m,n,now=NOW)['symbols'][0]
 assert r['signal'] is None and r['entry'] is None and 'sudah lewat' in r['reason']


def test_raw_transport_timeout_uses_contents_api_fallback():
 from fx_scanner import cbot_manual_dashboard as panel
 import base64,json
 c,m,n=fixture();p=project([c],m,n,now=NOW)
 meta={'encoding':'base64','content':base64.b64encode(json.dumps(p).encode()).decode()}
 def read(url):
  if url.startswith(panel.BASE):raise OSError('timed out')
  return meta
 panel._api_snapshot.cache_clear()
 with patch.object(panel,'read_json',side_effect=read):
  q=panel.fetch();assert q['contract']==p['contract']
 panel._api_snapshot.cache_clear()


def test_stale_watch_reference_is_labeled_but_never_an_entry():
 c,m,n=fixture();p=project([c],m,n,now=NOW)
 q=validate(p,now=NOW+timedelta(minutes=2));r=q['symbols'][0]
 assert r['reference_areas'] and not r['areas'] and r['entry'] is None
 q=validate(p,now=NOW+timedelta(minutes=11))
 assert not q['symbols'][0]['reference_areas']
