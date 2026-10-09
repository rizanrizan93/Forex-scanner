"""Read broker truth and operational events without placing or amending orders."""
import json, io
from contextlib import redirect_stdout
from datetime import datetime, timezone
from fx_scanner.execution.policy import load_execution_policy
from fx_scanner.execution.factory import build_broker_gateway
from fx_scanner.demo_broker_pnl import capture_ctrader_demo_snapshot
from fx_scanner.storage.supabase_operational import SupabaseOperationalStore

policy=load_execution_policy(None)
assert policy.ctrader['environment']=='DEMO' and policy.ctrader['require_demo']
store=SupabaseOperationalStore.from_env()
gateway,session=build_broker_gateway(policy,('EURUSD','XAUUSD'),backend='CTRADER')
try:
 with redirect_stdout(io.StringIO()):
  snap=capture_ctrader_demo_snapshot(session=session,store=store,phase='ORDER_PROTECTION_AUDIT')
 rows=[]
 for p in snap.positions:
  if p.symbol not in {'EURUSD','XAUUSD'}: continue
  rows.append({'symbol':p.symbol,'side':str(p.side),'entry':p.open_price,'sl':p.stop_loss,'tp':p.take_profit,'protected':bool(p.stop_loss and p.take_profit),'scanner_owned':str(p.comment or '').startswith(('DEMO_AUTO:','FXIS:'))})
 now=datetime.now(timezone.utc)
 events=store.client.table('broker_order_events').select('observed_at,event_type,accepted,broker_order_id,payload').eq('event_type','ORDER_ACCEPTED').eq('accepted',True).gte('observed_at','2026-10-09T02:42:00+00:00').order('observed_at',desc=True).limit(100000).execute().data
 accepted=[e for e in events if e.get('accepted') and e.get('broker_order_id') and e['event_type']=='ORDER_ACCEPTED']
 summary={'observed_at':now.isoformat(),'demo_only':True,'open_positions':rows,'accepted_orders_since_migration':len({e['broker_order_id'] for e in accepted}), 'latest_accepted_orders':[{'observed_at':e['observed_at'],'symbol':(e.get('payload') or {}).get('symbol'),'entry':(e.get('payload') or {}).get('executed_price'),'sl':(e.get('payload') or {}).get('attached_stop_loss'),'tp':(e.get('payload') or {}).get('attached_take_profit')} for e in accepted[:5]]}
 store.write_heartbeat('ctrader_demo_order_protection_audit',healthy=all(r['protected'] for r in rows),lag_seconds=0.,details=summary)
 print('BROKER_ORDER_PROTECTION_AUDIT '+json.dumps(summary,default=str))
finally:
 session.close()
