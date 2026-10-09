"""Frozen XAU DEMO execution with durable, at-most-once child reservations."""
import os
import math
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from time import monotonic, sleep
from uuid import uuid4
import pandas as pd
from .xau_frozen_dd50 import SYMBOL, STRATEGY_ID, POLICY_HASH, manifest, geometry, layers
from .execution.control_plane import ControlPlaneGate, ControlPlaneRefreshWorker
from .execution.demo_autotrade import SupabaseOrderAuditSink
from .execution.factory import build_broker_gateway
from .execution.models import ExecutionMode, OrderIntent, OrderSide, OrderType
from .execution.policy import load_execution_policy
from .execution.router import ExecutionRouter
from .storage.supabase_operational import SupabaseOperationalStore
from .demo_structural_profit_protector import _close_full_position

# Preserve the dashboard freshness/bridge contract; strategy identity is explicit.
WORKER = 'ctrader_demo_xau_v351_executor'
LABEL = 'RZXA50'
STATE_WORKER = 'ctrader_demo_xau_frozen_dd50'
class DurableState:
    def __init__(self, store, account, now):
        self.store, self.key = store, f'{STATE_WORKER}_state_{account}'
        rows = store.client.table('runtime_heartbeats').select('*').eq('worker_name',self.key).execute().data
        if rows:
            row = rows[0]
        else:
            state = {'policy_hash':POLICY_HASH,'daily_counts':{},
                'activated_at':now.isoformat(),'attempts':{},'last_signal':None,'quarantined':False}
            row = {'worker_name':self.key,'observed_at':now.isoformat(),'healthy':True,'lag_seconds':0.,'details':state}
            # Unique worker PK makes competing initialization fail closed.
            store.client.table('runtime_heartbeats').insert(row).execute()
        self.version, self.data = row['observed_at'], deepcopy(row['details'])
        if self.data.get('policy_hash') != POLICY_HASH:
            raise RuntimeError('FROZEN_POLICY_HASH_MISMATCH')
        self.token = uuid4().hex
        lease = self.data.get('lease_until')
        if lease and pd.Timestamp(lease)>pd.Timestamp(now):
            raise RuntimeError('XAUUSD_STATE_LEASE_BUSY')
        self.data['lease_token'] = self.token
        self.save()

    def save(self, release=False):
        now = datetime.now(UTC)
        self.data['lease_until'] = None if release else (now+timedelta(minutes=3)).isoformat()
        result = self.store.client.table('runtime_heartbeats').update(
            {'observed_at':now.isoformat(),'healthy':True,'details':deepcopy(self.data)}
            ).eq('worker_name',self.key).eq('observed_at',self.version).execute()
        if len(result.data or []) != 1:
            raise RuntimeError('XAUUSD_STATE_CAS_CONFLICT')
        self.version = result.data[0]['observed_at']


def usd_contract(session):
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAAssetListReq
    trader = session.trader()
    req = ProtoOAAssetListReq(); req.ctidTraderAccountId = int(session.account_id)
    res = session._send_sync(req,client_msg_id='xau-dd50-assets-'+uuid4().hex)
    currency = next((x.name for x in res.asset if x.assetId==trader.depositAssetId),None)
    info = session.symbol_info(SYMBOL)
    if currency != 'USD' or int(info.lotSize) != 10000 or int(info.minVolume)>100 or 100%int(info.stepVolume):
        raise RuntimeError('XAU_FROZEN_REQUIRES_USD_100OZ_CONTRACT_AND_ONE_OZ_CHILD')
    return info


def candidate_from_heartbeat(store, now):
    rows = store.client.table('runtime_heartbeats').select('*').eq(
        'worker_name','ctrader_demo_xau_sd_liquidity_v342').execute().data
    if not rows:
        raise RuntimeError('FROZEN_CORE_HEARTBEAT_MISSING')
    row = rows[0]
    if not row['healthy'] or not 0 <= (pd.Timestamp(now)-pd.Timestamp(row['observed_at'])).total_seconds() <= 60:
        raise RuntimeError('FROZEN_CORE_HEARTBEAT_STALE')
    core = row['details'].get('evaluation',{}).get('frozen_core',{})
    if core.get('policy_hash') != POLICY_HASH or core.get('strategy_id') != STRATEGY_ID:
        raise RuntimeError('FROZEN_CORE_IDENTITY_MISMATCH')
    return core


def cycle(store, gateway, session, base_policy, control, gate, now):
    manifest()
    info = usd_contract(session)
    durable = DurableState(store,session.account_id,now)
    state = durable.data
    details = {'symbol':SYMBOL,'strategy_id':STRATEGY_ID,'policy_hash':POLICY_HASH,
        'execution_scope':'DEMO_ONLY','live_execution_enabled':False,
        'git_sha':os.getenv('GITHUB_SHA','UNKNOWN'),'state':'WAIT','reason':'NO_FRESH_SIGNAL',
        'activated_at':state['activated_at'],'accepted_children':0}
    try:
        if any(x.get('outcome') is None for x in state.get('attempts',{}).values()):
            state['quarantined']=True
        reconciled = session.reconcile()
        owned = [p for p in reconciled.position if p.tradeData.symbolId==info.symbolId and str(p.tradeData.label)==LABEL]
        for p in owned:
            expiry = state.get('expires_at')
            if not expiry:
                raise RuntimeError('FROZEN_POSITION_EXPIRY_STATE_MISSING')
            if pd.Timestamp(now)>=pd.Timestamp(expiry):
                status, reason = _close_full_position(session,position_id=int(p.positionId),raw_volume=int(p.tradeData.volume))
                if status != 'CLOSED':
                    state['quarantined']=True
                    raise RuntimeError('XAU_EXIT_'+status+':'+reason)
            elif not getattr(p,'stopLoss',0) or not getattr(p,'takeProfit',0):
                state['quarantined']=True
                raise RuntimeError('XAU_EXISTING_PROTECTION_MISSING')
        if state['quarantined']:
            details.update(state='BLOCKED',reason='UNCERTAIN_ATTEMPT_QUARANTINE')
            return details
        core = candidate_from_heartbeat(store,now)
        candidate = core.get('candidate')
        details.update(state=core['state'],reason=core['reason'],candidate=candidate)
        if core['state'] != 'READY' or not candidate:
            return details
        at = pd.Timestamp(candidate['at'])
        if not 0 <= (pd.Timestamp(now)-at).total_seconds() <= 60:
            details.update(state='WAIT',reason='SIGNAL_EXPIRED')
            return details
        if state.get('last_signal')==candidate['at']:
            details.update(state='WAIT',reason='SIGNAL_ALREADY_CONSUMED')
            return details
        day = at.tz_convert('Asia/Jakarta').date().isoformat()
        if state['daily_counts'].get(day,0)>=6:
            details.update(state='WAIT',reason='MAX_SIX_SETUPS_WIB_DAY')
            return details
        rec = session.reconcile()
        # The replay assumes a single flat USD account. Never mix exposure or
        # close positions owned by EURUSD, the old engine, or manual trading.
        if rec.position or rec.order:
            details.update(state='WAIT',reason='ACCOUNT_POSITION_OR_ORDER_ACTIVE')
            return details
        gate.assert_orders_allowed('AUTO')
        snapshot = gateway.account_snapshot()
        quote = gateway.market_quote(SYMBOL)
        entry,stop,target,distance = geometry(candidate,float(quote.bid),float(quote.ask))
        if abs(float(quote.bid)-candidate['reference_bid']) > distance*.03:
            details.update(state='WAIT',reason='SIGNAL_QUOTE_DRIFT')
            return details
        side = OrderSide.BUY if candidate['side']==1 else OrderSide.SELL
        margin_res = session.expected_margin(int(info.symbolId),100)
        if not margin_res.margin:
            raise RuntimeError('XAU_EXPECTED_MARGIN_MISSING')
        first = margin_res.margin[0]
        broker_margin = float(first.buyMargin if side==OrderSide.BUY else first.sellMargin)/10**int(margin_res.moneyDigits)
        margin_child = max(entry/100,broker_margin)
        used_margin = snapshot.equity-snapshot.margin_free if snapshot.margin_free is not None else snapshot.equity
        k = layers(snapshot.balance,snapshot.equity,distance,margin_child,snapshot.margin_free or 0.,used_margin)
        details.update(equity=snapshot.equity,balance=snapshot.balance,planned_children=k,
            planned_total_lot=k*.01,entry=entry,sl=stop,tp=target,broker_margin_per_child=broker_margin,
            desired_children=max(1,int(snapshot.balance//100)),expires_at=candidate['expires_at'])
        if k<1:
            details.update(state='WAIT',reason='BUDGET_BELOW_ONE_CHILD')
            return details
        policy = replace(base_policy,mode=ExecutionMode.AUTO,
            order={**base_policy.order,'comment_prefix':LABEL,'max_signal_age_seconds':60},
            demo_safety={**base_policy.demo_safety,'max_risk_pct':12.5,'max_order_lots':.01,
                'max_concurrent_positions':gateway.position_count()+k})
        router = ExecutionRouter(policy,gateway=gateway,session=session,control_gate=gate,
            audit_sink=SupabaseOrderAuditSink(store))
        state['last_signal']=candidate['at']
        state['expires_at']=candidate['expires_at']
        state['daily_counts']={day:state['daily_counts'].get(day,0)+1}
        state['attempts']={}
        durable.save()
        total_risk,total_margin=0.,0.
        for child in range(k):
            rec=session.reconcile()
            if any(p.tradeData.symbolId!=info.symbolId or str(p.tradeData.label)!=LABEL for p in rec.position) or rec.order:
                details['reason']='EXTERNAL_EXPOSURE_DURING_BATCH'
                break
            current=gateway.account_snapshot()
            if not math.isfinite(current.equity) or current.equity<=0:
                details['reason']='ACCOUNT_EQUITY_INVALID'
                break
            q=gateway.market_quote(SYMBOL)
            live=float(q.ask if side==OrderSide.BUY else q.bid)
            if abs(live-entry)>distance*.03 or not 0<=q.ask-q.bid<=1.5:
                details.update(state='WAIT',reason='CHILD_BATCH_QUOTE_DRIFT_OR_SPREAD')
                break
            child_risk=abs(live-stop)+.05
            cap=min(snapshot.equity,current.equity)
            if total_risk+child_risk>cap*.125+1e-8 or used_margin+total_margin+margin_child>cap*.5+1e-8:
                details['reason']='CHILD_BATCH_BUDGET_LIMIT'
                break
            if current.margin_free is None or current.margin_free<margin_child:
                details['reason']='BROKER_FREE_MARGIN_LIMIT'
                break
            signal_id=f'XA50:{int(at.timestamp())}:{child:03d}'
            state['attempts'][signal_id]={'outcome':None,'at':datetime.now(UTC).isoformat()}
            durable.save()
            intent=OrderIntent(signal_id,SYMBOL,side,OrderType.MARKET,at.to_pydatetime(),.01,
                live,stop,target,child_risk/current.equity*100,comment='DEMO_AUTO:XAU_DD50_FROZEN')
            try:
                control.refresh_once()
                receipt=router.execute(intent)
            except Exception:
                state['quarantined']=True
                durable.save()
                raise
            state['attempts'][signal_id].update(outcome='ACCEPTED' if receipt.accepted else 'REJECTED',broker_order_id=receipt.broker_order_id)
            durable.save()
            if not receipt.accepted:
                details['reason']=receipt.message
                break
            total_risk+=child_risk; total_margin+=margin_child
            details['accepted_children']+=1
            details.update(state='ORDER_ACCEPTED',reason=receipt.message)
            store.record_order_event(backend='CTRADER',account_id=str(session.account_id),
                signal_key=signal_id,event_type='DEMO_XAU_FROZEN_CHILD',
                broker_order_id=receipt.broker_order_id,accepted=True,code=STRATEGY_ID,
                message=receipt.message,payload={**details,'child_index':child,'child_lot':.01})
        return details
    finally:
        durable.save(release=True)

def run():
    if os.getenv('CTRADER_DEMO_XAU_FROZEN_ENABLED')!='1':
        raise SystemExit('XAUUSD_FROZEN_DISABLED')
    base=load_execution_policy(None)
    if base.ctrader.get('environment')!='DEMO' or not base.ctrader.get('require_demo'):
        raise SystemExit('XAUUSD_DEMO_ONLY')
    store=SupabaseOperationalStore.from_env(execution_ready_score_floor=65.)
    gateway,session=build_broker_gateway(base,(SYMBOL,),backend='CTRADER')
    gate=ControlPlaneGate(max_age_seconds=5.)
    control=ControlPlaneRefreshWorker(store,gate,interval_seconds=1.)
    duration=min(330,max(1,int(os.getenv('XAUUSD_FROZEN_RUN_SECONDS','1'))))
    end=monotonic()+duration
    failures=0
    try:
        control.refresh_once();control.start()
        while True:
            now=datetime.now(UTC)
            try:
                details=cycle(store,gateway,session,base,control,gate,now)
                healthy=True
            except Exception as exc:
                failures+=1;healthy=False
                details={'symbol':SYMBOL,'strategy_id':STRATEGY_ID,'policy_hash':POLICY_HASH,
                    'git_sha':os.getenv('GITHUB_SHA','UNKNOWN'),'state':'ERROR_FAIL_CLOSED',
                    'reason':f'{type(exc).__name__}:{exc}','live_execution_enabled':False}
            store.write_heartbeat(WORKER,healthy=healthy,lag_seconds=0.,details=details)
            print('XAUUSD_FROZEN_DD50 '+str(details),flush=True)
            if monotonic()>=end:
                break
            # Align next cycle to the following minute, with a 2-second completion buffer.
            sleep(min(max(1,62-datetime.now(UTC).second),max(0,end-monotonic())))
        return 0 if failures==0 else 2
    finally:
        control.stop(timeout=2.)
        session.close()

if __name__=='__main__':
    raise SystemExit(run())
