"""Historical data requests only; no order execution or token refresh."""
import csv, hashlib, json, os, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
OUT = Path('evidence')
ALLOWED = frozenset({'ProtoOAApplicationAuthReq','ProtoOAAccountAuthReq',
    'ProtoOAGetAccountListByAccessTokenReq','ProtoOASymbolsListReq',
    'ProtoOASymbolByIdReq','ProtoOAGetTrendbarsReq','ProtoOATraderReq',
    'ProtoOAReconcileReq','ProtoOAGetPositionUnrealizedPnLReq',
    'ProtoOADealListReq','ProtoOAOrderListReq'})

def guard(message):
    if type(message).__name__ not in ALLOWED:
        raise RuntimeError('NON_READ_REQUEST_BLOCKED')

def sanitize(x):
    if isinstance(x, dict):
        return {k:sanitize(v) for k,v in x.items() if k.lower() not in
            {'ctidtraderaccountid','accountnumber','traderlogin','accesstoken',
             'refreshtoken','clientsecret','clientid'}}
    if isinstance(x,list): return [sanitize(v) for v in x]
    return x

def main():
    from google.protobuf.json_format import MessageToDict
    from ctrader_open_api.messages import OpenApiMessages_pb2 as messages
    from fx_scanner.execution.ctrader_session import CTraderOpenApiSession
    from fx_scanner.live_account_readonly import _select_account

    class ReadSession(CTraderOpenApiSession):
        def _send_sync(self, message, **kwargs):
            guard(message)
            time.sleep(.3)
            return super()._send_sync(message, **kwargs)

    OUT.mkdir(exist_ok=True)
    now = datetime.now(UTC).replace(second=0,microsecond=0)
    start = datetime(2026,11,1,tzinfo=UTC)
    summary = {'observed_utc':now.isoformat(),'account_suffix':'7903',
        'execution_authority':'NONE','errors':[],'bars':{},'history':{}}
    session = ReadSession(client_id=os.environ['CTRADER_CLIENT_ID'],
        client_secret=os.environ['CTRADER_CLIENT_SECRET'],
        access_token=os.environ['CTRADER_ACCESS_TOKEN'],account_id=None,
        refresh_token=None,allow_token_refresh=False,environment='live',
        request_timeout_seconds=25)
    try:
        account = _select_account(session.granted_accounts(),symbol='XAUUSD')
        if not account.is_live or str(account.trader_login)[-4:]!='7903':
            raise RuntimeError('ACCOUNT_IDENTITY_MISMATCH')
        session.account_id=account.ctid_trader_account_id
        session.connect()
        session.load_symbols(['XAUUSD','EURUSD','BTCUSD'])
        catalogue={s:sanitize(MessageToDict(session.symbol_info(s),preserving_proto_field_name=True))
                   for s in ['XAUUSD','EURUSD','BTCUSD']}
        (OUT/'contracts.json').write_text(json.dumps(catalogue))
        (OUT/'account.json').write_text(json.dumps(sanitize({
            'trader':MessageToDict(session.trader(),preserving_proto_field_name=True),
            'positions_pending':MessageToDict(session.reconcile(),preserving_proto_field_name=True),
            'pnl':MessageToDict(session.unrealized_pnl(),preserving_proto_field_name=True)})))

        for kind,cls_name,field in [('orders','ProtoOAOrderListReq','order'),
                                   ('deals','ProtoOADealListReq','deal')]:
            records=[]
            def collect(lo,hi):
                req=getattr(messages,cls_name)()
                req.ctidTraderAccountId=session.account_id
                req.fromTimestamp=int(lo.timestamp()*1000)
                req.toTimestamp=int(hi.timestamp()*1000)-1
                if 'maxRows' in req.DESCRIPTOR.fields_by_name:req.maxRows=1000
                res=session._send_sync(req)
                if getattr(res,'hasMore',False):
                    if (hi-lo).total_seconds()<=1:raise RuntimeError('HISTORY_TRUNCATED')
                    mid=lo+(hi-lo)/2
                    collect(lo,mid);collect(mid,hi)
                else:records.extend(sanitize(MessageToDict(v,preserving_proto_field_name=True))
                                    for v in getattr(res,field,()))
            try:
                lo=start
                while lo<now:
                    hi=min(lo+timedelta(days=1),now);collect(lo,hi);lo=hi
                (OUT/(kind+'.json')).write_text(json.dumps(records))
                summary['history'][kind]={'count':len(records),'complete':True,
                    'from_utc':start.isoformat(),'through_utc':now.isoformat()}
            except Exception as e:
                summary['history'][kind]={'complete':False,'error_type':type(e).__name__}
                summary['errors'].append(kind+':'+type(e).__name__)

        for symbol in ['XAUUSD','EURUSD','BTCUSD']:
            bars={};lo=(now-timedelta(days=21)).replace(hour=0,minute=0)
            try:
                while lo<now:
                    hi=min(lo+timedelta(days=1),now)
                    try:
                        result=session.historical_bars(symbol,'M1',from_time=lo,
                            to_time=hi,count=2000)
                    except Exception as e:
                        if 'returned no M1 bars' not in str(e):raise
                        result=()
                    for b in result:
                        if lo<=b.timestamp<hi and b.timestamp+timedelta(minutes=1)<=now:
                            bars[b.timestamp]=b
                    lo=hi
                path=OUT/(symbol+'_M1.csv')
                with path.open('w') as f:
                    w=csv.writer(f);w.writerow(['utc','open','high','low','close'])
                    for at,b in sorted(bars.items()):
                        w.writerow([at.isoformat(),b.open,b.high,b.low,b.close])
                summary['bars'][symbol]={'count':len(bars),'first':min(bars).isoformat() if bars else None,
                    'last':max(bars).isoformat() if bars else None,
                    'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                    'source':'CTRADER_LIVE_BROKER','spread_history_available':False}
            except Exception as e:
                summary['errors'].append(symbol+':'+type(e).__name__)
                summary['bars'][symbol]={'error_type':type(e).__name__}
        summary['allowed_request_types']=sorted(ALLOWED)
    except Exception as e:
        summary['errors'].append('SESSION:'+type(e).__name__)
    finally:
        session.close()
        (OUT/'broker_summary.json').write_text(json.dumps(summary,indent=2))
        print('BROKER_EVIDENCE='+json.dumps(summary),flush=True)

if __name__=='__main__':main()
