"""Dedicated R3 market-data reader; no account positions/orders/token rotation."""
import json,os,sys,time
from pathlib import Path
from datetime import UTC,datetime,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fx_scanner.execution.ctrader_market_readonly import ReadOnly

class Reader(ReadOnly):
    allowed=ReadOnly.allowed|frozenset({'ProtoOAGetTickDataReq'})
    def send_new_order(self,*a,**k):raise RuntimeError('R3_ORDER_DISABLED')
    def cancel_order(self,*a,**k):raise RuntimeError('R3_ORDER_DISABLED')


def collect(output):
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTickDataReq
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAQuoteType
    p=Path(output);previous={}
    if p.exists():
        try:
            cached=json.loads(p.read_text())
            if cached.get('contract')=='RIZAN_MANUAL_R3_MARKET_V1':previous={x['timestamp']:x for x in cached.get('m1',[])}
        except (OSError,ValueError,KeyError,TypeError):pass
    s=Reader(client_id=os.environ['CTRADER_CLIENT_ID'],client_secret=os.environ['CTRADER_CLIENT_SECRET'],
             access_token=os.environ['CTRADER_ACCESS_TOKEN'],account_id=None,environment='live',refresh_token=None,
             allow_token_refresh=False,request_timeout_seconds=20)
    try:
        grants=[a for a in s.granted_accounts() if a.is_live and str(a.trader_login).endswith('7903')]
        if len(grants)!=1:raise RuntimeError('R3_READONLY_ACCOUNT_NOT_UNIQUE')
        s.account_id=grants[0].ctid_trader_account_id;s.connect();s.load_symbols(['XAUUSD'])
        now=datetime.now(UTC);begin=now-timedelta(days=14)
        if previous:begin=max(begin,datetime.fromisoformat(max(previous))-timedelta(minutes=3))
        cursor=now
        for page in range(12):
            rows=s.historical_bars('XAUUSD','M1',from_time=max(begin,cursor-timedelta(days=7)),to_time=cursor,count=5000)
            earliest=min(b.timestamp for b in rows)
            for b in rows:
                if b.timestamp+timedelta(minutes=1)<=datetime.now(UTC):
                    previous[b.timestamp.isoformat()]={k:float(getattr(b,k)) for k in ['open','high','low','close']}|{'timestamp':b.timestamp.isoformat()}
            if earliest<=begin or len(previous)>=12000:break
            if earliest>=cursor:raise RuntimeError('R3_HISTORY_NO_PROGRESS')
            cursor=earliest-timedelta(milliseconds=1);time.sleep(.25)
        m1=[r for _,r in sorted(previous.items())][-12000:]
        if len(m1)<2000:raise RuntimeError('R3_HISTORY_NOT_READY')
        quote={};points={}
        for side in ['BID','ASK']:
            clock=datetime.now(UTC)
            req=ProtoOAGetTickDataReq(ctidTraderAccountId=s.account_id,symbolId=s.symbol_id('XAUUSD'),
                type=ProtoOAQuoteType.Value(side),fromTimestamp=int((clock-timedelta(seconds=15)).timestamp()*1000),toTimestamp=int(clock.timestamp()*1000))
            response=s._send_sync(req)
            if response.tickData:
                newest=response.tickData[0]
                points[side]=(newest.tick/100000.,datetime.fromtimestamp(newest.timestamp/1000,UTC))
            time.sleep(.1)
        if len(points)==2:
            bid,bt=points['BID'];ask,at=points['ASK']
            if 0<bid<=ask and abs((at-bt).total_seconds())<=5:
                quote={'bid':bid,'ask':ask,'at':min(at,bt).isoformat()}
        return dict(contract='RIZAN_MANUAL_R3_MARKET_V1',source='CTRADER_MARKET_DATA_READ_ONLY',symbol='XAUUSD',
                    as_of=datetime.now(UTC).isoformat(),execution_authority=False,execution_influence=False,m1=m1,quote=quote)
    finally:s.close()


if __name__=='__main__':
    try:
        p=Path(sys.argv[1]);result=collect(p);tmp=p.with_name('.'+p.name+'.'+str(os.getpid())+'.tmp')
        with tmp.open('w') as w:json.dump(result,w,separators=(',',':'),allow_nan=False);w.flush();os.fsync(w.fileno())
        tmp.chmod(0o644);os.replace(tmp,p)
        print('R3_MARKET_READONLY',result['as_of'],len(result['m1']))
    except Exception as e:
        import traceback
        frames=traceback.extract_tb(e.__traceback__)
        print('R3_COLLECTION_FAILED:'+type(e).__name__+':'+','.join(Path(f.filename).name+'@'+str(f.lineno) for f in frames),flush=True)
        raise SystemExit(1)
