"""Historical FP Markets BID/ASK tick probe, never an order, token refresh or bridge."""
from datetime import UTC,datetime,timedelta
from pathlib import Path
import json,os,sys
from ctrader_open_api import Client,Protobuf,TcpProtocol,EndPoints
from ctrader_open_api.messages import OpenApiMessages_pb2 as messages
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAQuoteType
from twisted.internet import reactor,defer
from twisted.internet.task import deferLater

ALLOWED=frozenset(('ProtoOAApplicationAuthReq','ProtoOAGetAccountListByAccessTokenReq',
                    'ProtoOAAccountAuthReq','ProtoOASymbolsListReq','ProtoOAGetTickDataReq'))
ANCHORS=[['2026-05-22T11:44:00Z','entry'],['2026-05-24T22:01:00Z','exit'],['2026-05-25T12:35:00Z','entry'],['2026-05-26T09:15:00Z','exit'],['2026-05-29T13:00:00Z','entry'],['2026-05-29T14:01:00Z','exit'],['2026-06-10T13:45:00Z','entry'],['2026-06-10T15:48:00Z','exit'],['2026-07-14T17:14:00Z','entry'],['2026-07-15T02:20:00Z','exit'],['2026-07-15T15:11:00Z','entry'],['2026-07-16T06:37:00Z','exit'],['2026-09-04T10:14:00Z','entry'],['2026-09-04T12:30:00Z','exit'],['2026-09-24T02:52:00Z','entry'],['2026-09-24T08:25:00Z','exit']]
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
    price=int(raw[0].tick)
    result=[]
    for i,t in enumerate(raw):
        if i:
            absolute+=int(t.timestamp)  # negative time delta for earlier quote
            price+=int(t.tick)           # signed price delta from preceding quote
        result.append((absolute,round(price/100000,5)))
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
    rows=[]
    for event_i,(iso,kind_label) in enumerate(ANCHORS):
        T=datetime.fromisoformat(iso.replace('Z','+00:00')).astimezone(UTC)
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
            yield deferLater(reactor,.35,lambda:None)
        b=status['BID'];a=status['ASK']
        valid=(b['asof'] is not None and a['asof'] is not None and
               b['asof_age_ms']<=20000 and a['asof_age_ms']<=20000 and
               1000<b['asof']<10000 and 1000<a['asof']<10000 and
               a['asof']>=b['asof'] and not a['has_more'] and not b['has_more'])
        row={'event_id':event_i//2+1,'event_type':kind_label,'anchor_utc':T.isoformat(),
             'quote_valid':bool(valid),'spread':round(a['asof']-b['asof'],5) if valid else None,
             'bid_asof':b['asof'],'ask_asof':a['asof'],'bid_age_ms':b['asof_age_ms'],
             'ask_age_ms':a['asof_age_ms'],'bid_count':b['count'],'ask_count':a['count'],
             'bid_has_more':b['has_more'],'ask_has_more':a['has_more']}
        rows.append(row)
        print('READ_ONLY_EVENT',row['event_id'],kind_label,'valid',row['quote_valid'],
              'spread',row['spread'],flush=True)
    entry_spreads=[r['spread'] for r in rows if r['quote_valid'] and r['event_type']=='entry']
    import statistics,csv
    with (out/'XAU_NATIVE_QUOTE_16_EVENTS.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    result={'source':'FP_MARKETS_CTRADER_NATIVE_TICK_BID_ASK',
         'mode':'QUOTE_ONLY_NO_ORDER_FILLS','events_expected':16,'events_complete':len(rows),
         'events_valid':sum(r['quote_valid'] for r in rows),
         'entry_valid':len(entry_spreads),
         'entry_spread_median':statistics.median(entry_spreads) if entry_spreads else None,
         'entry_spread_max':max(entry_spreads) if entry_spreads else None,
         'reference_proxy_p50_spread':.33700576,'bridge_or_bot_modified':False,
         'full_native_tick_execution_replay':False}
    (out/'XAU_NATIVE_TICK_AUDIT.json').write_text(json.dumps(result,indent=2))
    print('READ_ONLY_TICK_16_SUMMARY',json.dumps(result),flush=True)

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
reactor.callLater(240,lambda:(errors.append('TICK_PILOT_TIMEOUT'),finish(None)))
client.startService();reactor.run()
if errors or not (out/'XAU_NATIVE_TICK_AUDIT.json').is_file():
    raise RuntimeError('TICK_PILOT_FAILED:'+','.join(errors))
