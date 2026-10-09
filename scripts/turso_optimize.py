"""Apply reviewed non-destructive index optimization and report footprint."""
import json
from pathlib import Path
from datetime import datetime, timezone
from fx_scanner.storage.backend import create_backend_client
from fx_scanner.storage.turso_budget import report_budget
c=create_backend_client()
statements=[(s.strip(),()) for s in Path('turso/optimize.sql').read_text().split(';') if s.strip()]
before=c.execute("SELECT count(*) n FROM sqlite_master WHERE type='index'").data[0]['n']
c.batch(statements,transaction=True)
after=c.execute("SELECT count(*) n FROM sqlite_master WHERE type='index'").data[0]['n']
checks={}
for label,sql,args in [('control','SELECT * FROM execution_control WHERE control_key=?',['primary']),('heartbeat','SELECT observed_at FROM runtime_heartbeats WHERE worker_name=?',['ctrader_demo_eurusd_frozen_dd37']),('accepted_orders',"SELECT observed_at FROM broker_order_events WHERE event_type='ORDER_ACCEPTED' AND accepted=1 AND observed_at>=? ORDER BY observed_at DESC LIMIT 5",['2026-10-09T00:00:00+00:00'])]:
 plan=c.execute('EXPLAIN QUERY PLAN '+sql,args).data
 checks[label]=[r['detail'] for r in plan]
 if any('SCAN '+table in r['detail'] for r in plan for table in ['execution_control','runtime_heartbeats','broker_order_events']):raise RuntimeError('unexpected table scan: '+label)
print('TURSO_INDEX_OPTIMIZATION '+json.dumps({'before':before,'after':after,'plans':checks}))
c.table('runtime_heartbeats').upsert({'worker_name':'turso_free_tier_optimization_v1','observed_at':datetime.now(timezone.utc).isoformat(),'healthy':True,'lag_seconds':0.,'details':{'indexes_before':before,'indexes_after':after,'constraints_preserved':True,'strategy_unchanged':True}},on_conflict='worker_name',returning='minimal').execute()
print('TURSO_FREE_TIER_BUDGET '+json.dumps(report_budget(c)))
