import json, sqlite3
from pathlib import Path
from types import SimpleNamespace
import pytest
from fx_scanner.storage.turso_client import TursoClient, Result, Query, TursoError, scalar
from fx_scanner.storage.supabase_operational import SupabaseOperationalStore

class Local:
    def __init__(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.executescript(Path('turso/schema.sql').read_text())
        self.db.execute('PRAGMA foreign_keys=ON')
    def table(self,t):return Query(self,t)
    def batch(self,statements,transaction=False):
        out=[]
        with self.db:
            for sql,args in statements:
                args=[json.dumps(x) if isinstance(x,(list,dict)) else x for x in args]
                cursor=self.db.execute(sql,args)
                out.append(Result([dict(r) for r in cursor.fetchall()],cursor.rowcount))
        return out

def store():
    c=Local();c.db.execute("INSERT INTO execution_control(control_key) VALUES ('primary')");c.db.commit()
    return SupabaseOperationalStore('https://example.com','test',client=c)

def test_versioned_control_and_stale_lease():
    s=store();a=s.get_execution_control();assert not a.new_orders_enabled and a.emergency_stop
    b=s.set_execution_control(execution_mode='AUTO',new_orders_enabled=True,emergency_stop=False)
    assert b.version==a.version+1 and b.new_orders_enabled
    assert s.client.table('execution_control').update({'version':9}).eq('control_key','primary').eq('version',a.version).execute().data==[]

def test_json_projection_and_roundtrip():
    s=store();s.write_heartbeat('test',healthy=True,details={'evaluation':{'state':'WAIT','items':[1,2]}})
    q=s.client.table('runtime_heartbeats')
    r=q.select('worker_name,healthy,state:details->evaluation->>state,items:details->evaluation->items').execute().data[0]
    assert r=={'worker_name':'test','healthy':True,'state':'WAIT','items':[1,2]}
    assert s.client.table('runtime_heartbeats').select('details').eq('worker_name','test').execute().data[0]['details']['evaluation']['state']=='WAIT'

def test_constraints_and_atomic_batch():
    c=Local()
    rows=[{'symbol':'EURUSD','base_currency':'EUR','quote_currency':'USD','pip_size':.0001,'tier':'A'}, {'symbol':'BAD','base_currency':'X','quote_currency':'USD','pip_size':.0001,'tier':'A'}]
    with pytest.raises(sqlite3.IntegrityError):c.table('fx_symbols').insert(rows).execute()
    assert c.table('fx_symbols').select('*').execute().data==[]

def test_signal_claim_once_and_fk():
    s=store();c=s.client
    c.table('fx_symbols').insert({'symbol':'EURUSD','base_currency':'EUR','quote_currency':'USD','pip_size':.0001,'tier':'A'}).execute()
    row={'symbol':'EURUSD','direction':'LONG','setup_type':'TEST','state':'EXECUTION_READY','observed_at':'2026-01-01T00:00:00+00:00','data_coverage':1}
    id=c.table('signals').insert(row).execute().data[0]['id']
    assert s.claim_signal_for_execution(id);assert not s.claim_signal_for_execution(id)
    with pytest.raises(sqlite3.IntegrityError):c.table('signals').insert(dict(row,symbol='BAD')).execute()

def test_upsert_preserves_uuid_and_other_columns():
    c=Local();base={'worker_name':'x','observed_at':'2026-01-01T00:00:00+00:00','healthy':True,'details':{'old':1}}
    c.table('runtime_heartbeats').upsert(base,on_conflict='worker_name').execute()
    c.table('runtime_heartbeats').upsert(dict(base,details={'new':2}),on_conflict='worker_name').execute()
    assert c.table('runtime_heartbeats').select('*').execute().data[0]['details']=={'new':2}

def test_bound_parameters_and_reject_unfiltered_mutations():
    c=Local();q=c.table('runtime_heartbeats').select('worker_name').eq('worker_name',"x' OR 1=1--")
    sql,args=q.build()[0];assert '?' in sql and args==["x' OR 1=1--"]
    with pytest.raises(ValueError):c.table('signals').update({'state':'COOLDOWN'}).execute()
    with pytest.raises(ValueError):c.table('signals').select('id);DROP_TABLE').execute()

@pytest.mark.parametrize('url',['http://db.turso.io','libsql://a@db.turso.io','libsql://db.turso.io?q=1'])
def test_unsafe_url_rejected(url):
    with pytest.raises(ValueError):TursoClient(url,'token')

def test_http_protocol_and_error_redaction():
    class Transport:
        def post(self,url,headers,json):
            self.payload=json
            return SimpleNamespace(status_code=401)
    t=Transport();c=TursoClient('libsql://db.turso.io','secret',transport=t)
    with pytest.raises(TursoError,match='HTTP 401'):c.execute('SELECT ?',['secret'])
    assert t.payload['requests'][-1]['type']=='close'
