"""Isolated V1.3.0 BTC data/checkpoint bridge. NO execution or broker credentials.
Bind loopback only, behind an independently configured WSS :25345 reverse proxy.
This file never loads production .env or imports a trading executor.
"""
from __future__ import annotations
import asyncio,csv,hashlib,hmac,json,math,os,re,struct,time,urllib.request
from pathlib import Path
from websockets.asyncio.server import serve
import store_base as durable

CONTRACT='RZ-7D130-BTC8500283-LFOLLOW-WEEKEND'
PREFIX='RZBTC7D130'
SEED_SHA='e041102102e4ae2768e06f0261b4bfbfabc056ffa5decde21e161d8904179030'
SEED_END=1792108800
# Reuse audited SQLite CAS/lease/lost-ACK code; isolated namespace/database.
durable.CONTRACTS={PREFIX:{'hash':CONTRACT,'schema':1,'execution_model':None}}
Store=durable.Store

def identity(key,lease,contract,account):
    if key!=f'{PREFIX}:{account}:BTCUSD' or not re.fullmatch('[a-f0-9]{32}',lease) or contract!=CONTRACT:
        raise ValueError('IDENTITY_INVALID')

def dumps(value):return json.dumps(value,allow_nan=False,separators=(',',':'))

class Feed:
    def __init__(self,seed):
        with Path(seed).open() as f:
            self.bars=[[int(a['unix']),*[float(a[k]) for k in ['open','high','low','close']],int(a['count'])] for a in csv.DictReader(f)]
        raw=b''.join(struct.pack('<qddddi',*a) for a in self.bars)
        if len(self.bars)!=68280 or hashlib.sha256(raw).hexdigest()!=SEED_SHA:raise ValueError('SEED_HASH')
        self.minutes={};self.next_minute=SEED_END;self.cached=None
    def wire(self,now):
        through=int(now)//3600*3600
        if self.bars[-1][0]+3600!=through:raise ValueError('FEED_NOT_CURRENT')
        if self.cached is None or self.cached[0]!=through:self.cached=(through,dumps({'type':'feed','contract':CONTRACT,'source':'BITSTAMP_BTCUSD_M1','through':through,'bars':self.bars}))
        return self.cached[1]
    def ingest(self,values,now):
        # Strict consecutive closed M1 after the immutable seed: gaps block publication.
        target=int(now)//60*60
        parsed=[]
        for a in values:
            at=int(a['timestamp']);p=[float(a[k]) for k in ['open','high','low','close']]
            if at%60 or any(not math.isfinite(v) or v<=0 for v in p) or p[1]<max(p[0],p[3]) or p[2]>min(p[0],p[3]) or p[2]>p[1]:raise ValueError('M1_INVALID')
            if at>=self.next_minute and at<target:parsed.append([at,*p])
        parsed.sort()
        for a in parsed:
            at=a[0]
            if at<self.next_minute:continue
            if at!=self.next_minute:raise ValueError('M1_GAP')
            self.minutes[at]=a;self.next_minute=at+60
            if self.next_minute%3600==0:
                start=self.next_minute-3600;q=[self.minutes.pop(t) for t in range(start,self.next_minute,60)]
                self.bars.append([start,q[0][1],max(x[2] for x in q),min(x[3] for x in q),q[-1][4],60])
    def update(self,now):
        target=int(now)//60*60
        # Bounded catch-up; feed stays unavailable until all missing hours close.
        for _ in range(20):
            if self.next_minute>=target:return
            end=min(target-60,self.next_minute+999*60)
            url=f'https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=60&limit=1000&start={self.next_minute}&end={end}&exclude_current_candle=true'
            request=urllib.request.Request(url,headers={'User-Agent':'RizanFrozen7D130-data-only'})
            with urllib.request.urlopen(request,timeout=10) as reply:
                # Bound untrusted response memory, verify JSON and endpoint symbol.
                raw=reply.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError('API_RESPONSE_SIZE')
            body=durable.strict_load(raw)
            if body['data']['pair'].lower().replace('/','')!='btcusd':raise ValueError('API_SYMBOL')
            previous=self.next_minute;self.ingest(body['data']['ohlc'],now)
            if self.next_minute==previous:raise ValueError('API_NO_PROGRESS')

class Bridge:
    def __init__(self,store,feed,token,account,clock=time.time):
        if len(token)<32 or not re.fullmatch('[0-9]+',account):raise ValueError('CONFIG_INVALID')
        self.store,self.feed,self.token,self.account,self.clock=store,feed,token,account,clock;self.peers={};self.sent={}
    async def data(self,ws):
        try:wire=self.feed.wire(self.clock());stamp=int(self.clock())//3600
        except Exception:wire=dumps({'type':'feed_unavailable'});stamp=-1
        if self.sent.get(ws)==stamp:return
        await ws.send(wire);self.sent[ws]=stamp
    async def handler(self,ws):
        try:
            hello=durable.strict_load(await asyncio.wait_for(ws.recv(),10))
            if hello.get('type')!='hello' or not hmac.compare_digest(str(hello.get('token','')),self.token):raise ValueError('AUTH_FAILED')
            key,lease=hello.get('key',''),hello.get('lease','')
            identity(key,lease,hello.get('contract'),self.account)
            if key in self.peers.values():raise ValueError('LEASE_BUSY')
            version,state=self.store.acquire(key,lease);self.peers[ws]=key
            await ws.send(dumps({'type':'ready','revision':version,'state':state}));await self.data(ws)
            async for raw in ws:
                request=durable.strict_load(raw);kind=request.get('type')
                if kind=='ping':
                    self.store.touch(key,lease);await ws.send(dumps({'type':'pong'}));await self.data(ws)
                elif kind=='save':
                    state=request['state']
                    # No command messages, per-account server binding, bounded durable state.
                    if len(dumps(state))>16000:raise ValueError('STATE_TOO_LARGE')
                    revision=self.store.save(key,lease,request['base_revision'],request['client_revision'],state)
                    await ws.send(dumps({'type':'ack','revision':revision,'client_revision':request['client_revision']}))
                else:raise ValueError('MESSAGE_INVALID')
        except ValueError as exc:
            # Only fixed codes are sent; never reflect a token, payload or exception text.
            known={'AUTH_FAILED','IDENTITY_INVALID','LEASE_BUSY','LEASE_EXPIRED','REVISION_CONFLICT','STATE_REVISION_REUSE_CONFLICT','MESSAGE_INVALID','STATE_TOO_LARGE'}
            await ws.send(dumps({'type':'error','code':str(exc) if str(exc) in known else 'STATE_INVALID'}));await ws.close(code=1008)
        except Exception:await ws.close(code=1011)
        finally:self.peers.pop(ws,None);self.sent.pop(ws,None)

async def main():
    # A new explicit research DB is mandatory; no implicit production path.
    db=Path(os.environ['RZ7D_STATE_DB']).resolve();seed=Path(os.environ['RZ7D_SEED_CSV']).resolve()
    if db.name!='btc7d130-research.sqlite':raise SystemExit('Research DB basename required')
    port=int(os.environ.get('RZ7D_LOOPBACK_PORT','8130'))
    if port==25345:raise SystemExit('Use isolated loopback backend; do not take production WSS port')
    os.umask(0o077)
    feed=Feed(seed);bridge=Bridge(Store(db),feed,os.environ['RZ7D_TOKEN'],os.environ['RZ7D_ACCOUNT'])
    async def refresh():
        while True:
            try:await asyncio.to_thread(feed.update,time.time())
            except Exception:pass  # stale feed remains blocked, never substitute broker bars
            for ws in tuple(bridge.peers):
                try:await bridge.data(ws)
                except Exception:pass
            await asyncio.sleep(1)
    async with serve(bridge.handler,'127.0.0.1',port,max_size=32000,max_queue=8,ping_interval=15,ping_timeout=15,compression=None):
        await refresh()
if __name__=='__main__':asyncio.run(main())
