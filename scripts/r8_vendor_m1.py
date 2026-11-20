"""R8 research-only Dukascopy DOLLARIDXUSD M1 source-byte acquisition.

Records original SHA256 and UTC day offsets. The inferred lag is an ASSUMPTION,
not a reconstruction of historical first_seen_at. No trading access.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import lzma
import math
import pathlib
import struct
import time
import urllib.error
import urllib.request

import pandas as pd

UTC=dt.timezone.utc
RECORD=struct.Struct('>IIIIIf')  # secs, O, C, L, H, volume
HOSTS=('https://datafeed.dukascopy.com/datafeed', 'https://www.dukascopy.com/datafeed')


def decode_day(raw:bytes,day:dt.date)->list[tuple]:
    payload=lzma.decompress(raw,format=lzma.FORMAT_AUTO)
    if len(payload)%RECORD.size:raise ValueError('BI5_INVALID_RECORD_LENGTH')
    rows=[];seen=set()
    for sec,op,cl,lo,hi,volume in RECORD.iter_unpack(payload):
        if sec>=86400 or sec%60 or sec in seen:raise ValueError('BI5_INVALID_UTC_OFFSET_OR_DUPLICATE')
        if lo<=0 or lo>min(op,cl) or hi<max(op,cl) or not math.isfinite(volume) or volume<0:
            raise ValueError('BI5_INVALID_OHLC_VOLUME')
        seen.add(sec)
        stamp=dt.datetime.combine(day,dt.time(),UTC)+dt.timedelta(seconds=sec)
        rows.append((stamp,op,hi,lo,cl))
    rows.sort(key=lambda x:x[0])
    return rows


def fetch_day(day:dt.date,retries:int=2):
    suffix=f'DOLLARIDXUSD/{day.year}/{day.month-1:02d}/{day.day:02d}/BID_candles_min_1.bi5'
    errors=[]
    for host in HOSTS:
        url=f'{host}/{suffix}'
        for attempt in range(retries):
            try:
                req=urllib.request.Request(url,headers={'User-Agent':'RIZAN-R8-Research/1.0'})
                with urllib.request.urlopen(req,timeout=18) as r:
                    status=r.status;raw=r.read()
                if status!=200 or not raw:raise ValueError('HTTP_NON200_OR_EMPTY')
                rows=decode_day(raw,day)
                if not rows:raise ValueError('DECODED_EMPTY')
                return {'day':day.isoformat(),'status':'OK','url':url,'sha256':hashlib.sha256(raw).hexdigest(),
                        'bytes':len(raw),'rows':len(rows),'acquired_at_utc':dt.datetime.now(UTC).isoformat()},rows
            except urllib.error.HTTPError as e:
                errors.append(f'{url}:HTTP_{e.code}')
                if e.code in (403,404):break
            except Exception as e:
                errors.append(f'{url}:{type(e).__name__}:{str(e)[:80]}')
            if attempt+1<retries:time.sleep(.7*(attempt+1))
    return {'day':day.isoformat(),'status':'MISSING_OR_FAILED','errors':errors},[]


def acquire(year:int,out:pathlib.Path,workers:int=4,strict:bool=True):
    today=dt.datetime.now(UTC).date()
    end=min(dt.date(year,12,31),today) if year==today.year else dt.date(year,12,31)
    if year<2019 or year>today.year:raise ValueError('YEAR_OUT_OF_RANGE')
    dates=[dt.date(year,1,1)+dt.timedelta(days=i) for i in range((end-dt.date(year,1,1)).days+1)]
    records=[];rows=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for rec,dayrows in pool.map(fetch_day,dates):
            records.append(rec);rows.extend(dayrows)
    accepted=[r for r in records if r['status']=='OK']
    missing_weekdays=[r for r in records if r['status']!='OK' and dt.date.fromisoformat(r['day']).weekday()<5]
    if len(accepted)<20 or (strict and len(missing_weekdays)>25):
        raise RuntimeError(f'DUKASCOPY_INSUFFICIENT_DAY_COVERAGE:accepted={len(accepted)},missing_weekdays={len(missing_weekdays)}')
    df=pd.DataFrame(rows,columns=['timestamp','open','high','low','close']).sort_values('timestamp')
    if df.timestamp.duplicated().any():raise ValueError('DUPLICATE_SOURCE_MINUTE')
    out.mkdir(parents=True,exist_ok=True)
    csv=out/f'dollaridxusd_m1_{year}.csv'
    df['timestamp']=df.timestamp.dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    df.to_csv(csv,index=False)
    digest=hashlib.sha256(csv.read_bytes()).hexdigest()
    manifest={'contract':'R8_USD_ORIGINAL_BI5_M1_V1','year':year,'instrument':'DOLLARIDXUSD',
              'instrument_type':'DUKASCOPY_USD_INDEX_CFD_PROXY_NOT_ICE_DXY',
              'source_timestamp_semantics':'UTC_DAY_SECONDS_OFFSET_M1_OPEN',
              'bytes_sha256_each_day':records,'csv_sha256':digest,'rows':len(df),
              'days_ok':len(accepted),'missing_weekdays':len(missing_weekdays),
              'source_sha256_catalog':hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest(),
              'availability_model':'SCENARIO_ONLY_BAR_CLOSE_PLUS_EXPLICIT_DELAY; HISTORICAL_FIRST_SEEN_UNKNOWN',
              'execution_authority':False,'execution_influence':False}
    (out/f'dollaridxusd_m1_{year}_provenance.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return csv,manifest


def main():
    a=argparse.ArgumentParser();a.add_argument('--year',type=int,required=True)
    a.add_argument('--out',type=pathlib.Path,default=pathlib.Path('artifacts/r8-usd'))
    a.add_argument('--workers',type=int,default=4)
    x=a.parse_args();csv,prov=acquire(x.year,x.out,x.workers)
    print(json.dumps({'file':str(csv),'rows':prov['rows'],'days_ok':prov['days_ok'],
                      'missing_weekdays':prov['missing_weekdays'],'sha256':prov['csv_sha256']}))
if __name__=='__main__':main()
