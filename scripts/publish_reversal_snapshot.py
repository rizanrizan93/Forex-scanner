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
from fx_scanner.zone_v05 import evaluate as evaluate_v05, blank as blank_v05
from fx_scanner.zone_v05_quotes import spread_asof
from fx_scanner.manual_reversal_map import evaluate as evaluate_manual, CONTRACT as MANUAL_CONTRACT

READ_REQUESTS = frozenset({"ProtoOAApplicationAuthReq", "ProtoOAGetAccountListByAccessTokenReq",
    "ProtoOAAccountAuthReq", "ProtoOASymbolsListReq", "ProtoOAGetTrendbarsReq", "ProtoOAGetTickDataReq"})


def main(output):
    from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
    from ctrader_open_api.messages import OpenApiMessages_pb2 as messages
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod, ProtoOAQuoteType
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
            # The backend may return 999 for count=1000. A short page is not
            # proof that history ended. Continue until range exhausted/empty.
            if oldest<=begin or oldest>=end: break
            end=oldest-timedelta(milliseconds=1)
            yield deferLater(reactor,.3,lambda:None)  # historical API rate cap
        if not rows: raise RuntimeError("XAU_READ_ONLY_BARS_EMPTY")
        snapshot=evaluate(list(rows.values()),result,now=now)
        Path(output).parent.mkdir(parents=True,exist_ok=True)
        Path(output).write_text(json.dumps(snapshot,indent=2,allow_nan=False)+"\n")
        # Reuse this existing read-only connection; do not start another collector,
        # touch the cBot bridge, renew OAuth, or alter the legacy snapshot contract.
        native={"M1":list(rows.values())}
        manual={"contract":MANUAL_CONTRACT,"symbol":"XAUUSD","as_of":now.isoformat(),
            "execution_authority":False,"execution_influence":False,"probability":None,
            "validation_status":"MANUAL_REFERENCE_NOT_CALIBRATED","state":"DATA_UNAVAILABLE","zones":[],"plans":[]}
        try:
            for tf,days,count in [("H4",100,600),("H1",60,900),("M15",15,900),("M5",6,900)]:
                yield deferLater(reactor,.3,lambda:None)
                res=yield request("ProtoOAGetTrendbarsReq",ctidTraderAccountId=account,symbolId=symbols[0].symbolId,
                    period=ProtoOATrendbarPeriod.Value(tf),fromTimestamp=int((now-timedelta(days=days)).timestamp()*1000),
                    toTimestamp=int(now.timestamp()*1000),count=count)
                native[tf]=[{"timestamp":datetime.fromtimestamp(b.utcTimestampInMinutes*60,UTC).isoformat(),
                    "low":b.low/100000.,"open":(b.low+b.deltaOpen)/100000.,
                    "high":(b.low+b.deltaHigh)/100000.,"close":(b.low+b.deltaClose)/100000.} for b in res.trendbar]
            # H2 is derived from two closed H1 bars. Native H12 is
            # preferred because broker H4 sessions need not align to UTC
            # 00/04/08 boundaries. D1/W1 are optional HTF
            # reference; one unsupported period must not remove the H1 map.
            for tf, days, count in [("H12", 150, 320), ("D1", 600, 650), ("W1", 1200, 250)]:
                try:
                    yield deferLater(reactor, .3, lambda: None)
                    res=yield request("ProtoOAGetTrendbarsReq",
                        ctidTraderAccountId=account, symbolId=symbols[0].symbolId,
                        period=ProtoOATrendbarPeriod.Value(tf),
                        fromTimestamp=int((now-timedelta(days=days)).timestamp()*1000),
                        toTimestamp=int(now.timestamp()*1000), count=count)
                    native[tf]=[{"timestamp":datetime.fromtimestamp(b.utcTimestampInMinutes*60,UTC).isoformat(),
                        "low":b.low/100000., "open":(b.low+b.deltaOpen)/100000.,
                        "high":(b.low+b.deltaHigh)/100000.,
                        "close":(b.low+b.deltaClose)/100000.} for b in res.trendbar]
                except Exception:
                    # HTF optional context absent, never synthesize from M1.
                    native[tf]=[]
                    print("MANUAL_OPTIONAL_"+tf+"_UNAVAILABLE",flush=True)
            manual=evaluate_manual(native,now=now)
        except Exception:
            # Fail closed for the optional manual panel; keep the existing read-only
            # legacy snapshot usable. No source exception or credential is published.
            print("MANUAL_REVERSAL_DATA_UNAVAILABLE",flush=True)
        # The same native feed evaluates V05. Historical quotes only: no orders,
        # spot subscriptions, token changes, positions or cBot bridge calls.
        v05=blank_v05(now)
        try:
            previous_path=Path(output).with_name('zone_v05_previous.json')
            previous=json.loads(previous_path.read_text()) if previous_path.exists() else None
            v05=evaluate_v05(native,now=now,previous=previous)
            anchors=v05.get('quote_anchors',[])
            spreads={}
            for anchor in anchors[:8]:
                T=datetime.fromisoformat(anchor);quotes={}
                for kind in ('BID','ASK'):
                    yield deferLater(reactor,.3,lambda:None)
                    r=yield request('ProtoOAGetTickDataReq',ctidTraderAccountId=account,
                        symbolId=symbols[0].symbolId,type=ProtoOAQuoteType.Value(kind),
                        fromTimestamp=int((T-timedelta(seconds=30)).timestamp()*1000),
                        toTimestamp=int(T.timestamp()*1000))
                    quotes[kind]=r
                value=spread_asof(quotes['BID'],quotes['ASK'],int(T.timestamp()*1000))
                if value is not None:spreads[anchor]=value
            v05=evaluate_v05(native,now=now,spreads=spreads,previous=previous)
        except Exception:
            v05=blank_v05(now,'V05_DATA_UNAVAILABLE')
            print('V05_DATA_UNAVAILABLE',flush=True)
        Path(output).with_name('zone_v05_snapshot.json').write_text(json.dumps(v05,indent=2,allow_nan=False)+'\n')
        Path(output).with_name("manual_reversal_snapshot.json").write_text(json.dumps(manual,indent=2,allow_nan=False)+"\n")
        print("REVERSAL_SCANNER_READ_ONLY state="+snapshot["state"]+" bars="+str(len(rows))+" execution_authority=False",flush=True)
        print("MANUAL_REVERSAL_READ_ONLY state="+manual["state"]+" plans="+str(len(manual["plans"]))+" execution_influence=False",flush=True)

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
