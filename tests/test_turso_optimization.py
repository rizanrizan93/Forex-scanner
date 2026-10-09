import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
import pytest
from fx_scanner.storage import turso_usage
from fx_scanner.storage.turso_client import TursoClient


def test_optimized_indexes_preserve_constraints_and_use_order_filter():
    db=sqlite3.connect(':memory:')
    db.executescript(Path('turso/schema.sql').read_text())
    db.executescript(Path('turso/optimize.sql').read_text())
    db.execute('PRAGMA foreign_keys=ON')
    db.execute("INSERT INTO fx_symbols(symbol,base_currency,quote_currency,pip_size,tier) VALUES ('EURUSD','EUR','USD',0.0001,'A')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO fx_symbols(symbol,base_currency,quote_currency,pip_size,tier) VALUES ('EURUSD','EUR','USD',0.0001,'A')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO signals(id,symbol,direction,setup_type,state,data_coverage) VALUES ('x','UNKNOWN','LONG','x','EXECUTION_READY',1)")
    plan=db.execute("EXPLAIN QUERY PLAN SELECT observed_at FROM broker_order_events WHERE event_type='ORDER_ACCEPTED' AND accepted=1 AND observed_at>=? ORDER BY observed_at DESC LIMIT 5",['2026-10-09']).fetchall()
    assert all('SCAN broker_order_events' not in r[3] for r in plan)
    assert not db.execute("SELECT name FROM sqlite_master WHERE name='runtime_heartbeats_pkey'").fetchall()


def test_usage_combines_clients_and_flushes_without_tracking_its_own_write(monkeypatch):
    monkeypatch.setenv('TURSO_USAGE_TRACKING','1')
    turso_usage._BUCKETS.clear();turso_usage._CLIENTS.clear()
    class Client:
        endpoint='test'
        def batch(self, statements, **kwargs):self.writes=statements;self.options=kwargs
    a,b=Client(),Client()
    turso_usage.record(a,[{'rows_read':10,'rows_written':2}])
    turso_usage.record(b,[{'rows_read':4,'rows_written':0},{}])
    turso_usage.flush()
    assert b.options=={'transaction':True,'track_usage':False}
    assert b.writes[0][1][2:]==[2,3,14,2,1]
    turso_usage.flush()
    assert not turso_usage._BUCKETS
    turso_usage._CLIENTS.clear()


def test_batch_records_provider_rows_including_failed_steps(monkeypatch):
    captured=[]
    monkeypatch.setattr(turso_usage,'record',lambda client,items:captured.extend(items))
    class Transport:
        def post(self,*args,**kwargs):
            result={'cols':[],'rows':[],'affected_row_count':0,'rows_read':8,'rows_written':0}
            return SimpleNamespace(status_code=200,json=lambda:{'results':[{'type':'ok','response':{'result':{'step_results':[{},result],'step_errors':[None,None]}}}]})
    c=TursoClient('libsql://test.turso.io','token',transport=Transport())
    c.execute('SELECT 1')
    assert captured[0]['rows_read']==8
    c.batch([('SELECT 1',())],track_usage=False)
    assert len(captured)==1
