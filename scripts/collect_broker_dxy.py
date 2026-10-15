"""Isolated cTrader candle reader: no orders, positions, token refresh or bridge."""
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from fx_scanner.dxy_broker_context import DIRECT_NAMES, WEIGHTS, normalize_symbol, evaluate_broker_dxy

READ_REQUESTS = frozenset({'ProtoOAApplicationAuthReq', 'ProtoOAGetAccountListByAccessTokenReq',
    'ProtoOAAccountAuthReq', 'ProtoOASymbolsListReq', 'ProtoOAGetTrendbarsReq'})


def main(output):
    from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
    from ctrader_open_api.messages import OpenApiMessages_pb2 as messages
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
    from twisted.internet import reactor, defer
    from twisted.internet.task import deferLater
    credentials={key: os.environ.get(key,'').strip() for key in
                 ['CTRADER_CLIENT_ID','CTRADER_CLIENT_SECRET','CTRADER_ACCESS_TOKEN']}
    if not all(credentials.values()):
        raise RuntimeError('DXY_READ_ONLY_CREDENTIALS_MISSING')
    client=Client(EndPoints.PROTOBUF_LIVE_HOST,EndPoints.PROTOBUF_PORT,TcpProtocol)
    errors=[]; started=False

    @defer.inlineCallbacks
    def request(name, **values):
        if name not in READ_REQUESTS:
            raise RuntimeError('DXY_READ_ONLY_PROTOCOL_GUARD')
        response=Protobuf.extract((yield client.send(getattr(messages,name)(**values),responseTimeoutInSeconds=20)))
        if response.DESCRIPTOR.name in {'ProtoOAErrorRes','ProtoErrorRes'}:
            raise RuntimeError('DXY_READ_ONLY_API_ERROR')
        return response

    @defer.inlineCallbacks
    def collect():
        yield request('ProtoOAApplicationAuthReq',clientId=credentials['CTRADER_CLIENT_ID'],clientSecret=credentials['CTRADER_CLIENT_SECRET'])
        grants=yield request('ProtoOAGetAccountListByAccessTokenReq',accessToken=credentials['CTRADER_ACCESS_TOKEN'])
        accounts=[a for a in grants.ctidTraderAccount if a.isLive and str(a.traderLogin).endswith('4480')]
        if len(accounts)!=1:
            raise RuntimeError('DXY_READ_ONLY_ACCOUNT_BINDING_MISMATCH')
        account=accounts[0].ctidTraderAccountId
        yield request('ProtoOAAccountAuthReq',ctidTraderAccountId=account,accessToken=credentials['CTRADER_ACCESS_TOKEN'])
        catalogue=yield request('ProtoOASymbolsListReq',ctidTraderAccountId=account,includeArchivedSymbols=False)
        symbols={s.symbolName.upper():s.symbolId for s in catalogue.symbol}
        candidates=[name for name in symbols if normalize_symbol(name) in DIRECT_NAMES]
        print('DXY_BROKER_DISCOVERY direct='+','.join(candidates)+' basket_present='+','.join(key for key in WEIGHTS if key in symbols),flush=True)
        now=datetime.now(UTC)

        @defer.inlineCallbacks
        def bars(name):
            yield deferLater(reactor,.3,lambda:None)
            response=yield request('ProtoOAGetTrendbarsReq',ctidTraderAccountId=account,symbolId=symbols[name],
                period=ProtoOATrendbarPeriod.Value('M5'),fromTimestamp=int((now-timedelta(hours=4)).timestamp()*1000),
                toTimestamp=int(now.timestamp()*1000),count=100)
            result=[]
            for bar in response.trendbar:
                close_at=datetime.fromtimestamp(bar.utcTimestampInMinutes*60,UTC)+timedelta(minutes=5)
                if close_at <= now:
                    result.append({'observed_at':close_at,'value':(bar.low+bar.deltaClose)/100000.})
            return result

        result={}; direct=[]; chosen=None
        for name in candidates:
            try:
                direct=yield bars(name)
                result=evaluate_broker_dxy(now=now,direct=direct,symbol=name)
                if result.get('available'):
                    chosen=name
                    break
            except Exception:
                continue
        if not result.get('available'):
            basket={}
            for name in WEIGHTS:
                if name not in symbols: continue
                try: basket[name]=yield bars(name)
                except Exception: continue
            result=evaluate_broker_dxy(now=now,basket=basket)
        result['collected_at']=now.isoformat()
        result['discovered_direct_symbols']=candidates
        path=Path(output);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(result,allow_nan=False))
        print('DXY_BROKER_READ_ONLY state='+str(result.get('state'))+' source='+str(result.get('source'))+' at='+str(result.get('current_at'))+' net_pct='+str(result.get('net_pct')),flush=True)

    def finish(value):
        if hasattr(value,'check'): errors.append(value.type.__name__)
        client.stopService()
        if reactor.running: reactor.stop()
        return None

    def connected(_):
        nonlocal started
        if started:return
        started=True
        collect().addBoth(finish)

    client.setConnectedCallback(connected)
    reactor.callLater(150,lambda:(errors.append('TIMEOUT'),finish(None)))
    client.startService();reactor.run()
    if errors or not Path(output).is_file():raise RuntimeError('DXY_READ_ONLY_COLLECTION_FAILED:'+','.join(errors))


if __name__=='__main__':main(sys.argv[1])
