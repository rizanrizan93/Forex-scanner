"""Isolated cTrader market-data reader; protocol allowlist excludes all orders.

Uses existing OAuth grants for XAU account suffix 4480. Never changes bindings,
refreshes tokens, reads positions, or contacts the cBot bridge.
"""
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from fx_scanner.reversal_scanner import evaluate, load_result

READ_REQUESTS = frozenset({"ProtoOAApplicationAuthReq", "ProtoOAGetAccountListByAccessTokenReq",
    "ProtoOAAccountAuthReq", "ProtoOASymbolsListReq", "ProtoOAGetTrendbarsReq"})


def main(output):
    from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
    from ctrader_open_api.messages import OpenApiMessages_pb2 as messages
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
    from twisted.internet import reactor, defer
    from twisted.internet.task import deferLater
    credentials={name:os.environ.get(name,"").strip() for name in
                 ["CTRADER_CLIENT_ID","CTRADER_CLIENT_SECRET","CTRADER_ACCESS_TOKEN"]}
    if not all(credentials.values()):
        raise RuntimeError("READ_ONLY_DATA_CREDENTIALS_MISSING")
    result=load_result()
    client=Client(EndPoints.PROTOBUF_LIVE_HOST,EndPoints.PROTOBUF_PORT,TcpProtocol)
    errors=[]; started=False

    @defer.inlineCallbacks
    def request(name, **values):
        if name not in READ_REQUESTS:
            raise RuntimeError("READ_ONLY_PROTOCOL_GUARD")
        message=getattr(messages,name)(**values)
        response=Protobuf.extract((yield client.send(message,responseTimeoutInSeconds=20)))
        if response.DESCRIPTOR.name in {"ProtoOAErrorRes","ProtoErrorRes"}:
            raise RuntimeError("READ_ONLY_API_ERROR:"+str(response.errorCode))
        return response

    @defer.inlineCallbacks
    def collect():
        yield request("ProtoOAApplicationAuthReq",clientId=credentials["CTRADER_CLIENT_ID"],clientSecret=credentials["CTRADER_CLIENT_SECRET"])
        grants=yield request("ProtoOAGetAccountListByAccessTokenReq",accessToken=credentials["CTRADER_ACCESS_TOKEN"])
        accounts=[a for a in grants.ctidTraderAccount if a.isLive and str(a.traderLogin).endswith("4480")]
        if len(accounts)!=1:
            raise RuntimeError("XAU_READ_ONLY_ACCOUNT_BINDING_MISMATCH")
        account=accounts[0].ctidTraderAccountId
        yield request("ProtoOAAccountAuthReq",ctidTraderAccountId=account,accessToken=credentials["CTRADER_ACCESS_TOKEN"])
        catalogue=yield request("ProtoOASymbolsListReq",ctidTraderAccountId=account,includeArchivedSymbols=False)
        symbols=[s for s in catalogue.symbol if s.symbolName.upper()=="XAUUSD"]
        if len(symbols)!=1: raise RuntimeError("XAU_READ_ONLY_SYMBOL_MISMATCH")
        now=datetime.now(UTC); begin=now-timedelta(days=14); end=now
        rows={}
        for _ in range(30):
            res=yield request("ProtoOAGetTrendbarsReq",ctidTraderAccountId=account,symbolId=symbols[0].symbolId,
                period=ProtoOATrendbarPeriod.Value("M1"),fromTimestamp=int(begin.timestamp()*1000),
                toTimestamp=int(end.timestamp()*1000),count=1000)
            if not res.trendbar: break
            oldest=end
            for bar in res.trendbar:
                stamp=datetime.fromtimestamp(bar.utcTimestampInMinutes*60,UTC)
                if stamp<oldest: oldest=stamp
                if stamp+timedelta(minutes=1)>now: continue
                rows[stamp.isoformat()]={"timestamp":stamp.isoformat(), "low":bar.low/100000.,
                    "open":(bar.low+bar.deltaOpen)/100000.,"high":(bar.low+bar.deltaHigh)/100000.,
                    "close":(bar.low+bar.deltaClose)/100000.}
            if oldest<=begin or oldest>=end or len(res.trendbar)<1000: break
            end=oldest-timedelta(milliseconds=1)
            yield deferLater(reactor,.3,lambda:None)  # historical API rate cap
        if not rows: raise RuntimeError("XAU_READ_ONLY_BARS_EMPTY")
        snapshot=evaluate(list(rows.values()),result,now=now)
        Path(output).parent.mkdir(parents=True,exist_ok=True)
        Path(output).write_text(json.dumps(snapshot,indent=2,allow_nan=False)+"\n")
        print("REVERSAL_SCANNER_READ_ONLY state="+snapshot["state"]+" bars="+str(len(rows))+" execution_authority=False",flush=True)

    def finish(value):
        if hasattr(value,"check"): errors.append(value.type.__name__)
        client.stopService()
        if reactor.running: reactor.stop()
        return None

    def connected(_):
        nonlocal started
        if started: return
        started=True
        collect().addBoth(finish)

    client.setConnectedCallback(connected)
    client.setDisconnectedCallback(lambda *_: finish(RuntimeError("DATA_DISCONNECTED")) if not started else None)
    reactor.callLater(180,lambda: (errors.append("DATA_TIMEOUT"),finish(None)))
    client.startService(); reactor.run()
    if errors or not Path(output).is_file(): raise RuntimeError("READ_ONLY_COLLECTION_FAILED:"+",".join(errors))


if __name__=="__main__":
    main(sys.argv[1])
