"""Report only backend control and worker health, never vault contents."""
import json
from fx_scanner.storage.backend import create_backend_client
from fx_scanner.eurusd_frozen_dd37 import POLICY_HASH
c=create_backend_client()
control=c.table('execution_control').select('*').eq('control_key','primary').execute().data[0]
active=c.table('fx_symbols').select('symbol').eq('active',True).execute().data
assert {r['symbol'] for r in active}=={'EURUSD','XAUUSD'}
assert control['metadata']['demo_only'] and not control['metadata']['live_execution_enabled']
assert control['new_orders_enabled'] and not control['emergency_stop']
print('TURSO_RUNTIME_CONTROL_OK demo_only=True active_symbols=EURUSD,XAUUSD')
workers=['ctrader_demo_eurusd_frozen_dd37','ctrader_demo_xau_sd_liquidity_v342','ctrader_demo_xau_friend_entry_v343','ctrader_demo_xau_v351_executor','ctrader_demo_xau_v375_reaction_executor']
rows=c.table('runtime_heartbeats').select('*').in_('worker_name',workers).execute().data
for row in rows:
 d=row.get('details') or {}
 if row['worker_name']=='ctrader_demo_eurusd_frozen_dd37': assert d.get('policy_hash')==POLICY_HASH
 print(json.dumps({'worker':row['worker_name'],'healthy':row['healthy'],'observed_at':row['observed_at'],'state':d.get('state'),'reason':d.get('reason'),'git_sha':d.get('git_sha')}))
