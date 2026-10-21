"""Bounded cTrader reader. Every outgoing protobuf request is allowlisted."""
import collections,hashlib,json,os,sys,time
from datetime import datetime,UTC,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fx_scanner.execution.ctrader_session import CTraderOpenApiSession
class Reader(CTraderOpenApiSession):
 allowed=frozenset({'ProtoOAApplicationAuthReq','ProtoOAAccountAuthReq','ProtoOAGetAccountListByAccessTokenReq','ProtoOASymbolsListReq','ProtoOASymbolByIdReq','ProtoOAGetTrendbarsReq','ProtoHeartbeatEvent','ProtoOAReconcileReq','ProtoOAGetTickDataReq'})
 def _send_sync(self,message,**kwargs):
  if message.DESCRIPTOR.name not in self.allowed:raise RuntimeError('READ_ONLY_PROTOCOL_GUARD')
  return super()._send_sync(message,**kwargs)
 def send_new_order(self,*a,**k):raise RuntimeError('ORDER_DISABLED')
 def cancel_order(self,*a,**k):raise RuntimeError('ORDER_DISABLED')
def main(output):
 p=Path(output);now=datetime.now(UTC);old=json.loads(p.read_text()) if p.exists() else {};bars=old.get('bars',{})
 r=Reader(client_id=os.environ['CTRADER_CLIENT_ID'],client_secret=os.environ['CTRADER_CLIENT_SECRET'],access_token=os.environ['CTRADER_ACCESS_TOKEN'],account_id=None,environment='live',refresh_token=None,allow_token_refresh=False,request_timeout_seconds=20)
 out={'as_of':now.isoformat(),'bars':{},'quotes':{},'positions':[],'read_only':True}
 try:
  grants=[a for a in r.granted_accounts() if a.is_live and str(a.trader_login).endswith('7903')]
  if len(grants)!=1:raise RuntimeError('ACCOUNT_BINDING_MISMATCH')
  out['account_binding']=hashlib.sha256(str(grants[0].trader_login).encode()).hexdigest()
  r.account_id=grants[0].ctid_trader_account_id;r.connect();r.load_symbols(['XAUUSD','EURUSD','BTCUSD'])
  for symbol in ['XAUUSD','EURUSD']:
   cached={b['timestamp']:b for b in bars.get(symbol,[])};begin=now-timedelta(days=14)
   if cached:begin=max(begin,datetime.fromisoformat(max(cached))-timedelta(minutes=2))
   cursor=now
   for page in range(35):
    rows=r.historical_bars(symbol,'M1',from_time=max(begin,cursor-timedelta(days=7)),to_time=cursor,count=5000)
    if not rows:break
    earliest=min(b.timestamp for b in rows)
    for b in rows:
     if b.timestamp+timedelta(minutes=1)<=now:cached[b.timestamp.isoformat()]={k:getattr(b,k) for k in ['open','high','low','close']}|{'timestamp':b.timestamp.isoformat()}
    if earliest<=begin:break
    if earliest>=cursor:raise RuntimeError('HISTORY_NO_PROGRESS')
    cursor=earliest-timedelta(milliseconds=1);time.sleep(.35)
   out['bars'][symbol]=[b for at,b in sorted(cached.items()) if datetime.fromisoformat(at)>=now-timedelta(days=14)]
  from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTickDataReq
  from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAQuoteType
  for symbol in ['XAUUSD','EURUSD','BTCUSD']:
   try:
    points={}
    for kind in ['BID','ASK']:
     t=datetime.now(UTC);req=ProtoOAGetTickDataReq(ctidTraderAccountId=r.account_id,symbolId=r.symbol_id(symbol),type=ProtoOAQuoteType.Value(kind),fromTimestamp=int((t-timedelta(seconds=20)).timestamp()*1000),toTimestamp=int(t.timestamp()*1000))
     res=r._send_sync(req)
     if res.hasMore or not res.tickData:raise ValueError('QUOTE_UNAVAILABLE')
     # First tick is absolute (newest first); no future/as-of substitution.
     q=res.tickData[0];points[kind]={'price':q.tick/100000.,'at':datetime.fromtimestamp(q.timestamp/1000,UTC).isoformat()};time.sleep(.3)
    if points['ASK']['price']<points['BID']['price']:raise ValueError('CROSSED_QUOTE')
    out['quotes'][symbol]=points
   except Exception:out['quotes'][symbol]={}
  names={r.symbol_id(s):s for s in ['XAUUSD','EURUSD','BTCUSD']}
  for pos in r.reconcile().position:
   d=pos.tradeData;label=str(getattr(d,'label',''))
   if label.startswith(('RZXRC1|','RZEF245|','RZBTC8500283|')):
    out['positions'].append({'symbol':names.get(d.symbolId),'side':'BUY' if d.tradeSide==1 else 'SELL','entry':pos.price,'sl':getattr(pos,'stopLoss',None),'tp':getattr(pos,'takeProfit',None)})
  out['as_of']=datetime.now(UTC).isoformat();p.write_text(json.dumps(out,allow_nan=False))
 finally:r.close()
if __name__=='__main__':main(sys.argv[1])
