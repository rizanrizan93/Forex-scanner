"""Broker data/account evidence only. Outgoing protobuf allowlist excludes ALL trade mutations."""
import collections,csv,datetime,hashlib,json,os,pathlib,time
from fx_scanner.execution.ctrader_session import CTraderOpenApiSession
UTC=datetime.timezone.utc;P=pathlib.Path;out=P('publish');out.mkdir(exist_ok=True)
class ReadOnlySession(CTraderOpenApiSession):
 allowed={'ProtoOAApplicationAuthReq','ProtoOAAccountAuthReq','ProtoOAGetAccountListByAccessTokenReq','ProtoOASymbolsListReq','ProtoOASymbolByIdReq','ProtoOAGetTrendbarsReq','ProtoOATraderReq','ProtoOAReconcileReq','ProtoOAGetPositionUnrealizedPnLReq','ProtoHeartbeatEvent','ProtoOAOrderListReq','ProtoOADealListReq','ProtoOAExpectedMarginReq'}
 def _send_sync(self,message,**kw):
  name=message.DESCRIPTOR.name
  if name not in self.allowed:raise RuntimeError('NON_READ_ONLY_MESSAGE_DENIED')
  self.read_requests[name]+=1
  return super()._send_sync(message,**kw)
 def __init__(self,**kw):self.read_requests=collections.Counter();super().__init__(**kw)
 def send_new_order(self,*a,**k):raise RuntimeError('ORDER_SUBMISSION_DISABLED')
 def cancel_order(self,*a,**k):raise RuntimeError('ORDER_CANCEL_DISABLED')
def main():
 report={'read_only':True,'live_orders_sent':0,'token_refresh_enabled':False,'history_start_utc':'2026-09-01T00:00:00Z','purpose':'Native M1 candle signal/execution diagnosis; historical bid/ask spread, macro and native terminal state not reconstructed'}
 needed=['CTRADER_CLIENT_ID','CTRADER_CLIENT_SECRET','CTRADER_ACCESS_TOKEN']
 if not all(os.environ.get(k) for k in needed):report['status']='CREDENTIALS_UNAVAILABLE';return report
 session=ReadOnlySession(client_id=os.environ[needed[0]],client_secret=os.environ[needed[1]],access_token=os.environ[needed[2]],account_id=None,environment='live',refresh_token=None,allow_token_refresh=False,request_timeout_seconds=20)
 try:
  grants=session.granted_accounts();matches=[a for a in grants if a.trader_login==2147903 and a.is_live]
  report['expected_account_matches']=len(matches)
  if len(matches)!=1:report['status']='EXPECTED_ACCOUNT_NOT_GRANTED';return report
  session.account_id=matches[0].ctid_trader_account_id;session.connect();session.load_symbols(['XAUUSD','EURUSD','BTCUSD'])
  trader=session.trader();digits=int(getattr(trader,'moneyDigits',0) or 0);report['account']={'balance':trader.balance/10**digits,'account_last4':'7903','is_live':True,'broker_leverage_in_cents':int(getattr(trader,'leverageInCents',0))}
  reconciled=session.reconcile();report['current_positions_count']=len(reconciled.position);report['current_pending_orders_count']=len(reconciled.order)
  report['contracts']={}
  for symbol in ['XAUUSD','EURUSD','BTCUSD']:
   m=session.symbol_info(symbol);report['contracts'][symbol]={k:getattr(m,k) for k in ['digits','pipPosition','minVolume','stepVolume','maxVolume','lotSize','maxExposure','tradingMode'] if hasattr(m,k)}
  report['minimum_volume_margin']={}
  for symbol in ['XAUUSD','EURUSD','BTCUSD']:
   try:
    meta=session.symbol_info(symbol);m=session.expected_margin(session.symbol_id(symbol),int(meta.minVolume));md=int(getattr(m,'moneyDigits',digits));report['minimum_volume_margin'][symbol]={'volume_api_cents':int(meta.minVolume),'volume_units':int(meta.minVolume)/100,'money_digits':md,'margin':[{'volume_api_cents':int(v.volume),'buy_margin':v.buyMargin/10**md,'sell_margin':v.sellMargin/10**md} for v in m.margin]}
   except Exception as e:report['minimum_volume_margin'][symbol]={'available':False,'error_type':type(e).__name__}
  now=datetime.datetime.now(UTC).replace(second=0,microsecond=0);begin=datetime.datetime(2026,9,1,tzinfo=UTC);report['end_exclusive_utc']=now.isoformat();report['data']={}
  for symbol in ['XAUUSD','EURUSD','BTCUSD']:
   cursor=now;merged={};pages=[]
   for page in range(25):
    rows=session.historical_bars(symbol,'M1',from_time=max(begin,cursor-datetime.timedelta(days=7)),to_time=cursor,count=5000)
    if not rows:break
    earliest=min(r.timestamp for r in rows)
    for r in rows:
     if begin<=r.timestamp and r.timestamp+datetime.timedelta(minutes=1)<=now:merged[r.timestamp]=r
    pages.append({'rows':len(rows),'earliest':earliest.isoformat(),'latest':max(r.timestamp for r in rows).isoformat()})
    if earliest<=begin:break
    assert earliest<cursor,'HISTORY_NO_PROGRESS';cursor=earliest-datetime.timedelta(milliseconds=1);time.sleep(.4)
   assert merged and min(merged)<datetime.datetime(2026,9,5,tzinfo=UTC),'WARMUP_TOO_SHORT'
   dest=out/(symbol+'_BROKER_M1.csv')
   with dest.open('w',newline='') as f:
    w=csv.writer(f);w.writerow(['utc','open','high','low','close','spread','roll','buy_ok','sell_ok'])
    for at,r in sorted(merged.items()):
     # This spread is an explicit execution-control assumption, never historical spread evidence.
     roll=sum(3 if (begin.date()+datetime.timedelta(days=d)).weekday()==2 else 1 for d in range((at.date()-begin.date()).days+1) if (begin.date()+datetime.timedelta(days=d)).weekday()<5)
     w.writerow([at.isoformat(),r.open,r.high,r.low,r.close,.26 if symbol=='XAUUSD' else .00001,roll if symbol=='XAUUSD' else 0,1,1])
   report['data'][symbol]={'rows':len(merged),'start':min(merged).isoformat(),'end':max(merged).isoformat(),'pages':pages,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'spread_note':'Historical spread unavailable; explicit .26 XAU / .00001 EUR placeholder for separate model replay, not broker execution parity.'}
   print('BROKER_HISTORY_PROGRESS',symbol,len(merged),flush=True)
  # Read order/deal history only; export owned labels and timestamps, no credentials/account identifiers.
  try:
   from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAOrderListReq,ProtoOADealListReq
   names={session.symbol_id(s):s for s in ['XAUUSD','EURUSD','BTCUSD']};since=int(datetime.datetime(2026,10,9,17,tzinfo=UTC).timestamp()*1000)
   req=ProtoOAOrderListReq();req.ctidTraderAccountId=session.account_id;req.fromTimestamp=since;req.toTimestamp=int(now.timestamp()*1000)
   res=session._send_sync(req);orders=[]
   for order in res.order:
    data=order.tradeData;label=str(getattr(data,'label',''))
    if not label.startswith(('RZX','RZEU','RZEF','RZBTC')):continue
    orders.append({'label':label,'symbol':names.get(data.symbolId,'OTHER'),'order_status':int(order.orderStatus),'order_type':int(order.orderType),'volume':int(data.volume),'trade_side':int(data.tradeSide),'open_timestamp_ms':int(getattr(data,'openTimestamp',0)),'execution_price':float(getattr(order,'executionPrice',0))})
   report['owned_order_history']={'has_more':bool(getattr(res,'hasMore',False)),'orders':orders}
  except Exception as e:report['owned_order_history']={'available':False,'error_type':type(e).__name__}
  report['status']='BROKER_HISTORY_ACQUIRED';return report
 except Exception as e:report['status']='BROKER_READ_ONLY_UNAVAILABLE';report['error_type']=type(e).__name__;return report
 finally:
  report['outgoing_request_counts']=dict(session.read_requests);session.close()
r=main();(out/'BROKER_READ_ONLY_HISTORY.json').write_text(json.dumps(r,indent=2));print('BROKER_READ_ONLY_RESULT',json.dumps(r),flush=True)
