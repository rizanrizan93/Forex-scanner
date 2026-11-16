"""V1 broker observations using an enforced read-only protocol allowlist.

The token is loaded privately. No order submission/amend/cancel is permitted.
Published summaries omit account IDs, labels, IDs, position sizes and balances.
"""
import json, os, sys, time
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from fx_scanner.execution.ctrader_session import CTraderOpenApiSession

UTC=timezone.utc
FOLDER=Path('/var/lib/rizan-bootstrap125-monitor')
CREDENTIALS=Path('/etc/rizan-bootstrap125-monitor-broker.json')
PREFIXES={'TPX_b6014ae7':'XAUUSD','TPE_b6014ae7':'EURUSD','TPB_b6014ae7':'BTCUSD','RZB125S':'EURUSD'}

class Reader(CTraderOpenApiSession):
    allowed=frozenset({'ProtoOAApplicationAuthReq','ProtoOAAccountAuthReq',
        'ProtoOAGetAccountListByAccessTokenReq','ProtoOASymbolsListReq','ProtoOASymbolByIdReq',
        'ProtoOAGetTrendbarsReq','ProtoHeartbeatEvent','ProtoOAReconcileReq',
        'ProtoOADealListReq','ProtoOAOrderListReq'})
    def _send_sync(self,message,**kwargs):
        if message.DESCRIPTOR.name not in self.allowed: raise RuntimeError('READ_ONLY_PROTOCOL_GUARD')
        return super()._send_sync(message,**kwargs)
    def send_new_order(self,*args,**kwargs): raise RuntimeError('ORDER_DISABLED')
    def cancel_order(self,*args,**kwargs): raise RuntimeError('ORDER_DISABLED')
    def new_order_message(self,*args,**kwargs): raise RuntimeError('ORDER_DISABLED')


def label_role(label):
    return PREFIXES.get(str(label).partition('|')[0])


def atomic(name,data,mode=0o644):
    target=FOLDER/name; tmp=target.with_suffix('.tmp')
    with tmp.open('w') as stream:
        json.dump(data,stream,allow_nan=False,separators=(',',':'))
        stream.flush();os.fsync(stream.fileno())
    tmp.chmod(mode);os.replace(tmp,target)


def read():
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAOrderListReq,ProtoOADealListReq
    secrets=json.loads(CREDENTIALS.read_text())
    client=Reader(client_id=secrets['CTRADER_CLIENT_ID'],client_secret=secrets['CTRADER_CLIENT_SECRET'],
        access_token=secrets['CTRADER_ACCESS_TOKEN'],account_id=None,environment='live',
        refresh_token=None,allow_token_refresh=False,request_timeout_seconds=15)
    start=datetime.now(UTC)
    since=start-timedelta(hours=48)
    result=dict(contract='RIZAN_BOOTSTRAP125_BROKER_READONLY_V1',account_suffix='7903',
        read_only=True,execution_authority=False,observed_at=None,status='UNKNOWN',
        history_from=since.isoformat(),history_to=start.isoformat(),orders_history_checked=False,
        deals_history_checked=False,roles={},market={},error=None)
    try:
        grants=[g for g in client.granted_accounts() if g.is_live and str(g.trader_login).endswith('7903')]
        if len(grants)!=1: raise RuntimeError('ACCOUNT_BINDING_MISMATCH')
        client.account_id=grants[0].ctid_trader_account_id;client.connect()
        client.load_symbols(['XAUUSD','EURUSD','BTCUSD'])
        ids={client.symbol_id(s):s for s in ('XAUUSD','EURUSD','BTCUSD')}
        result['roles']={s:dict(open_positions=0,pending_orders=0,orders=0,deals=0,
                               rejected_orders=0,entry_fills=0,last_order_at=None,last_fill_at=None)
                         for s in ids.values()}
        result['foreign_exposure_present']=False
        live=client.reconcile()
        for position in live.position:
            symbol=label_role(getattr(position.tradeData,'label',''))
            if symbol and ids.get(position.tradeData.symbolId)==symbol:
                result['roles'][symbol]['open_positions']+=1
            else:result['foreign_exposure_present']=True
        for order in live.order:
            symbol=label_role(getattr(order.tradeData,'label',''))
            if symbol and ids.get(order.tradeData.symbolId)==symbol:
                result['roles'][symbol]['pending_orders']+=1
            else:result['foreign_exposure_present']=True
        kwargs=dict(ctidTraderAccountId=client.account_id,fromTimestamp=int(since.timestamp()*1000),toTimestamp=int(start.timestamp()*1000))
        order_map={}
        try:
            response=client._send_sync(ProtoOAOrderListReq(**kwargs))
            result['orders_history_checked']=not bool(getattr(response,'hasMore',False))
            for order in response.order:
                symbol=label_role(getattr(order.tradeData,'label',''))
                if not symbol or ids.get(order.tradeData.symbolId)!=symbol:continue
                order_map[order.orderId]=symbol
                if getattr(order,'closingOrder',False):continue
                row=result['roles'][symbol];row['orders']+=1
                row['rejected_orders']+=int(int(order.orderStatus)==3)
                timestamp=int(getattr(order,'utcLastUpdateTimestamp',0))
                if timestamp:
                    at=datetime.fromtimestamp(timestamp/1000,UTC).isoformat()
                    row['last_order_at']=max(at,row['last_order_at'] or at)
        except Exception as e: result['orders_error']=type(e).__name__
        try:
            response=client._send_sync(ProtoOADealListReq(**kwargs,maxRows=1000))
            result['deals_history_checked']=not bool(getattr(response,'hasMore',False))
            result['unmapped_deals']=0
            for deal in response.deal:
                symbol=label_role(getattr(deal,'label','')) or order_map.get(deal.orderId)
                if not symbol or ids.get(deal.symbolId)!=symbol:
                    result['unmapped_deals']+=1;continue
                row=result['roles'][symbol];row['deals']+=1
                if not deal.HasField('closePositionDetail') and int(deal.dealStatus) in (2,3):
                    row['entry_fills']+=1
                    timestamp=int(deal.executionTimestamp)
                    if timestamp:
                        at=datetime.fromtimestamp(timestamp/1000,UTC).isoformat()
                        row['last_fill_at']=max(at,row['last_fill_at'] or at)
        except Exception as e: result['deals_error']=type(e).__name__
        # Broker candles supply independent chart evidence, not native readiness.
        # M1 and H1 growth context is collected now; full strategy warmup/parity
        # must still be checked separately before any missed-entry claim.
        market=dict(contract='RIZAN_BOOTSTRAP125_MARKET_READONLY_V1',read_only=True,
                    execution_authority=False,account_suffix='7903',bars={},observed_at=None)
        for symbol in ids.values():
            market['bars'][symbol]={}
            result['market'][symbol]={}
            for frame,count,days in [('M1',512,3),('M5',512,5),('H1',512,45),('H4',1024,270)]:
                try:
                    now=datetime.now(UTC);period={'M1':60,'M5':300,'H1':3600,'H4':14400}[frame]
                    bars=client.historical_bars(symbol,frame,from_time=now-timedelta(days=days),to_time=now,count=count)
                    closed=[b for b in bars if b.timestamp+timedelta(seconds=period)<=now]
                    market['bars'][symbol][frame]=[dict(timestamp=b.timestamp.isoformat(),open=b.open,high=b.high,low=b.low,close=b.close,volume=b.tick_count) for b in closed]
                    result['market'][symbol][frame]=dict(count=len(closed),last_closed_bar_at=closed[-1].timestamp.isoformat() if closed else None)
                except Exception as e: result['market'][symbol][frame]=dict(error=type(e).__name__)
                time.sleep(.25)
        market['observed_at']=datetime.now(UTC).isoformat();atomic('market.json',market)
        result['status']='OBSERVED'
    except Exception as e:
        result['status']='UNAVAILABLE';result['error']=type(e).__name__
    finally:
        client.close()
    # Keep broker snapshot time at reconcile/history observation, not end of slow
    # history fetching. Market carries its own completed observation timestamp.
    result['observed_at']=start.isoformat()
    atomic('broker.json',result)
    print(json.dumps(dict(status=result['status'],observed_at=result['observed_at'],
        orders_history_checked=result['orders_history_checked'],deals_history_checked=result['deals_history_checked'],
        error=result['error'])))

if __name__=='__main__':read()
