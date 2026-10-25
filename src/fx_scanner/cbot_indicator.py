"""Read-only manual trailing scenarios. No execution or account dependencies."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import math
from .cbot_manual import stamp

def number(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)

def seed(side,entry,stop,started_at,spread,activation_r=1.,distance_r=1.):
    at=stamp(started_at)
    if (side not in (-1,1) or not at or not all(number(x) for x in
        [entry,stop,spread,activation_r,distance_r]) or min(entry,stop)<=0 or
        side*(entry-stop)<=0 or spread<0 or activation_r<0 or distance_r<=0):
        raise ValueError('Geometri skenario trailing tidak valid')
    cursor=at.replace(second=0,microsecond=0)
    if cursor<at:cursor+=timedelta(minutes=1)
    return dict(side=side,entry=entry,initial_stop=stop,stop=stop,risk=abs(entry-stop),
        water=entry,cursor=cursor.isoformat(),started_at=at.isoformat(),spread=spread,
        activation_r=activation_r,distance_r=distance_r,active=False,stopped=False,
        coverage_gap=False,exit=None,execution_authority=False,execution_influence=False)

def advance(state,bars,*,as_of,now=None):
    s=deepcopy(state);now=now or datetime.now(UTC);cut=stamp(as_of)
    if not cut or not -5<=(now-cut).total_seconds()<=90:raise ValueError('Data trailing belum baru')
    if s.get('execution_authority') is not False or s.get('execution_influence') is not False:
        raise ValueError('Invalid display-only scenario')
    cursor=stamp(s.get('cursor'));started=stamp(s.get('started_at'))
    if not cursor or not started or started>now or cursor<started.replace(second=0,microsecond=0):
        raise ValueError('Invalid scenario chronology')
    side=s.get('side');risk=s.get('risk')
    if side not in (-1,1) or not all(number(s.get(k)) for k in
        ['entry','initial_stop','stop','risk','water','spread','activation_r','distance_r']):
        raise ValueError('Invalid scenario values')
    if (risk<=0 or abs(risk-side*(s['entry']-s['initial_stop']))>1e-7 or s['spread']<0 or
        s['activation_r']<0 or s['distance_r']<=0 or side*(s['stop']-s['initial_stop'])<0):
        raise ValueError('Invalid trailing geometry')
    rows=[];seen=set()
    for b in bars:
        at=stamp(b.get('timestamp'))
        if not at or at in seen:raise ValueError('Invalid candle chronology')
        seen.add(at)
        if not all(number(b.get(k)) and b[k]>0 for k in ['open','high','low','close']):
            raise ValueError('Invalid candle prices')
        if b['low']>min(b['open'],b['close']) or b['high']<max(b['open'],b['close']):
            raise ValueError('Invalid OHLC')
        if at+timedelta(minutes=1)<=cut and at+timedelta(minutes=1)<=now:rows.append((at,b))
    for at,b in sorted(rows):
        if s['stopped'] or s['coverage_gap']:break
        if at<cursor:continue
        if at!=cursor:s['coverage_gap']=True;break
        offset=s['spread'] if side==-1 else 0
        adverse=(b['low'] if side==1 else b['high'])+offset
        if side*(adverse-s['stop'])<=0:
            op=b['open']+offset
            s['exit']=min(s['stop'],op) if side==1 else max(s['stop'],op)
            s['stopped']=True;cursor=at+timedelta(minutes=1);break
        favorable=(b['high'] if side==1 else b['low'])+offset
        s['water']=max(s['water'],favorable) if side==1 else min(s['water'],favorable)
        s['active']=s['active'] or side*(s['water']-s['entry'])>=s['activation_r']*risk
        if s['active']:
            quote=b['close']+offset;candidate=s['water']-side*s['distance_r']*risk
            candidate=min(candidate,quote-.01) if side==1 else max(candidate,quote+.01)
            s['stop']=max(s['stop'],candidate) if side==1 else min(s['stop'],candidate)
        cursor=at+timedelta(minutes=1)
    if not s['stopped'] and not s['coverage_gap'] and cursor+timedelta(minutes=1)<cut.replace(second=0,microsecond=0):
        s['coverage_gap']=True
    s['cursor']=cursor.isoformat();return s

def attach_market(c,market):
    """Only attach public display candles from the reader's existing response."""
    if c.get('symbol')!='XAUUSD' or not isinstance(c.get('indicator'),dict):return
    c['indicator_m1']=[{k:b.get(k) for k in ['timestamp','open','high','low','close']}
        for b in (market.get('bars',{}).get('XAUUSD') or [])[-720:]]
    quotes=market.get('quotes',{}).get('XAUUSD') or {}
    c['indicator_quote']={k:{f:(quotes.get(k) or {}).get(f) for f in ['price','at']} for k in ['BID','ASK']}
