"""Broker cTrader historical M1 OHLC research collection: READ ONLY.

No order, position, bridge, token refresh, cBot or trading API calls.
M1 trendbars are NOT native tick BID/ASK fills.
"""
import csv, json, os, sys, hashlib
from datetime import datetime, timedelta, UTC
from pathlib import Path

ALLOWED=frozenset({'ProtoOAApplicationAuthReq','ProtoOAGetAccountListByAccessTokenReq',
  'ProtoOAAccountAuthReq','ProtoOASymbolsListReq','ProtoOAGetTrendbarsReq'})
START=datetime(2026,3,15,tzinfo=UTC)
END=datetime(2026,10,20,tzinfo=UTC)
INSTRUMENTS=('XAUUSD','EURUSD')

def check_rows(rows,symbol):
    if len(rows)<150000:raise ValueError(f'{symbol}: insufficient historical M1 candles: {len(rows)}')
    ts=sorted(rows)
    if ts[0]>START+timedelta(days=6) or ts[-1]<END-timedelta(days=5):
        raise ValueError(f'{symbol}: missing start/end coverage')
    gaps=0
    for t,v in rows.items():
        if any(v[k]<=0 for k in ('open','high','low','close')) or v['high']<max(v['open'],v['low'],v['close']) or v['low']>min(v['open'],v['high'],v['close']):
            raise ValueError(f'{symbol}: bad OHLC at '+t.isoformat())
    for a,b in zip(ts,ts[1:]):
        if b-a>timedelta(hours=6) and a.weekday() in (0,1,2,3) and b.weekday() in (0,1,2,3,4):gaps+=1
    if gaps>10:raise ValueError(f'{symbol}: suspicious weekday gap count {gaps}')
    return {'symbol':symbol,'rows':len(rows),'first_utc':ts[0].isoformat(),
       'last_utc':ts[-1].isoformat(),'large_weekday_gaps':gaps,
       'source':'CTRADER_BROKER_TRENDBAR_READ_ONLY','data_type':'M1_TRENDBAR_NOT_NATIVE_TICK_BID_ASK'}

def save_rows(path,rows):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=('timestamp','open','high','low','close'))
        w.writeheader()
        for t,b in sorted(rows.items()):w.writerow({'timestamp':t.isoformat(),**b})
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main(output):
    from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
    from ctrader_open_api.messages import OpenApiMessages_pb2 as messages
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
    from twisted.internet import reactor, defer
    from twisted.internet.task import deferLater

    auth={key:os.environ.get(key,'').strip() for key in
         ('CTRADER_CLIENT_ID','CTRADER_CLIENT_SECRET','CTRADER_ACCESS_TOKEN')}
    if not all(auth.values()):raise RuntimeError('READ_ONLY_CTRADER_CREDENTIALS_MISSING')
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    client=Client(EndPoints.PROTOBUF_LIVE_HOST,EndPoints.PROTOBUF_PORT,TcpProtocol)
    errors=[];started=False

    @defer.inlineCallbacks
    def req(name,**kwargs):
        if name not in ALLOWED:raise RuntimeError('READ_ONLY_PROTOCOL_BLOCK')
        resp=Protobuf.extract((yield client.send(getattr(messages,name)(**kwargs),
                                                 responseTimeoutInSeconds=25)))
        if resp.DESCRIPTOR.name in ('ProtoOAErrorRes','ProtoErrorRes'):
            raise RuntimeError('READ_ONLY_BROKER_API_ERROR:'+str(resp.errorCode))
        return resp

    @defer.inlineCallbacks
    def collect_symbol(account,symbol):
        rows={};pages=0;begin=START
        while begin<END:
            until=min(begin+timedelta(days=14),END);cursor=until
            while cursor>begin:
                resp=yield req('ProtoOAGetTrendbarsReq',ctidTraderAccountId=account,
                     symbolId=symbol.symbolId,period=ProtoOATrendbarPeriod.Value('M1'),
                     fromTimestamp=int(begin.timestamp()*1000),
                     toTimestamp=int(cursor.timestamp()*1000),count=1000)
                pages+=1
                if not resp.trendbar:break
                oldest=cursor
                for b in resp.trendbar:
                    t=datetime.fromtimestamp(b.utcTimestampInMinutes*60,UTC)
                    oldest=min(oldest,t)
                    if not START<=t<END:continue
                    v={'low':b.low/100000.,'open':(b.low+b.deltaOpen)/100000.,
                       'high':(b.low+b.deltaHigh)/100000.,
                       'close':(b.low+b.deltaClose)/100000.}
                    if t in rows and rows[t]!=v:raise RuntimeError('HISTORY_DUPLICATE_DISAGREEMENT')
                    rows[t]=v
                if oldest<=begin:break
                if oldest>=cursor:raise RuntimeError('HISTORY_PAGINATION_STALLED')
                cursor=oldest-timedelta(milliseconds=1)
                if pages>1100:raise RuntimeError('TOO_MANY_READ_ONLY_REQUESTS')
                yield deferLater(reactor,0.3,lambda:None)
            begin=until
            print('V10_PROGRESS '+symbol.symbolName+' through='+begin.date().isoformat()+' n='+str(len(rows)),flush=True)
        status=check_rows(rows,symbol.symbolName)
        status['request_pages']=pages
        status['file_sha256']=save_rows(out/(symbol.symbolName+'_ctrader_m1.csv'),rows)
        return status

    @defer.inlineCallbacks
    def collect():
        yield req('ProtoOAApplicationAuthReq',clientId=auth['CTRADER_CLIENT_ID'],clientSecret=auth['CTRADER_CLIENT_SECRET'])
        grants=yield req('ProtoOAGetAccountListByAccessTokenReq',accessToken=auth['CTRADER_ACCESS_TOKEN'])
        # Exactly the existing read-only live connection used by the XAU scanner.
        accounts=[a for a in grants.ctidTraderAccount if a.isLive and str(a.traderLogin).endswith('4480')]
        if len(accounts)!=1:raise RuntimeError('RESEARCH_BROKER_ACCOUNT_BINDING_MISMATCH')
        account=accounts[0].ctidTraderAccountId
        yield req('ProtoOAAccountAuthReq',ctidTraderAccountId=account,accessToken=auth['CTRADER_ACCESS_TOKEN'])
        catalogue=yield req('ProtoOASymbolsListReq',ctidTraderAccountId=account,includeArchivedSymbols=False)
        result=[]
        for key in INSTRUMENTS:
            matching=[s for s in catalogue.symbol if s.symbolName.upper()==key]
            if len(matching)!=1:raise RuntimeError('RESEARCH_SYMBOL_UNAVAILABLE:'+key)
            result.append((yield collect_symbol(account,matching[0])))
        (out/'DATA_QUALITY.json').write_text(json.dumps({
           'contract':'RIZAN_RESEARCH_V1_0_M1_READ_ONLY',
           'from_utc':START.isoformat(),'end_utc_exclusive':END.isoformat(),
           'market_data_only':True,'execution_authority':False,
           'instruments':result,'caveat':'cTrader M1 trendbars not native BID/ASK ticks; no trades simulated.'
        },indent=2))
        print('V10_CTRADER_COMPLETE '+str([(r['symbol'],r['rows']) for r in result]),flush=True)

    def finish(x):
        if hasattr(x,'check'):errors.append(x.getErrorMessage().split('\n')[0][:180])
        client.stopService()
        if reactor.running:reactor.stop()
        return None

    def connected(_):
        nonlocal started
        if started:return
        started=True
        collect().addBoth(finish)

    client.setConnectedCallback(connected)
    client.setDisconnectedCallback(lambda *_:finish(RuntimeError('RESEARCH_DISCONNECTED')) if not started else None)
    reactor.callLater(1200,lambda:(errors.append('RESEARCH_READ_TIMEOUT'),finish(None)))
    client.startService();reactor.run()
    if errors or not (out/'DATA_QUALITY.json').is_file():
        raise RuntimeError('V10_READ_ONLY_HISTORY_FAILED:'+','.join(errors))

if __name__=='__main__':main(sys.argv[1])
