"""DEMO-only forward lane for the frozen EURUSD DD37 candidate.

Durable CAS state is separate from telemetry. Every child is marked attempted
before crossing the broker boundary; interrupted/uncertain attempts quarantine
new entries and are never resubmitted blindly.
"""
import os
from . import frozen_layering as layering
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from time import monotonic, sleep
from uuid import uuid4
import pandas as pd

from .eurusd_frozen_dd37 import POLICY, POLICY_HASH, STRATEGY_ID, SYMBOL, advance_virtual, features, frame_from_bars, layers, multiplier, signal
from .execution.control_plane import ControlPlaneGate, ControlPlaneRefreshWorker
from .execution.demo_autotrade import SupabaseOrderAuditSink
from .execution.factory import build_broker_gateway
from .execution.models import ExecutionMode, OrderIntent, OrderSide, OrderType
from .execution.policy import load_execution_policy
from .execution.router import ExecutionRouter
from .storage.supabase_operational import SupabaseOperationalStore
from .demo_structural_profit_protector import _close_full_position

WORKER = 'ctrader_demo_eurusd_frozen_dd37'
LABEL = 'RZEU37'

class DurableState:
    def __init__(self, store, account, now):
        self.store, self.key = store, f'{WORKER}_state_{account}'
        rows = store.client.table('runtime_heartbeats').select('*').eq('worker_name',self.key).execute().data
        if rows:
            row = rows[0]
        else:
            state = {'policy_hash':POLICY_HASH,'fast':0.,'slow':0.,'cursor':
                (pd.Timestamp(now).floor('min')-pd.Timedelta(minutes=1)).isoformat(),
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
            raise RuntimeError('EURUSD_STATE_LEASE_BUSY')
        self.data['lease_token'] = self.token
        self.save()

    def save(self, release=False):
        now = datetime.now(UTC)
        self.data['lease_until'] = None if release else (now+timedelta(minutes=3)).isoformat()
        result = self.store.client.table('runtime_heartbeats').update(
            {'observed_at':now.isoformat(),'healthy':True,'details':deepcopy(self.data)}
            ).eq('worker_name',self.key).eq('observed_at',self.version).execute()
        if len(result.data or []) != 1:
            raise RuntimeError('EURUSD_STATE_CAS_CONFLICT')
        self.version = result.data[0]['observed_at']

def usd_contract(session):
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAAssetListReq
    trader = session.trader()
    req = ProtoOAAssetListReq(); req.ctidTraderAccountId = int(session.account_id)
    res = session._send_sync(req,client_msg_id='eurusd-assets-'+uuid4().hex)
    currency = next((x.name for x in res.asset if x.assetId==trader.depositAssetId),None)
    if currency != 'USD':
        raise RuntimeError('EURUSD_FROZEN_REQUIRES_USD_ACCOUNT')
    info = session.symbol_info(SYMBOL)
    if int(info.lotSize) != 10000000:
        raise RuntimeError('EURUSD_CONTRACT_SIZE_NOT_100000')
    return trader, info

def matching_positions(reconciled, symbol_id):
    return [p for p in reconciled.position if p.tradeData.symbolId==symbol_id]

def manage_exits(session, positions, now, state):
    for p in positions:
        if str(p.tradeData.label) != LABEL:
            continue
        opened = pd.Timestamp(int(p.tradeData.openTimestamp),unit='ms',tz='UTC')
        old_cursor = pd.Timestamp(state['cursor'])
        # Server SL/TP stay active; timeout/gap closes only this strategy's EURUSD.
        basket_expiry=(state.get('layering_basket') or {}).get('expires_at')
        timed_out = (pd.Timestamp(now)>=opened+pd.Timedelta(minutes=240) or now.hour>=20
            or bool(basket_expiry and pd.Timestamp(now)>=pd.Timestamp(basket_expiry)))
        gap = state.get('gap_detected',False)
        if timed_out or gap:
            status, reason = _close_full_position(session,position_id=int(p.positionId),raw_volume=int(p.tradeData.volume))
            if status != 'CLOSED':
                state['quarantined']=True
                raise RuntimeError('EURUSD_EXIT_'+status+':'+reason)
        elif not getattr(p,'stopLoss',0) or not getattr(p,'takeProfit',0):
            raise RuntimeError('EURUSD_EXISTING_PROTECTION_MISSING')

def cycle(store, gateway, session, base_policy, control, gate, now):
    trader, info = usd_contract(session)
    durable = DurableState(store,session.account_id,now)
    state = durable.data
    details = {'symbol':SYMBOL,'strategy_id':STRATEGY_ID,'policy_hash':POLICY_HASH,
        'policy':asdict(POLICY),'execution_scope':'DEMO_ONLY','live_execution_enabled':False,
        'git_sha':os.getenv('GITHUB_SHA','UNKNOWN'),'state':'WAIT','reason':'NO_FRESH_SWEEP',
        'activated_at':state['activated_at'],'accepted_children':0,
        'layering_policy_hash':layering.HASHES[SYMBOL],
        'layering_configuration':layering.manifest(SYMBOL)['contract']['configuration']}
    try:
        attempts = state.get('attempts',{})
        if any(x.get('outcome') is None for x in attempts.values()):
            state['quarantined']=True
        raw = frame_from_bars(session.historical_bars(SYMBOL,'M1',
            from_time=now-timedelta(days=12),to_time=now,count=18000),now)
        cursor = pd.Timestamp(state['cursor'])
        if cursor < raw.index[0]-pd.Timedelta(minutes=5):
            state['quarantined']=True
            raise RuntimeError('EURUSD_VIRTUAL_HISTORY_GAP_RECOVERY_REQUIRED')
        following = raw[raw.index>cursor]
        state['gap_detected'] = bool(len(following) and (following.index[0]-cursor).total_seconds()>300)
        if len(following)>1:
            state['gap_detected'] |= bool((following.index.to_series().diff().dt.total_seconds()>300).any())
        reconciled = session.reconcile()
        positions = matching_positions(reconciled,int(info.symbolId))
        manage_exits(session,positions,now,state)
        feature_frame = features(raw,state)
        advance_virtual(raw,feature_frame,state)
        details.update(fast_ema_r=state['fast'],slow_ema_r=state['slow'],
            sizing_multiplier=multiplier(state['fast'],state['slow']),last_completed_m1=str(raw.index[-1]))
        durable.save()
        monitored=layering.monitor(state,durable,session,gateway,SYMBOL,LABEL,int(info.symbolId),now,details,gate=gate)
        at = pd.Timestamp(now).floor('15min')
        if state['quarantined']:
            details.update(state='BLOCKED',reason='UNCERTAIN_ATTEMPT_QUARANTINE')
            return details
        if monitored:
            return details
        if at not in feature_frame.index or not (0 <= (pd.Timestamp(now)-at).total_seconds() < 60):
            details['reason']='WAIT_NEXT_M15_OPEN_WINDOW'
            return details
        candidate = signal(at,feature_frame.loc[at])
        details['candidate']=candidate or {}
        if candidate is None:
            return details
        if state.get('last_signal') == candidate['at']:
            details['reason']='SIGNAL_ALREADY_CONSUMED'
            return details
        exposure=session.reconcile()
        positions = matching_positions(exposure,int(info.symbolId))
        if exposure.position or exposure.order:
            details['reason']='EURUSD_BASKET_OR_EXTERNAL_ORDER_ACTIVE'
            return details
        gate.assert_orders_allowed('AUTO')
        snapshot = gateway.account_snapshot()
        quote = gateway.market_quote(SYMBOL)
        if quote.ask-quote.bid > .00022:
            details['reason']='EURUSD_SPREAD_ABOVE_STRESS_2_2_PIPS'
            return details
        side = OrderSide.BUY if candidate['side']==1 else OrderSide.SELL
        entry = float(quote.ask if side==OrderSide.BUY else quote.bid)
        distance = candidate['distance']
        stop, target = entry-candidate['side']*distance,entry+candidate['side']*distance*4
        margin_res = session.expected_margin(int(info.symbolId),100000)
        if not margin_res.margin:
            raise RuntimeError('EURUSD_EXPECTED_MARGIN_MISSING')
        first = margin_res.margin[0]
        broker_margin = float(first.buyMargin if side==OrderSide.BUY else first.sellMargin)/10**int(margin_res.moneyDigits)
        margin_child = max(entry*10,broker_margin)
        k = layers(snapshot.equity,entry,distance,state['fast'],state['slow'],
            margin_per_child=margin_child,free_margin=snapshot.margin_free)
        basket=layering.plan(SYMBOL,balance=snapshot.balance,equity=snapshot.equity,
            free_margin=snapshot.margin_free or 0.,baseline_children=k,entry=entry,stop=stop,target=target,
            margin_child=margin_child,spread=float(quote.ask-quote.bid),
            used_margin=max(0.,snapshot.equity-(snapshot.margin_free or 0.)),scale=multiplier(state['fast'],state['slow']),
            now=now,expires_at=(at+pd.Timedelta(minutes=240)).isoformat())
        k=basket['initial_children']
        details['layering']=basket
        details.update(equity=snapshot.equity,balance=snapshot.balance,planned_children=k,
            planned_total_lot=k*.01,entry=entry,sl=stop,tp=target,broker_margin_per_child=broker_margin)
        if k<1:
            details['reason']='BUDGET_BELOW_ONE_CHILD'
            return details
        scale = multiplier(state['fast'],state['slow'])
        # Only this local EURUSD router receives the frozen pair-specific limits.
        policy = replace(base_policy,mode=ExecutionMode.AUTO,
            order={**base_policy.order,'comment_prefix':LABEL,'max_signal_age_seconds':60},
            demo_safety={**base_policy.demo_safety,'max_risk_pct':27.25,'max_order_lots':.01,
                'max_concurrent_positions':gateway.position_count()+k})
        router = ExecutionRouter(policy,gateway=gateway,session=session,control_gate=gate,
            audit_sink=SupabaseOrderAuditSink(store))
        state['last_signal']=candidate['at']
        state['attempts']={}
        state['layering_basket']=basket
        durable.save()
        total_risk, total_margin = 0.,0.
        for child in range(k):
            # Recheck real account room and quote before each actual .01-lot child.
            current = gateway.account_snapshot()
            q = gateway.market_quote(SYMBOL)
            live = float(q.ask if side==OrderSide.BUY else q.bid)
            if abs(live-entry)>distance*.03 or q.ask-q.bid>.00022:
                details['reason']='CHILD_BATCH_QUOTE_DRIFT_OR_SPREAD'
                break
            child_risk = 1000*(abs(live-stop)+POLICY.virtual_slip)
            if total_risk+child_risk>min(snapshot.equity,current.equity)*POLICY.risk*scale+1e-8 or total_margin+margin_child>min(snapshot.equity,current.equity)*POLICY.margin*scale+1e-8:
                details['reason']='CHILD_BATCH_BUDGET_LIMIT'
                break
            if current.margin_free is None or current.margin_free < margin_child:
                details['reason']='BROKER_FREE_MARGIN_LIMIT'
                break
            signal_id=f'EU37:{int(at.timestamp())}:{child:03d}'
            state['attempts'][signal_id]={'outcome':None,'at':datetime.now(UTC).isoformat()}
            durable.save()  # Irreversible boundary reservation; no blind retry.
            intent=OrderIntent(signal_id,SYMBOL,side,OrderType.MARKET,at.to_pydatetime(),.01,
                live,stop,target,child_risk/current.equity*100,comment='DEMO_AUTO:EURUSD_DD37_FROZEN')
            try:
                control.refresh_once()
                receipt=router.execute(intent)
            except Exception:
                state['quarantined']=True
                durable.save()
                raise
            state['attempts'][signal_id]['outcome']='ACCEPTED' if receipt.accepted else 'REJECTED'
            state['attempts'][signal_id]['broker_order_id']=receipt.broker_order_id
            durable.save()
            if not receipt.accepted:
                details['reason']=receipt.message
                break
            total_risk+=child_risk;total_margin+=margin_child
            details['accepted_children']+=1
            basket['initial_accepted']+=1
            durable.save()
            details.update(state='ORDER_ACCEPTED',reason=receipt.message)
            store.record_order_event(backend='CTRADER',account_id=str(session.account_id),
                signal_key=signal_id,event_type='DEMO_EURUSD_FROZEN_CHILD',
                broker_order_id=receipt.broker_order_id,accepted=True,code=STRATEGY_ID,
                message=receipt.message,payload={**details,'child_index':child,'child_lot':.01})
        layering.submit_limits(state=state,durable=durable,session=session,gateway=gateway,store=store,
            base_policy=base_policy,control=control,gate=gate,symbol=SYMBOL,label=LABEL,
            symbol_id=int(info.symbolId),at=at,details=details)
        details['planned_children']=basket['total_children']
        details['planned_total_lot']=basket['total_children']*.01
        return details
    finally:
        durable.save(release=True)

def run():
    if os.getenv('CTRADER_DEMO_EURUSD_FROZEN_ENABLED')!='1':
        raise SystemExit('EURUSD_FROZEN_DISABLED')
    base=load_execution_policy(None)
    if base.ctrader.get('environment')!='DEMO' or not base.ctrader.get('require_demo'):
        raise SystemExit('EURUSD_DEMO_ONLY')
    store=SupabaseOperationalStore.from_env(execution_ready_score_floor=65.)
    gateway,session=build_broker_gateway(base,(SYMBOL,),backend='CTRADER')
    gate=ControlPlaneGate(max_age_seconds=5.)
    control=ControlPlaneRefreshWorker(store,gate,interval_seconds=1.)
    duration=min(330,max(1,int(os.getenv('EURUSD_FROZEN_RUN_SECONDS','1'))))
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
            print('EURUSD_FROZEN_DD37 '+str(details),flush=True)
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
