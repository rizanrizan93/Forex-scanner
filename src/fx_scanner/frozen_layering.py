"""User-frozen staged DEMO baskets; no new signal family or live authority."""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import math
from pathlib import Path

from .execution.models import ExecutionMode, OrderIntent, OrderSide, OrderType
from .execution.router import ExecutionRouter
from .execution.demo_autotrade import SupabaseOrderAuditSink

HASHES = {
    'XAUUSD': '48ebaaf55e089e06f9f72573a7e6cc1c10805f85f4b5114e0f3a4e33088d6e16',
    'EURUSD': '0e14ca6e5fe16d3383ca086fc7253aca40b1f65e85c4b70e9e0385a0510c0e63',
}


def manifest(symbol, path=None):
    path = path or Path(__file__).resolve().parents[2] / 'config/frozen' / (symbol.lower()+'_layering_1m_v1.json')
    data = json.loads(Path(path).read_text())
    digest = sha256(json.dumps(data['contract'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if digest != HASHES[symbol] or data['policy_hash'] != digest or data['contract']['symbol'] != symbol:
        raise RuntimeError('LAYERING_FROZEN_HASH_MISMATCH')
    return data


def plan(symbol, *, balance, equity, free_margin, baseline_children, entry, stop, target,
         margin_child, spread, scale=1., used_margin=0., now=None, expires_at=None):
    """Allocate integer children; reserve margin even at the basket stop.

    Native limits are placed once, not resized blindly after a restart. Their
    quantities reserve conservative stop-equity margin; actual fills differ
    from the retrospective synthetic quote replay. Recompound every new basket.
    """
    frozen = manifest(symbol)
    c = frozen['contract']; cfg = c['configuration']
    numeric = (balance, equity, free_margin, entry, stop, target, margin_child, spread, scale, used_margin)
    if not all(math.isfinite(x) for x in numeric) or min(balance,equity,entry,stop,target,margin_child,scale)<=0 or free_margin<0 or spread<0:
        raise RuntimeError('LAYERING_ACCOUNT_OR_PRICE_INVALID')
    side = 1 if stop < entry < target else -1 if target < entry < stop else 0
    if not side:
        raise RuntimeError('LAYERING_GEOMETRY_INVALID')
    now = now or datetime.now(UTC)
    units = 1 if symbol == 'XAUUSD' else 1000
    slip = c['slippage_per_unit']; distance = abs(entry-stop)
    reference = min(balance,equity)
    riskcap = reference*c['risk_cap']*scale
    margincap = max(0.,min(free_margin, reference*c['margin_cap']*scale-used_margin))
    risk0 = units*(distance+slip)
    count = min(math.floor(baseline_children*cfg['equity_capacity_multiplier']),
                math.floor(riskcap/risk0+1e-9),math.floor(margincap/margin_child+1e-9))
    if symbol == 'EURUSD':
        count = min(count,math.floor(195*(reference/100)**.0625))
    budget = count*risk0 if cfg['budget']=='BASELINE_PLANNED_USD' else riskcap
    initial = min(max(1,math.floor(count*cfg['initial_fraction_of_baseline_children'])),math.floor(budget/risk0+1e-9)) if count else 0
    n = cfg['stages']; weights = [(i+1)**cfg['depth_weight_power'] for i in range(1,n)]
    remaining = max(0.,budget-initial*risk0) if initial else 0.
    # All queued layers could fill during a feed outage. Reserve margin against
    # equity at the common stop rather than treating pending orders as free.
    safe_margin = min(margincap,max(0.,(reference-budget)*c['margin_cap']*scale-used_margin))
    rows=[]; usedrisk=usedmargin=0.; total=0
    for i in range(n):
        depth = cfg['max_depth_r']*(i/(n-1))**cfg['spacing_exponent']
        price = entry if i==0 else entry-side*depth*distance+side*slip
        risk = units*(side*(price-stop)+slip)
        allocation = initial*risk0 if i==0 else remaining*weights[i-1]/sum(weights)
        wanted = initial if i==0 else math.floor(allocation/risk+1e-9)
        hardcap = math.floor(195*(reference/100)**.0625) if symbol=='EURUSD' else 2**31-1
        qty = max(0,min(wanted,hardcap-total,math.floor(max(0.,budget-usedrisk)/risk+1e-9),
            math.floor(max(0.,safe_margin-usedmargin)/margin_child+1e-9)))
        if i==0 and qty<1:
            # Preserve a safely budgeted initial child; additions are optional.
            qty=max(0,min(initial,math.floor(margincap/margin_child+1e-9)))
        rows.append({'stage':i,'depth_r':depth,'entry':price,'children':qty,'risk_per_child':risk})
        usedrisk+=qty*risk;usedmargin+=qty*margin_child;total+=qty
    add_expiry = now+timedelta(minutes=cfg['add_expiry_minutes'])
    if expires_at:
        add_expiry=min(add_expiry,datetime.fromisoformat(str(expires_at).replace('Z','+00:00')))
    return {'symbol':symbol,'policy_hash':frozen['policy_hash'],'strategy_id':frozen['strategy_id'],
        'configuration_id':cfg['id'],'stages':rows,'initial_children':rows[0]['children'],
        'total_children':total,'risk_budget_usd':budget,'planned_risk_usd':usedrisk,
        'reference_equity':reference,'scale':scale,'margin_per_child':margin_child,
        'planned_margin_usd':usedmargin,'entry':entry,'sl':stop,'tp':target,'side':side,
        'add_expires_at':add_expiry.isoformat(),'expires_at':str(expires_at or add_expiry.isoformat()),
        'initial_accepted':0,'pending_accepted':0,'placement_complete':False,
        'equity_capacity_multiplier':cfg['equity_capacity_multiplier']}


def cancel_owned(session, orders, label, symbol_id):
    for order in orders:
        if order.tradeData.symbolId==symbol_id and str(order.tradeData.label)==label:
            session.cancel_order(int(order.orderId))
    latest=session.reconcile()
    if any(o.tradeData.symbolId==symbol_id and str(o.tradeData.label)==label for o in latest.order):
        raise RuntimeError('LAYERING_CANCEL_NOT_CONFIRMED')
    return latest


def monitor(state, durable, session, gateway, symbol, label, symbol_id, now, details, gate=None):
    """Manage durable baskets before checking a fresh signal, across restarts."""
    basket=state.get('layering_basket')
    if not basket:
        return False
    rec=session.reconcile()
    owned=[p for p in rec.position if p.tradeData.symbolId==symbol_id and str(p.tradeData.label)==label]
    pending=[o for o in rec.order if o.tradeData.symbolId==symbol_id and str(o.tradeData.label)==label]
    if basket['policy_hash']!=HASHES[symbol]:
        cancel_owned(session,pending,label,symbol_id)
        state['quarantined']=True
        raise RuntimeError('LAYERING_ACTIVE_HASH_MISMATCH')
    details.update(layering=deepcopy(basket),candidate={'side':basket['side'],'direction':'BUY' if basket['side']==1 else 'SELL','at':state.get('last_signal')},
        entry=basket['entry'],sl=basket['sl'],tp=basket['tp'],
        planned_children=basket['total_children'],planned_total_lot=basket['total_children']*.01,
        active_children=sum(int(p.tradeData.volume)/(100 if symbol=='XAUUSD' else 100000) for p in owned),
        pending_children=len(pending))
    q=gateway.market_quote(symbol)
    price=float(q.bid if basket['side']==1 else q.ask)
    invalid=basket['side']*(price-basket['sl'])<=0 or basket['side']*(price-basket['tp'])>=0
    room=gateway.account_snapshot()
    contract=manifest(symbol)['contract']
    equity=min(basket['reference_equity'],room.equity)
    reserved_margin=basket['planned_margin_usd']
    budget_bad=(basket['planned_risk_usd']>equity*contract['risk_cap']*basket['scale']+1e-8 or
        reserved_margin>equity*contract['margin_cap']*basket['scale']+1e-8)
    expiry=datetime.fromisoformat(basket['add_expires_at'])
    control_block=False
    if gate is not None:
        try:
            gate.assert_orders_allowed('AUTO')
        except Exception:
            control_block=True
    abort=control_block or not owned or invalid or state.get('quarantined') or budget_bad or now>=expiry
    if pending and abort:
        rec=cancel_owned(session,pending,label,symbol_id)
        pending=[]
    if not owned and rec.position:
        # A pending fill can race cancellation after the parent already exited.
        from .demo_structural_profit_protector import _close_full_position
        for p in rec.position:
            if p.tradeData.symbolId==symbol_id and str(p.tradeData.label)==label:
                status,reason=_close_full_position(session,position_id=int(p.positionId),raw_volume=int(p.tradeData.volume))
                if status!='CLOSED':
                    state['quarantined']=True
                    raise RuntimeError('LAYERING_ORPHAN_EXIT_'+reason)
    if not owned:
        state.pop('layering_basket',None)
        durable.save()
        details.update(state='WAIT',reason='LAYERING_BASKET_FINISHED',pending_children=0)
        return True
    details.update(state='BASKET_ACTIVE',reason='LAYERING_LIMITS_ACTIVE' if pending else 'LAYERING_POSITIONS_ACTIVE',
        pending_children=len(pending))
    return True


def submit_limits(*, state, durable, session, gateway, store, base_policy, control, gate,
                  symbol, label, symbol_id, at, details):
    basket=state['layering_basket'];contract=manifest(symbol)['contract']
    if not basket['initial_accepted']:
        basket['placement_complete']=True;durable.save();return
    max_count=gateway.position_count()+basket['total_children']+1
    policy=replace(base_policy,mode=ExecutionMode.AUTO,
        order={**base_policy.order,'comment_prefix':label,'max_signal_age_seconds':60},
        demo_safety={**base_policy.demo_safety,'max_risk_pct':contract['risk_cap']*100,
                     'max_order_lots':.01,'max_concurrent_positions':max_count})
    router=ExecutionRouter(policy,gateway=gateway,session=session,control_gate=gate,audit_sink=SupabaseOrderAuditSink(store))
    side=OrderSide.BUY if basket['side']==1 else OrderSide.SELL
    for stage in basket['stages'][1:]:
        for child in range(stage['children']):
            now=datetime.now(UTC)
            expiry=datetime.fromisoformat(basket['add_expires_at'])
            if now>=expiry:
                basket['placement_complete']=True;durable.save();return
            rec=session.reconcile()
            owns=lambda x:x.tradeData.symbolId==symbol_id and str(x.tradeData.label)==label
            if not any(owns(p) for p in rec.position) or any(not owns(x) for x in list(rec.position)+list(rec.order)):
                cancel_owned(session,rec.order,label,symbol_id)
                basket['placement_complete']=True;durable.save();return
            snapshot=gateway.account_snapshot();q=gateway.market_quote(symbol)
            live=float(q.ask if side==OrderSide.BUY else q.bid)
            if basket['side']*(live-basket['sl'])<=0 or basket['side']*(live-basket['tp'])>=0:
                cancel_owned(session,rec.order,label,symbol_id)
                basket['placement_complete']=True;durable.save();return
            if (basket['side']*(live-stage['entry'])<=0 or
                q.ask-q.bid>(1.5 if symbol=='XAUUSD' else .00022)):
                # Never turn a missed limit into a market catch-up.
                continue
            cap=min(basket['reference_equity'],snapshot.equity)
            if (basket['planned_risk_usd']>cap*contract['risk_cap']*basket['scale']+1e-8 or
                basket['planned_margin_usd']>cap*contract['margin_cap']*basket['scale']+1e-8 or
                snapshot.margin_free is None or snapshot.margin_free < basket['planned_margin_usd']):
                basket['placement_complete']=True;durable.save();return
            key=f'{"XA50" if symbol=="XAUUSD" else "EU37"}:{int(at.timestamp())}:L{stage["stage"]}:{child:03d}'
            state['attempts'][key]={'outcome':None,'at':now.isoformat(),'stage':stage['stage']}
            durable.save()
            intent=OrderIntent(key,symbol,side,OrderType.LIMIT,now,.01,stage['entry'],basket['sl'],basket['tp'],
                stage['risk_per_child']/snapshot.equity*100,
                comment='DEMO_AUTO:'+('XAU_DD50_FROZEN' if symbol=='XAUUSD' else 'EURUSD_DD37_FROZEN'),expires_at=expiry)
            try:
                control.refresh_once();receipt=router.execute(intent)
            except Exception:
                state['quarantined']=True;durable.save();raise
            state['attempts'][key].update(outcome='ACCEPTED' if receipt.accepted else 'REJECTED',broker_order_id=receipt.broker_order_id)
            if receipt.accepted:
                basket['pending_accepted']+=1
                details['accepted_pending_children']=basket['pending_accepted']
            durable.save()
            if not receipt.accepted:
                break
    basket['placement_complete']=True
    details['layering']=deepcopy(basket)
    details['pending_children']=basket['pending_accepted']
    durable.save()
