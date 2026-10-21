"""Historical FP Markets BID/ASK tick probe, never an order, token refresh or bridge."""
from datetime import UTC,datetime,timedelta
from pathlib import Path
import json,os,sys
from ctrader_open_api import Client,Protobuf,TcpProtocol,EndPoints
from ctrader_open_api.messages import OpenApiMessages_pb2 as messages
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAQuoteType
from twisted.internet import reactor,defer

ALLOWED=frozenset(('ProtoOAApplicationAuthReq','ProtoOAGetAccountListByAccessTokenReq',
                    'ProtoOAAccountAuthReq','ProtoOASymbolsListReq','ProtoOAGetTickDataReq'))
T=datetime(2026,9,4,10,14,tzinfo=UTC)
auth={key:os.environ.get(key,'').strip() for key in
      ('CTRADER_CLIENT_ID','CTRADER_CLIENT_SECRET','CTRADER_ACCESS_TOKEN')}
if not all(auth.values()):raise RuntimeError('MISSING_READ_ONLY_AUTH')
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
client=Client(EndPoints.PROTOBUF_LIVE_HOST,EndPoints.PROTOBUF_PORT,TcpProtocol)
errors=[];started=False
@defer.inlineCallbacks
def request(name,**kwargs):
    if name not in ALLOWED:raise RuntimeError('PROTOCOL_NOT_READ_ONLY')
    response=Protobuf.extract((yield client.send(getattr(messages,name)(**kwargs),
                                                 responseTimeoutInSeconds=25)))
    if response.DESCRIPTOR.name in ('ProtoOAErrorRes','ProtoErrorRes'):
        raise RuntimeError('BROKER_READ_ERROR:'+str(response.errorCode))
    return response

def decode(response):
    raw=list(response.tickData)
    if not raw:return []
    absolute=int(raw[0].timestamp)
    result=[]
    for i,t in enumerate(raw):
        if i: absolute-=int(t.timestamp)
        result.append((absolute,round(int(t.tick)/100000,5)))
    result.reverse()
    if any(result[j][0]>result[j+1][0] for j in range(len(result)-1)):
        print('TICK_ENCODING_AUDIT', 'count',len(raw),
              'head_timestamp_fields',[int(t.timestamp) for t in raw[:6]],
              'tail_timestamp_fields',[int(t.timestamp) for t in raw[-6:]],
              'first_last_decoded',[result[0][0],result[-1][0]],flush=True)
        raise RuntimeError('INVALID_RELATIVE_TICK_TIME')
    return result

@defer.inlineCallbacks
def collect():
    yield request('ProtoOAApplicationAuthReq',clientId=auth['CTRADER_CLIENT_ID'],
                  clientSecret=auth['CTRADER_CLIENT_SECRET'])
    grants=yield request('ProtoOAGetAccountListByAccessTokenReq',
                        accessToken=auth['CTRADER_ACCESS_TOKEN'])
    ids=[a for a in grants.ctidTraderAccount if a.isLive and
         str(a.traderLogin).endswith('4480')]
    if len(ids)!=1:raise RuntimeError('BROKER_ACCOUNT_BINDING_MISMATCH')
    acct=ids[0].ctidTraderAccountId
    yield request('ProtoOAAccountAuthReq',ctidTraderAccountId=acct,
                  accessToken=auth['CTRADER_ACCESS_TOKEN'])
    s=yield request('ProtoOASymbolsListReq',ctidTraderAccountId=acct,
                    includeArchivedSymbols=False)
    syms=[x for x in s.symbol if x.symbolName.upper()=='XAUUSD']
    if len(syms)!=1:raise RuntimeError('XAU_SYMBOL_MISSING')
    status={}
    for kind in ('BID','ASK'):
        r=yield request('ProtoOAGetTickDataReq',ctidTraderAccountId=acct,
                 symbolId=syms[0].symbolId,type=ProtoOAQuoteType.Value(kind),
                 fromTimestamp=int((T-timedelta(minutes=2)).timestamp()*1000),
                 toTimestamp=int((T+timedelta(minutes=2)).timestamp()*1000))
        values=decode(r)
        anchor=int(T.timestamp()*1000)
        known=[(tm,p) for tm,p in values if tm<=anchor]
        status[kind]={'count':len(values),'has_more':bool(r.hasMore),
             'first_utc':datetime.fromtimestamp(values[0][0]/1000,UTC).isoformat() if values else None,
             'last_utc':datetime.fromtimestamp(values[-1][0]/1000,UTC).isoformat() if values else None,
             'asof':known[-1][1] if known else None,
             'asof_age_ms':anchor-known[-1][0] if known else None}
    b=status['BID'];a=status['ASK']
    valid=(b['asof'] is not None and a['asof'] is not None and
           b['asof_age_ms']<=20000 and a['asof_age_ms']<=20000 and
           a['asof']>=b['asof'] and not a['has_more'] and not b['has_more'])
    obj={'source':'FP_MARKETS_CTRADER_NATIVE_TICK_SAMPLE',
         'type':'QUOTE_ONLY_NO_EXECUTION','anchor_utc':T.isoformat(),
         'quote_valid':bool(valid),'spread':round(a['asof']-b['asof'],5) if valid else None,
         'quotes':status,'orders_sent':False,'bridge_modified':False}
    (out/'XAU_NATIVE_TICK_PILOT.json').write_text(json.dumps(obj,indent=2))
    print('READ_ONLY_TICK_PILOT',json.dumps(obj),flush=True)

def finish(x):
    if hasattr(x,'check'):errors.append(x.getErrorMessage().split('\n')[0][:180])
    client.stopService()
    if reactor.running:reactor.stop()
    return None
def connected(_):
    global started
    if started:return
    started=True;collect().addBoth(finish)
client.setConnectedCallback(connected)
client.setDisconnectedCallback(lambda *_:finish(RuntimeError('DISCONNECTED')) if not started else None)
reactor.callLater(90,lambda:(errors.append('TICK_PILOT_TIMEOUT'),finish(None)))
client.startService();reactor.run()
if errors or not (out/'XAU_NATIVE_TICK_PILOT.json').is_file():
    raise RuntimeError('TICK_PILOT_FAILED:'+','.join(errors))
