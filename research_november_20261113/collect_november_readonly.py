"""Price candles only. No execution, refresh, account telemetry or bridge access."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import csv, hashlib, json, os, time

UTC=timezone.utc
START=datetime(2026,10,1,tzinfo=UTC)
END=datetime(2026,11,13,3,0,tzinfo=UTC)
ALLOWED=frozenset({'ProtoOAApplicationAuthReq','ProtoOAAccountAuthReq',
 'ProtoOAGetAccountListByAccessTokenReq','ProtoOASymbolsListReq',
 'ProtoOASymbolByIdReq','ProtoOAGetTrendbarsReq','ProtoHeartbeatEvent'})

def guard(name):
    if name not in ALLOWED:raise RuntimeError('READ_ONLY_PROTOCOL_BLOCK')

def main():
    from fx_scanner.execution.ctrader_session import CTraderOpenApiSession
    class Reader(CTraderOpenApiSession):
        def _send_sync(self,message,**kwargs):
            guard(message.DESCRIPTOR.name)
            time.sleep(.30)
            return super()._send_sync(message,**kwargs)
        def send_new_order(self,*args,**kwargs):raise RuntimeError('ORDER_DISABLED')
        def cancel_order(self,*args,**kwargs):raise RuntimeError('ORDER_DISABLED')
    for blocked in ['ProtoOANewOrderReq','ProtoOAClosePositionReq','ProtoOAAmendPositionSLTPReq','ProtoOARefreshTokenReq']:
        try:guard(blocked)
        except RuntimeError:pass
        else:raise AssertionError('GUARD_FAILED')
    out=Path('artifacts/november_prices');out.mkdir(parents=True,exist_ok=True)
    end=min(END,datetime.now(UTC).replace(second=0,microsecond=0))
    report={'read_only':True,'execution_authority':False,'from_utc':START.isoformat(),
      'through_exclusive_utc':end.isoformat(),'source':'CTRADER_BROKER_M1_TRENDBAR',
      'native_tick_bid_ask':False,'historical_spread_available':False,'instruments':{}}
    client=Reader(client_id=os.environ['CTRADER_CLIENT_ID'],
      client_secret=os.environ['CTRADER_CLIENT_SECRET'],access_token=os.environ['CTRADER_ACCESS_TOKEN'],
      account_id=None,environment='live',refresh_token=None,allow_token_refresh=False,
      request_timeout_seconds=25)
    try:
        accounts=[a for a in client.granted_accounts() if a.is_live and str(a.trader_login).endswith('7903')]
        if len(accounts)!=1:raise RuntimeError('ACCOUNT_BINDING_MISMATCH')
        client.account_id=accounts[0].ctid_trader_account_id
        client.connect();client.load_symbols(['XAUUSD','EURUSD','BTCUSD'])
        for symbol in ['XAUUSD','EURUSD','BTCUSD']:
            rows={};lo=START;pages=0
            while lo<end:
                hi=min(lo+timedelta(days=1),end);cursor=hi
                while cursor>lo:
                    try:batch=client.historical_bars(symbol,'M1',from_time=lo,to_time=cursor,count=2000)
                    except Exception as e:
                        if 'returned no M1 bars' in str(e):batch=[]
                        else:raise
                    pages+=1
                    if not batch:break
                    oldest=min(b.timestamp for b in batch)
                    for b in batch:
                        if not (START<=b.timestamp and b.timestamp+timedelta(minutes=1)<=end):continue
                        values=[b.open,b.high,b.low,b.close]
                        if min(values)<=0 or b.high<max(values) or b.low>min(values):raise RuntimeError('INVALID_OHLC')
                        if b.timestamp in rows and rows[b.timestamp]!=values:raise RuntimeError('CONFLICTING_CANDLE')
                        rows[b.timestamp]=values
                    if oldest<=lo:break
                    if oldest>=cursor:raise RuntimeError('NO_PAGINATION_PROGRESS')
                    cursor=oldest-timedelta(milliseconds=1)
                    if pages>500:raise RuntimeError('REQUEST_LIMIT')
                lo=hi
            if not rows:raise RuntimeError('NO_CANDLES:'+symbol)
            p=out/(symbol+'_M1.csv')
            with p.open('w',newline='') as f:
                w=csv.writer(f);w.writerow(['timestamp','open','high','low','close'])
                for at,values in sorted(rows.items()):w.writerow([at.isoformat(),*values])
            report['instruments'][symbol]={'bars':len(rows),'first':min(rows).isoformat(),
              'last':max(rows).isoformat(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
              'request_pages':pages}
            print('PRICE_COLLECTION',symbol,len(rows),min(rows).isoformat(),max(rows).isoformat(),flush=True)
    finally:
        client.close()
        (out/'PROVENANCE.json').write_text(json.dumps(report,indent=2))
    assert set(report['instruments'])=={'XAUUSD','EURUSD','BTCUSD'}
    print('NOVEMBER_READONLY_COLLECTION_COMPLETE',flush=True)

if __name__=='__main__':main()
