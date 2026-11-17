"""Timestamped public market/calendar inputs for manual R3; no account access."""
from __future__ import annotations
from datetime import UTC,datetime,timedelta
import json,math,re
from urllib.request import Request,urlopen

CONTRACT='RIZAN_MANUAL_R3_MARKET_V1'
NEWS_CONTRACT='RIZAN_MANUAL_R3_CALENDAR_V1'
URL='https://rizan-bridge.duckdns.org:25345/bootstrap125/manual-r3.json'
NEWS_URL='https://rizan-bridge.duckdns.org:25345/bootstrap125/manual-r3-news.json'
PRE_NEWS_URL='https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/scanner-pre-news-snapshots/runtime/pre_news_snapshot.json'


def stamp(value):
    try:
        at=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return at.astimezone(UTC) if at.tzinfo else None
    except (TypeError,ValueError):return None


def read_public(url,*,timeout=6,limit=4*1024*1024,opener=urlopen):
    with opener(Request(url,headers={'Cache-Control':'no-cache','User-Agent':'RIZAN-Manual-R3/1'}),timeout=timeout) as r:
        raw=r.read(limit+1)
    if len(raw)>limit:raise ValueError('R3_PAYLOAD_TOO_LARGE')
    p=json.loads(raw)
    if not isinstance(p,dict):raise ValueError('R3_PAYLOAD_NOT_OBJECT')
    return p


def calendar_from_snapshot(snapshot,*,now):
    out={'contract':NEWS_CONTRACT,'observed_at':None,'events':None,'execution_authority':False}
    if (snapshot.get('contract')!='RIZAN_PRE_NEWS_SNAPSHOT_V1'
            or snapshot.get('execution_authority') is not False):return out
    candidates=[x for x in snapshot.get('heartbeats',[]) if x.get('worker_name')=='ctrader_demo_xau_event_risk_v192']
    candidates=[x for x in candidates if stamp(x.get('observed_at'))]
    if not candidates:return out
    hb=max(candidates,key=lambda x:stamp(x['observed_at']));at=stamp(hb['observed_at'])
    if hb.get('healthy') is not True or not -5<=(now-at).total_seconds()<=600:return out
    risk=hb.get('details',{}).get('risk',{});rows=list(risk.get('upcoming_events') or [])
    rows += [risk[k] for k in ['focal_event','latest_released_event'] if isinstance(risk.get(k),dict)]
    events=[];seen=set()
    for row in rows:
        when=stamp(row.get('scheduled_at'));category=str(row.get('category','')).upper();title=str(row.get('title','')).upper()
        if not when or row.get('currency','USD')!='USD':continue
        if category in ['CPI','PPI','FOMC']:kind=category
        elif category in ['NFP','EMPLOYMENT'] and re.search(r'NON.?FARM|PAYROLL|EMPLOYMENT CHANGE',title):kind='NFP'
        else:continue
        if not now-timedelta(days=1)<=when<=now+timedelta(days=8):continue
        key=(kind,when)
        if key not in seen:events.append({'event':kind,'at':when.isoformat()});seen.add(key)
    return {**out,'observed_at':at.isoformat(),'events':sorted(events,key=lambda x:x['at'])}


def validate_calendar(calendar,*,now):
    if (not isinstance(calendar,dict) or calendar.get('contract')!=NEWS_CONTRACT
            or calendar.get('execution_authority') is not False):return None
    at=stamp(calendar.get('observed_at'));rows=calendar.get('events')
    if not at or not -5<=(now-at).total_seconds()<=600 or not isinstance(rows,list):return None
    if any(not isinstance(x,dict) or x.get('event') not in ['CPI','PPI','NFP','FOMC'] or stamp(x.get('at')) is None for x in rows):return None
    return rows


def validate_market(payload,*,now):
    import pandas as pd
    if (payload.get('contract')!=CONTRACT or payload.get('symbol')!='XAUUSD'
            or payload.get('source')!='CTRADER_MARKET_DATA_READ_ONLY'
            or payload.get('execution_authority') is not False or payload.get('execution_influence') is not False):
        raise ValueError('R3_SOURCE_CONTRACT_INVALID')
    at=stamp(payload.get('as_of'))
    if not at or not -5<=(now-at).total_seconds()<=90:raise ValueError('R3_PUBLICATION_STALE')
    rows=payload.get('m1')
    if not isinstance(rows,list) or not 2000<=len(rows)<=12000:raise ValueError('R3_HISTORY_INCOMPLETE')
    previous=None
    for row in rows:
        t=stamp(row.get('timestamp'))
        values=[row.get(k) for k in ['open','high','low','close']]
        if (not t or t.second or t.microsecond or t+timedelta(minutes=1)>now
                or any(type(v) not in [int,float] or not math.isfinite(v) for v in values)
                or not 0<values[2]<=min(values[0],values[3])<=max(values[0],values[3])<=values[1]
                or previous is not None and t<=previous):raise ValueError('R3_CANDLE_INVALID')
        previous=t
    frame=pd.DataFrame(rows).set_index('timestamp');frame.index=pd.to_datetime(frame.index,utc=True)
    quote=payload.get('quote') or {};qt=stamp(quote.get('at'))
    bid,ask=quote.get('bid'),quote.get('ask')
    valid=(qt is not None and -5<=(now-qt).total_seconds()<=30
           and all(type(x) in [float,int] and math.isfinite(x) for x in [bid,ask]) and 0<bid<=ask)
    return {'frame':frame,'bid':bid if valid else None,'ask':ask if valid else None,
            'quote_as_of':qt if valid else None,'news_events':validate_calendar(payload.get('calendar'),now=now),
            'as_of':at,'calendar':payload.get('calendar') or {}}


def fetch_market(*,now=None,opener=urlopen):
    now=now or datetime.now(UTC)
    p=read_public(URL+'?slot='+str(int(now.timestamp()//5)),opener=opener)
    return validate_market(p,now=now)
