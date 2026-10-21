"""Closed-candle V05 dashboard research engine. No broker/order authority.

Native rolling feed is an operational adaptation, not replay/native parity.
ENTRY is a fresh research reference, never an instruction sent to a cBot.
"""
from datetime import UTC, datetime
import hashlib
import math
import numpy as np
import pandas as pd
from .manual_reversal_map import frame, timestamp
from .zone_v05_nodes import nodes

CONTRACT='RIZAN_ZONE_V05_DASHBOARD_1'
MIN=60_000_000_000
HOUR=60*MIN
INF=np.iinfo(np.int64).max


def blank(now, reason='DATA_UNAVAILABLE'):
    return dict(contract=CONTRACT,symbol='XAUUSD',as_of=timestamp(now).isoformat(),
                execution_authority=False,execution_influence=False,probability=None,
                state='WAIT',reason=reason,plans=[],decisions=[],refresh_seconds=300,
                validation_status='DEVELOPMENT_CANDIDATE_NOT_INDEPENDENTLY_VALIDATED',
                route_status='CONDITIONAL_NEXT_LEG_NOT_VALIDATED')


def prepared(rows,tf,now):
    q=frame(rows,tf,now)
    tr=pd.concat([q.high-q.low,(q.high-q.close.shift()).abs(),(q.low-q.close.shift()).abs()],axis=1).max(axis=1)
    q['atr']=tr.rolling(14).mean().shift(1)
    for n in (20,50,200):q[f'ema{n}']=q.close.ewm(span=n,adjust=False).mean()
    q['time']=q.timestamp+pd.Timedelta(minutes={'H1':60,'H4':240}[tf])
    return q


def preserve_registry(z,previous,cutoff):
    """Keep published geometry stable while native rolling windows advance."""
    cols=['formed_ns','low','high','direction','tf','atr','strength','family','style','lookback','base_ns','origin_eligible']
    keys=['formed_ns','direction','tf','family','style','lookback']
    records=(previous or {}).get('node_registry',[]) if (previous or {}).get('contract')==CONTRACT else []
    if records:
        prior=pd.DataFrame(records)[cols]
        z=pd.concat([prior,z[cols]],ignore_index=True).drop_duplicates(keys,keep='first')
    z=z[z.formed_ns>=cutoff].sort_values('formed_ns',kind='stable').reset_index(drop=True)
    return z


def lifecycle(z,qs,m):
    mt=m.timestamp.astype('int64').to_numpy();hi=m.high.to_numpy();lo=m.low.to_numpy()
    dead=[];touch=[]
    for a in z.itertuples():
        q=qs[a.tf];t=q.time.astype('int64').to_numpy();c=q.close.to_numpy()
        bad=(t>a.formed_ns)&(t<=a.formed_ns+120*HOUR)&(a.direction*(c-(a.low if a.direction==1 else a.high))<0)
        end=int(t[bad][0]) if bad.any() else INF;dead.append(end)
        mask=(mt>=a.formed_ns)&(mt<min(end,a.formed_ns+120*HOUR))
        hit=np.flatnonzero(mask&((lo<=a.high) if a.direction==1 else (hi>=a.low)))
        touch.append(int(hit[0]) if len(hit) else -1)
    z=z.copy();z['dead']=dead;z['touch_i']=touch
    return z


def zone(a):
    key=f'{a.family}:{a.tf}:{a.formed_ns}:{a.low:.8f}:{a.high:.8f}:{a.direction}'
    return dict(id=hashlib.sha256(key.encode()).hexdigest()[:20],low=float(a.low),high=float(a.high),
                side='BUY' if a.direction==1 else 'SELL',timeframe='H'+str(int(a.tf)//60),
                formed_at=pd.Timestamp(a.formed_ns,tz='UTC').isoformat(),family=int(a.family))


def confirmation(m5,m15,touch,end,d,prox):
    fifteen=m15[(m15.closed_ns>touch)&(m15.closed_ns<=end)]
    fifteen=fifteen[(d*(fifteen.close-prox)>0)&(d*(fifteen.close-fifteen.open)>0)]
    reclaim=int(fifteen.closed_ns.iloc[0]) if len(fifteen) else None
    if reclaim is None:return None,None
    for k in range(3,len(m5)):
        b=m5.iloc[k];t=int(b.closed_ns)
        if t<=reclaim or t>end:continue
        prev=m5.iloc[k-3:k]
        if t-int(prev.closed_ns.iloc[0])!=15*MIN:continue
        bos=b.close>prev.high.max() if d==1 else b.close<prev.low.min()
        if bos and d*(b.close-prox)>0 and d*(b.close-b.open)>0:return reclaim,t
    return reclaim,None


def target(z,a,at):
    d=int(a.direction);prox=a.high if d==1 else a.low
    q=z[(z.direction!=d)&(z.formed_ns<=at)&(z.formed_ns>=at-120*HOUR)&(z.dead>at)]
    gap=d*((q.low if d==1 else q.high)-prox)
    q=q[(gap>=.25*a.atr)&(gap<=20*a.atr)].copy()
    if q.empty:return None
    q['distance']=d*((q.low if d==1 else q.high)-prox)
    return q.sort_values(['distance','formed_ns'],kind='stable').iloc[0]


def completed(rows,tf,now):
    q=frame(rows,tf,now);q['closed_ns']=(q.timestamp+pd.Timedelta(minutes={'M5':5,'M15':15}[tf])).astype('int64')
    return q


def build_plan(a,z,m,m5,m15,now_ns,costs):
    d=int(a.direction);prox=a.high if d==1 else a.low
    p=dict(source=zone(a),state='WATCH',reason='MENUNGGU_SENTUHAN',
           first_touch_at=None,reclaim_m15_at=None,confirmation_m5_at=None,
           entry=None,sl=float((a.low if d==1 else a.high)-d*.2*a.atr),tp=None,
           target=None,planned_net_rr=None,entry_at=None)
    mt=m.timestamp.astype('int64').to_numpy();i=int(a.touch_i)
    if i<0:
        if now_ns>=min(int(a.dead),a.formed_ns+24*HOUR):p.update(state='BATAL',reason='ZONA_BATAL_ATAU_KEDALUWARSA')
        return p
    at=int(mt[i]);p['first_touch_at']=pd.Timestamp(at,tz='UTC').isoformat()
    if at-a.formed_ns>24*HOUR:
        p.update(state='BATAL',reason='FIRST_TOUCH_LEBIH_24_JAM');return p
    b=target(z,a,at)
    if b is None:p.update(state='BATAL',reason='TARGET_BELUM_TERSEDIA_SAAT_TOUCH');return p
    tp=float((b.low if d==1 else b.high)-d*.025*a.atr);p.update(target=zone(b),tp=tp)
    end=min(at+120*MIN,int(a.dead),a.formed_ns+120*HOUR,now_ns)
    reclaim,conf=confirmation(m5,m15,at,end,d,prox)
    if reclaim:p['reclaim_m15_at']=pd.Timestamp(reclaim,tz='UTC').isoformat()
    p['reason']='MENUNGGU_BOS_M5' if reclaim else 'MENUNGGU_RECLAIM_M15'
    if conf is None:
        future=m.iloc[i:]
        if int(b.dead)<=now_ns or now_ns-b.formed_ns>120*HOUR or (future.high.max()>=tp if d==1 else future.low.min()<=tp):
            p.update(state='BATAL',reason='TARGET_SUDAH_TERCAPAI_ATAU_BATAL');return p
        if now_ns>=min(at+120*MIN,int(a.dead)):
            p.update(state='BATAL',reason='ZONA_BATAL_ATAU_KONFIRMASI_KEDALUWARSA')
        return p
    p['confirmation_m5_at']=pd.Timestamp(conf,tz='UTC').isoformat()
    j=int(np.searchsorted(mt,conf))
    if j>=len(m) or mt[j]-conf>MIN:
        p.update(reason='MENUNGGU_OPEN_M1_SETELAH_KONFIRMASI');return p
    entry=float(m.open.iloc[j]);risk=d*(entry-p['sl'])
    p.update(entry=entry,entry_at=pd.Timestamp(mt[j],tz='UTC').isoformat())
    spent=m.iloc[i:j]
    checks=[(mt[j]>=a.dead,'ZONA_SUDAH_BATAL'),(mt[j]>=b.dead or mt[j]-b.formed_ns>120*HOUR,'TARGET_SUDAH_BATAL'),
            (j<1 or mt[j]-mt[j-1]!=MIN,'DATA_M1_TIDAK_BERURUTAN'),
            (d*(entry-prox)>.75*a.atr,'HARGA_SUDAH_TERLALU_JAUH'),
            ((len(spent)>0 and (spent.high.max()>=tp if d==1 else spent.low.min()<=tp)),'TARGET_SUDAH_TERCAPAI'),
            (not 7<=pd.Timestamp(mt[j],tz='UTC').hour<17,'DI_LUAR_SESI_14_00_23_59_WIB'),
            (risk<=0,'RISIKO_TIDAK_VALID')]
    for fail,reason in checks:
        if fail:p.update(state='BATAL',reason=reason);return p
    if now_ns-mt[j]>=24*HOUR:
        p.update(state='BATAL',reason='KONFIRMASI_LAMA_LEBIH_24_JAM');return p
    spread=costs.get(pd.Timestamp(mt[j],tz='UTC').isoformat())
    cost=float(spread)+.17 if spread is not None and math.isfinite(float(spread)) and 0<=float(spread)<=50 else None
    if cost is None:
        p.update(state='BLOCK',reason='SPREAD_BROKER_BELUM_TERSEDIA');return p
    rr=(d*(tp-entry)-cost)/(risk+cost);p['planned_net_rr']=float(rr)
    if risk<3*cost or rr<1.5:
        p.update(state='BATAL',reason='RR_ATAU_BIAYA_TIDAK_MEMENUHI');return p
    p.update(state='ENTRY' if now_ns-conf<=5*MIN else 'AKTIF_REFERENSI',reason='SYARAT_M15_M5_TERPENUHI')
    for k in range(j,len(m)):
        row=m.iloc[k];stop=row.low<=p['sl'] if d==1 else row.high>=p['sl'];hit=row.high>=tp if d==1 else row.low<=tp
        if stop or hit or mt[k]>=mt[j]+24*HOUR:
            p.update(state='SELESAI',reason='SL_TERSENTUH' if stop else 'TP_TERSENTUH' if hit else 'BATAS_24_JAM',
                     ended_at=pd.Timestamp(mt[k],tz='UTC').isoformat());break
    return p


def validate(p,*,now=None):
    if p.get('contract')!=CONTRACT or p.get('symbol')!='XAUUSD' or p.get('execution_authority') is not False or p.get('execution_influence') is not False:
        raise ValueError('V05 read-only contract')
    p=dict(p);now=timestamp(now or datetime.now(UTC));p['fresh']=False
    if p.get('evaluated_close_at'):
        age=(now-timestamp(p['evaluated_close_at'])).total_seconds()
        produced=(now-timestamp(p['as_of'])).total_seconds()
        p['fresh']=0<=age<=420 and 0<=produced<=420
    if not p['fresh']:
        p.update(state='WAIT',reason='DATA_BELUM_LENGKAP_ATAU_TERLAMBAT',plans=[],decisions=[])
    else:
        plans=[]
        for plan in p.get('plans',[]):
            plan=dict(plan);confirmed=plan.get('confirmation_m5_at')
            age=(now-timestamp(confirmed)).total_seconds() if confirmed else 0
            if confirmed and age>=86400:continue
            if plan.get('state')=='ENTRY' and age>300:
                plan.update(state='AKTIF_REFERENSI',reason='ENTRY_BARU_SUDAH_LEWAT')
            plans.append(plan)
        p['plans']=plans
        p['decisions']=[dict(side=x['side'],result='ENTRY' if any(q.get('state')=='ENTRY' and q['source']['side']==x['side'] for q in plans) else 'TIDAK_ENTRY',
            reason=next((q['reason'] for q in plans if q['source']['side']==x['side']),'TIDAK_ADA_SETUP_YANG_LOLOS')) for x in p.get('decisions',[])]
        if p.get('state')=='ENTRY' and not any(q.get('state')=='ENTRY' for q in plans):p['state']='WATCH'
    return p


def evaluate(native,*,now=None,spreads=None,previous=None):
    now=timestamp(now or datetime.now(UTC));out=blank(now)
    try:
        m=frame(native.get('M1',[]),'M1',now);m5=completed(native.get('M5',[]),'M5',now);m15=completed(native.get('M15',[]),'M15',now)
        qs={60:prepared(native.get('H1',[]),'H1',now),240:prepared(native.get('H4',[]),'H4',now)}
        if len(m)<1000 or len(m5)<10 or len(m15)<10 or len(qs[60])<300 or len(qs[240])<210:return out
        close=int(m5.closed_ns.iloc[-1]);expected=now.floor('5min').value
        out.update(evaluated_close_at=pd.Timestamp(close,tz='UTC').isoformat(),next_evaluation_at=pd.Timestamp(close+5*MIN,tz='UTC').isoformat(),
                   timeframe_closed_at={k:(q.timestamp.iloc[-1]+pd.Timedelta(minutes=n)).isoformat() for k,q,n in [('M1',m,1),('M5',m5,5),('M15',m15,15),('H1',qs[60],60),('H4',qs[240],240)]})
        # Exact latest expected close required: never reuse yesterday's signal as today's entry.
        if close!=expected or m.timestamp.iloc[-1].value+MIN<close or int(m15.closed_ns.iloc[-1])!=now.floor('15min').value:
            out['evaluated_close_at']=None
            return validate(out,now=now)
        out['cost_basis']='BROKER_ASOF_ENTRY_SPREAD_PLUS_0_17_PROXY'
        costs=spreads or {}
        registered=preserve_registry(nodes(qs,m.set_index('timestamp')),previous,close-168*HOUR)
        out['node_registry']=registered.to_dict('records')
        z=lifecycle(registered,qs,m)
        latest_m1=m.timestamp.iloc[-1].value+MIN
        sources=z[(z.family==5)&(z.lookback==20)&(z.strength>=.6)&(z.formed_ns>=close-144*HOUR)]
        allplans=[build_plan(a,z,m,m5,m15,latest_m1,costs) for a in sources.itertuples()]
        # One research position at a time, same deterministic entry/origin ordering as FIFO.
        busy=0
        for p in sorted((p for p in allplans if p.get('entry_at') and p['state'] in ('ENTRY','AKTIF_REFERENSI','SELESAI')),key=lambda x:(x['entry_at'],x['source']['formed_at'],x['source']['low'])):
            en=timestamp(p['entry_at']).value
            if en<=busy:p.update(state='BATAL',reason='SATU_POSISI_REFERENSI_MASIH_AKTIF');continue
            busy=timestamp(p['ended_at']).value if p.get('ended_at') else latest_m1
        active=[p for p in allplans if p['state'] in ('ENTRY','AKTIF_REFERENSI')]
        selected=active[:1]
        price=float(m.close.iloc[-1]);out['price_reference']=price
        for side in ('BUY','SELL'):
            if any(p['source']['side']==side for p in selected):continue
            q=[p for p in allplans if p['source']['side']==side and p['state'] in ('WATCH','BLOCK')]
            if q:
                p=min(q,key=lambda x:min(abs(price-x['source']['low']),abs(price-x['source']['high'])))
                if active:p=dict(p,state='WATCH',reason='MENUNGGU_POSISI_REFERENSI_SELESAI')
                selected.append(p)
        out['plans']=selected
        out['decisions']=[dict(side=s,result='ENTRY' if any(p['source']['side']==s and p['state']=='ENTRY' for p in selected) else 'TIDAK_ENTRY',
            reason=next((p['reason'] for p in selected if p['source']['side']==s),'TIDAK_ADA_SETUP_YANG_LOLOS')) for s in ('BUY','SELL')]
        out['quote_anchors']=sorted({p['entry_at'] for p in allplans if p['state']=='BLOCK' and p.get('entry_at')},reverse=True)[:8]
        out['recent_events']=sorted([p for p in allplans if p.get('confirmation_m5_at')],key=lambda x:x['confirmation_m5_at'],reverse=True)[:8]
        out.update(state='ENTRY' if any(p['state']=='ENTRY' for p in selected) else 'WATCH',reason='EVALUASI_CLOSE_M5_SELESAI')
        for p in selected:
            p['next_leg']=dict(state='WATCH_BERSYARAT',zone=p.get('target'),
                reason='TUJUAN_BUKAN_ENTRY_OTOMATIS; zona tujuan perlu setup baru. B/C/D belum ditentukan sebelum terbentuk.',
                validated=False)
        return validate(out,now=now)
    except (ValueError,KeyError,TypeError,IndexError,OverflowError):
        return blank(now,'DATA_TIDAK_VALID')
