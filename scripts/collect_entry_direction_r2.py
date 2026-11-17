"""Independent market-data reader and frozen R2 scorer; no order/account mutations."""
from __future__ import annotations
import json,os,sys,time
from pathlib import Path
from datetime import UTC,datetime,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import pandas as pd
from fx_scanner.execution.ctrader_market_readonly import ReadOnly
from fx_scanner.entry_direction_r2.runtime import evaluate,CONTRACT

class Reader(ReadOnly):
 allowed=ReadOnly.allowed|frozenset({'ProtoOAGetTickDataReq'})
 def send_new_order(self,*a,**k):raise RuntimeError('R2_ORDER_DISABLED')
 def cancel_order(self,*a,**k):raise RuntimeError('R2_ORDER_DISABLED')

def atomic(path,payload,mode=0o600):
 tmp=path.with_suffix('.tmp')
 with tmp.open('w') as f:json.dump(payload,f,separators=(',',':'),allow_nan=False);f.flush();os.fsync(f.fileno())
 tmp.chmod(mode);os.replace(tmp,path)

def decode_ticks(items):
 out=[];clock=None
 for item in items:
  value=int(item.timestamp)
  clock=value if clock is None else clock-abs(value)
  out.append((clock,float(item.tick)/100000.))
 return out

def history(s,symbol,cache,count,now):
 previous={r['timestamp']:r for r in cache};begin=now-timedelta(days=100 if symbol=='XAUUSD' else 7)
 if len(previous)>=count:begin=max(begin,datetime.fromisoformat(max(previous))-timedelta(minutes=3))
 cursor=now
 for page in range(18):
  rows=s.historical_bars(symbol,'M1',from_time=max(begin,cursor-timedelta(days=7)),to_time=cursor,count=5000)
  earliest=min(b.timestamp for b in rows)
  for b in rows:
   if b.timestamp<=now:previous[b.timestamp.isoformat()]={k:float(getattr(b,k)) for k in ['open','high','low','close']}|{'timestamp':b.timestamp.isoformat()}
  if earliest<=begin or len(previous)>=count+1:break
  if earliest>=cursor:raise RuntimeError('R2_HISTORY_NO_PROGRESS')
  cursor=earliest-timedelta(milliseconds=1);time.sleep(.3)
 return [r for _,r in sorted(previous.items())][-(count+1):]

def market_ticks(s,now):
 from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTickDataReq
 from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAQuoteType
 streams={};start=now-timedelta(minutes=3)
 for side in ['BID','ASK']:
  rows=[];cursor=now
  for _ in range(12):
   req=ProtoOAGetTickDataReq(ctidTraderAccountId=s.account_id,symbolId=s.symbol_id('XAUUSD'),type=ProtoOAQuoteType.Value(side),fromTimestamp=int(start.timestamp()*1000),toTimestamp=int(cursor.timestamp()*1000))
   res=s._send_sync(req);chunk=decode_ticks(res.tickData);rows.extend(chunk);time.sleep(.3)
   if not res.hasMore or not chunk:break
   older=min(t for t,_ in chunk)
   if older<=int(start.timestamp()*1000):break
   cursor=datetime.fromtimestamp((older-1)/1000,UTC)
  streams[side]=pd.Series({t:v for t,v in rows},dtype=float).sort_index()
 if any(x.empty for x in streams.values()):return {},{}
 both=pd.concat(streams,axis=1).sort_index().ffill().dropna();both.index=pd.to_datetime(both.index,unit='ms',utc=True)
 spreads=both.ASK-both.BID;spreads=spreads[(spreads>0)&(spreads<100)]
 current=pd.Timestamp(now).floor('min');means=spreads.groupby(spreads.index.floor('min')).mean();means=means[means.index<current]
 # A minute mean is eligible only if both quote streams cover its beginning.
 first=both.index.min();means=means[means.index>=first.ceil('min')]
 bid=streams['BID'].iloc[-1];ask=streams['ASK'].iloc[-1];bt=streams['BID'].index[-1];at=streams['ASK'].index[-1]
 quote={'bid':float(bid),'ask':float(ask),'at':datetime.fromtimestamp(min(bt,at)/1000,UTC).isoformat()} if 0<bid<=ask and abs(bt-at)<=5000 else {}
 current_bids=streams['BID'][streams['BID'].index>=int(current.timestamp()*1000)]
 if quote and not current_bids.empty and streams['BID'].index.min()<int(current.timestamp()*1000):quote['minute_open']=float(current_bids.iloc[0]);quote['minute_open_at']=current.isoformat()
 return quote,{t.isoformat():float(v) for t,v in means.items()}

def collect(directory):
 state_path=directory/'state.json';public_path=directory/'snapshot.json';state={}
 if state_path.exists():state=json.loads(state_path.read_text())
 credentials=json.loads(Path('/etc/rizan-bootstrap125-monitor-broker.json').read_text())
 s=Reader(client_id=credentials['CTRADER_CLIENT_ID'],client_secret=credentials['CTRADER_CLIENT_SECRET'],access_token=credentials['CTRADER_ACCESS_TOKEN'],account_id=None,environment='live',refresh_token=None,allow_token_refresh=False,request_timeout_seconds=25)
 try:
  grants=[a for a in s.granted_accounts() if a.is_live and str(a.trader_login).endswith('7903')]
  if len(grants)!=1:raise RuntimeError('R2_READONLY_ACCOUNT_NOT_UNIQUE')
  s.account_id=grants[0].ctid_trader_account_id;s.connect();s.load_symbols(['XAUUSD','EURUSD'])
  now=datetime.now(UTC);bars={}
  for symbol,count in [('XAUUSD',60000),('EURUSD',2000)]:bars[symbol]=history(s,symbol,state.get('bars',{}).get(symbol,[]),count,now)
  now=datetime.now(UTC);quote,spreads=market_ticks(s,now);spread_cache=dict(state.get('spreads',{}));spread_cache.update(spreads);spread_cache={k:v for k,v in spread_cache.items() if pd.Timestamp(k)>=pd.Timestamp(now)-pd.Timedelta(days=2)}
  frames={}
  for symbol,rows in bars.items():
   f=pd.DataFrame(rows).set_index('timestamp');f.index=pd.to_datetime(f.index,utc=True);frames[symbol]=f
  if quote.get('minute_open_at'):
   t=pd.Timestamp(quote['minute_open_at']);price=quote['minute_open']
   if t not in frames['XAUUSD'].index:frames['XAUUSD'].loc[t,['open','high','low','close']]=[price]*4;frames['XAUUSD']=frames['XAUUSD'].sort_index()
  # An observed forming trendbar contributes OPEN only to entry-time features;
  # all indicators map completed candles and all close-based inputs shift1.
  frames['XAUUSD']['spread']=pd.Series({pd.Timestamp(k):v for k,v in spread_cache.items()}).reindex(frames['XAUUSD'].index)
  out=evaluate(frames['XAUUSD'],frames['EURUSD'],quote,now=datetime.now(UTC),memory=state.get('memory'))
  memory=out.pop('memory');atomic(state_path,{'bars':bars,'spreads':spread_cache,'memory':memory});atomic(public_path,out,0o644)
  print('ENTRY_R2_PUBLISHED',out['as_of'],out['status'],len(bars['XAUUSD']),len(bars['EURUSD']),flush=True)
 finally:s.close()

if __name__=='__main__':
 directory=Path(sys.argv[1]);directory.mkdir(exist_ok=True)
 try:collect(directory)
 except Exception as exc:
  # A failed read cannot retain an active-looking trigger or renew quote time.
  atomic(directory/'snapshot.json',{'contract':CONTRACT,'as_of':datetime.now(UTC).isoformat(),'model_id':'R2_RULE_670','status':'WAIT_DATA','direction':'WAIT','execution_authority':False,'execution_influence':False,'reason':'Sumber model belum tersedia','checks':[],'source_error':type(exc).__name__},0o644)
  print('ENTRY_R2_FAILED:'+type(exc).__name__,flush=True);raise SystemExit(1)
