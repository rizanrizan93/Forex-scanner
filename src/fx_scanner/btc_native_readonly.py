"""Independent public Bitstamp mirror of the pinned V1 feed. Never opens a bridge lease.

Native formulas: source/BtcCore.cs, BtcEntryGate.cs and EntryFamilies.cs at
90172c2fba345e4221ca822c8e7d1d760a98c6b1. Scores are candle predicates only.
"""
from __future__ import annotations
import gzip
import hashlib
import json
import math
import struct
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode

SEED_END = 1792108800
SEED_HASH = 'e041102102e4ae2768e06f0261b4bfbfabc056ffa5decde21e161d8904179030'
SEED_URL = ('https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/'
            '90172c2fba345e4221ca822c8e7d1d760a98c6b1/repairs/buy050_identity_20261108/bridge/BTC_SEED_PACKET.json.gz')
CONTRACT = 'RZ-7D130-BTC8500283-LFOLLOW-WEEKEND'
SOURCE = 'BITSTAMP_BTCUSD_M1'


def get_bytes(url, limit):
    for attempt in range(2):
        try:
            with urlopen(Request(url, headers={'User-Agent':'Rizan-V1-readonly-audit/1'}), timeout=12) as response:
                data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError('BTC_SOURCE_TOO_LARGE')
            return data
        except OSError:
            if attempt:
                raise


def valid_bar(row):
    if not isinstance(row, list) or len(row) != 6:
        return False
    at,o,h,l,c,n = row
    return (type(at) is int and at % 3600 == 0 and type(n) is int and 1 <= n <= 60
            and all(type(x) in (int,float) and math.isfinite(x) and x > 0 for x in (o,h,l,c))
            and l <= min(o,c) <= max(o,c) <= h)


def validate_seed(packet):
    if packet.get('contract') != CONTRACT or packet.get('source') != SOURCE or packet.get('through') != SEED_END:
        raise ValueError('BTC_SEED_CONTRACT')
    rows = packet.get('bars', [])
    if len(rows) != 68280:
        raise ValueError('BTC_SEED_COVERAGE')
    digest = hashlib.sha256(); previous = -1
    for row in rows:
        if not valid_bar(row) or row[0] <= previous or row[0]+3600 > SEED_END:
            raise ValueError('BTC_SEED_BAR')
        digest.update(struct.pack('<qddddi', *row)); previous = row[0]
    if rows[0][0] != 1546300800 or previous+3600 != SEED_END or digest.hexdigest() != SEED_HASH:
        raise ValueError('BTC_SEED_HASH')
    return rows


def load_seed():
    raw = gzip.decompress(get_bytes(SEED_URL, 2_000_000))
    if len(raw) > 16_000_000:
        raise ValueError('BTC_SEED_TOO_LARGE')
    return validate_seed(json.loads(raw))


def load_minutes(start, end):
    query = urlencode(dict(step=60,limit=1000,start=start,end=end-1,exclude_current_candle='true'))
    rows = json.loads(get_bytes('https://www.bitstamp.net/api/v2/ohlc/btcusd/?'+query, 1_000_000))['data']['ohlc']
    candidate = {}
    for r in rows:
        at=int(r['timestamp']);o,h,l,c=(float(r[k]) for k in ('open','high','low','close'))
        if at%60 or not all(math.isfinite(x) and x>0 for x in (o,h,l,c)) or not l<=min(o,c)<=max(o,c)<=h:
            raise ValueError('BTC_MINUTE_OHLC')
        if not start <= at < end:
            continue
        row=[at,o,h,l,c,1]
        if at in candidate and candidate[at] != row:
            raise ValueError('BTC_DUPLICATE_CONFLICT')
        candidate[at]=row
    # Match native BtcFeed: tolerate harmless response ordering/extras, never gaps/conflicts.
    if set(candidate) != set(range(start,end,60)):
        raise ValueError('BTC_EXTENSION_GAP')
    return [candidate[t] for t in range(start,end,60)]


def aggregate(rows, seconds):
    out=[]
    for at,o,h,l,c,n in rows:
        bucket=at//seconds*seconds
        if not out or out[-1][0] != bucket:out.append([bucket,o,h,l,c,n])
        else:
            b=out[-1];b[2]=max(b[2],h);b[3]=min(b[3],l);b[4]=c;b[5]+=n
    return out


def build_packet(through, seed_rows, read_chunk=load_minutes):
    if type(through) is not int or through%3600 or through<SEED_END or through>SEED_END+100000*3600:
        raise ValueError('BTC_THROUGH_INVALID')
    # Validate the original artifact even when a cached downloader is injected.
    validate_seed(dict(contract=CONTRACT,source=SOURCE,through=SEED_END,bars=seed_rows))
    chunks=[(start,min(start+60000,through)) for start in range(SEED_END,through,60000)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        batches=list(pool.map(lambda bounds:read_chunk(*bounds),chunks))
    minutes=[r for batch in batches for r in batch]
    if [r[0] for r in minutes] != list(range(SEED_END,through,60)):
        raise ValueError('BTC_EXTENSION_GAP')
    extension=aggregate(minutes,3600)
    if any(not valid_bar(r) or r[5]!=60 for r in extension):
        raise ValueError('BTC_EXTENSION_INVALID')
    return dict(contract=CONTRACT,source=SOURCE,through=through,seed_hash=SEED_HASH,
                bars=seed_rows+extension,read_only=True,execution_authority=False)


def features(rows):
    result=[];atr=up=dn=fast=slow=0.
    for i,b in enumerate(rows):
        at,o,h,l,c,n=b;pc=rows[i-1][4] if i else o
        tr=max(h-l,abs(h-pc),abs(l-pc))
        atr=tr if not i else atr+(tr-atr)/14
        up=0 if not i else up+(max(0,c-pc)-up)/14
        dn=0 if not i else dn+(max(0,pc-c)-dn)/14
        fast=c if not i else fast+2/21*(c-fast)
        slow=c if not i else slow+2/81*(c-slow)
        travel=sum(abs(rows[j][4]-rows[j-1][4]) for j in range(i-19,i+1)) if i>=20 else 0
        er=abs(c-rows[i-20][4])/travel if travel else float('nan')
        result.append(dict(bar=b,atr=atr,e20=fast,e80=slow,rsi=100-100/(1+up/dn) if dn>0 else 100,er=er))
    return result


def score_packet(packet, now, family):
    """Validate independently of broker candles; never promote native order readiness."""
    through=int(now.timestamp())//3600*3600
    if (not isinstance(packet,dict) or packet.get('contract')!=CONTRACT or packet.get('source')!=SOURCE
            or packet.get('read_only') is not True or packet.get('execution_authority') is not False
            or packet.get('through')!=through or packet.get('seed_hash')!=SEED_HASH):
        raise ValueError('BTC_NATIVE_NOT_CURRENT')
    rows=packet.get('bars',[])
    seed=[r for r in rows if r[0]<SEED_END]
    validate_seed(dict(contract=CONTRACT,source=SOURCE,through=SEED_END,bars=seed))
    extension=rows[len(seed):]
    if [r[0] for r in extension] != list(range(SEED_END,through,3600)) or any(not valid_bar(r) or r[5]!=60 for r in extension):
        raise ValueError('BTC_EXTENSION_GAP')
    if not rows or rows[-1][0]+3600!=through:
        raise ValueError('BTC_NATIVE_COVERAGE')
    h=features(rows);qrows=[r for r in aggregate(rows,14400) if r[0]+14400<=through];q=features(qrows)
    f=h[-1];v=q[-1];b=f['bar'];qb=v['bar'];out={'BUY':[],'SELL':[]}
    trend=lambda x:1 if x['bar'][4]>x['e80'] and x['e20']>x['e80'] else -1 if x['bar'][4]<x['e80'] and x['e20']<x['e80'] else 0
    at=datetime.fromtimestamp(through,timezone.utc);qat=datetime.fromtimestamp(qb[0]+14400,timezone.utc)
    note='Bitstamp tertutup '+at.isoformat()+'; seed SHA256 cocok V1'
    out['BUY'].append(family('BTC incumbent BUY H4 (pola native)',[
        ('Trend H4 bullish',trend(v)==1,25,note),
        ('Body H4 > 1,4 ATR', (qb[4]-qb[1])/v['atr']>1.4 if v['atr']>0 else False,30,'ATR RMA diinisialisasi sejak seed 2019'),
        ('Close H4 > high H4 sebelumnya',qb[4]>q[-2]['bar'][2],25,'BtcCore.Signals'),
        ('Efficiency H4 >= 0,2; count >=192',v['er']>=.2 and qb[5]>=192,20,'BtcEntryGate; hanya pola, bukan sesi atau kesiapan order'),
    ]))
    lo=min(x['bar'][3] for x in h[-17:-1]);hi=max(x['bar'][2] for x in h[-17:-1]);range4=sum(x['bar'][2]-x['bar'][3] for x in h[-5:-1])/4
    ratio=f['atr']/max(h[-21]['atr'],1e-12)
    out['SELL'].append(family('BTC incumbent SELL H1 (pola native)',[
        ('Trend H4 bearish',trend(v)==-1,20,note),
        ('Kompresi 4 H1 < 0,7 ATR sebelumnya',range4<h[-2]['atr']*.7,25,'Rumus BtcCore.Signals'),
        ('Breakdown 16 H1 tanpa breakout atas',b[4]<lo-.1*f['atr'] and b[4]<=hi+.1*f['atr'],30,'Batas low/high 16 H1 + buffer 0,1 ATR'),
        ('Body, RSI dan rasio ATR lolos',abs(b[4]-b[1])<=2.5*f['atr'] and f['rsi']>=30 and .6<=ratio<=1.8 and b[5]>=48,25,'Termasuk BtcEntryGate SELL RSI >=30'),
    ]))
    consecutive=all(r[5]==240 and (i==0 or r[0]-qrows[-41:][i-1][0]==14400) for i,r in enumerate(qrows[-41:]))
    out['BUY'].append(family('BTC H4 Break40 (pola native)',[
        ('Trend H4 bullish',trend(v)==1,20,note),
        ('Efficiency >=0,2 dan RSI 50–75',v['er']>=.2 and 50<=v['rsi']<=75,20,'EntryFamilies.BtcEvaluate'),
        ('Body >=0,75 ATR dan close di 25% atas',v['atr']>0 and (qb[4]-qb[1])/v['atr']>=.75 and qb[2]>qb[3] and (qb[4]-qb[3])/(qb[2]-qb[3])>=.75,25,'Candle H4 tertutup'),
        ('Breakout high 40 H4 + 0,05 ATR',qb[4]>max(x['bar'][2] for x in q[-41:-1])+.05*v['atr'],25,'Break40 BUY saja'),
        ('41 H4 lengkap dan berurutan',consecutive,10,'240 M1 per H4'),
    ]))
    return out,dict(source=SOURCE,through=at.isoformat(),h4_close=qat.isoformat(),seed_verified=True,
                    hourly_count=len(rows),terminal_acceptance='UNKNOWN',weekend=at.weekday()>=5)
