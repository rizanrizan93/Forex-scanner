"""Independent causal supply/demand geometry for the manual dashboard only."""
from datetime import UTC, datetime, timedelta
import hashlib
import math
import pandas as pd

CONTRACT = 'RIZAN_XAU_MANUAL_REVERSAL_MAP_V2'
MINUTES = {'H4':240, 'H1':60, 'M15':15, 'M5':5, 'M1':1}
MAX_AGE_HOURS = {'H4':1440, 'H1':504, 'M15':72, 'M5':24}

def timestamp(value):
    p=pd.Timestamp(value)
    if p.tzinfo is None:raise ValueError('Timezone candle wajib tersedia')
    return p.tz_convert('UTC')

def frame(rows, tf, now):
    f=pd.DataFrame(rows)
    if f.empty:return pd.DataFrame(columns=['timestamp','open','high','low','close'])
    cols=['timestamp','open','high','low','close']
    if not set(cols).issubset(f):raise ValueError('Candle OHLC tidak lengkap')
    f=f[cols].copy();f['timestamp']=[timestamp(x) for x in f.timestamp]
    if f.timestamp.duplicated().any():raise ValueError('Timestamp candle duplikat')
    for c in cols[1:]:f[c]=pd.to_numeric(f[c],errors='raise')
    if not all(math.isfinite(x) for x in f[cols[1:]].to_numpy().ravel()):raise ValueError('Harga candle tidak finite')
    if ((f.low<=0)|(f.high<f[['open','close','low']].max(axis=1))|(f.low>f[['open','close','high']].min(axis=1))).any():raise ValueError('Geometri OHLC tidak valid')
    return f.loc[f.timestamp+pd.Timedelta(minutes=MINUTES[tf])<=timestamp(now)].sort_values('timestamp').reset_index(drop=True)

def detect(rows, tf, now):
    f=frame(rows,tf,now)
    if len(f)<24:return []
    tr=pd.concat([f.high-f.low,(f.high-f.close.shift()).abs(),(f.low-f.close.shift()).abs()],axis=1).max(axis=1)
    atr=tr.rolling(14).mean();zones=[]
    for i in range(18,len(f)):
        a=float(atr.iloc[i]);bar=f.iloc[i];span=float(bar.high-bar.low)
        if a<=0 or span<.9*a or abs(bar.close-bar.open)<.5*span:continue
        side='BUY' if bar.close>bar.open else 'SELL'
        best=None
        for count in (1,2,3):
            base=f.iloc[i-count:i];low=float(base.low.min());high=float(base.high.max());width=high-low
            if width<=0 or width>1.3*a:continue
            if (side=='BUY' and bar.close<=high) or (side=='SELL' and bar.close>=low):continue
            if best is None or width<best[0]:best=(width,count,low,high)
        if best is None:continue
        width,count,low,high=best;available=bar.timestamp+pd.Timedelta(minutes=MINUTES[tf])
        if (timestamp(now)-available).total_seconds()>MAX_AGE_HOURS[tf]*3600:continue
        invalidation=low-.05*a if side=='BUY' else high+.05*a
        future=f.iloc[i+1:]
        broken=((future.close<invalidation) if side=='BUY' else (future.close>invalidation)).any()
        if broken:continue
        inside=(future.high>=low)&(future.low<=high);touches=int((inside&~inside.shift(fill_value=False)).sum())
        before=f.iloc[max(0,i-count-8):i-count]
        bos=bool(bar.close>before.high.max()) if side=='BUY' else bool(bar.close<before.low.min())
        zones.append({'zone_id':hashlib.sha256(f'{tf}:{side}:{available.isoformat()}:{low}:{high}'.encode()).hexdigest()[:16],
            'timeframe':tf,'direction':side,'low':low,'high':high,'invalidation':invalidation,
            'available_at':available.isoformat(),'origin_at':f.iloc[i-count].timestamp.isoformat(),
            'touch_count':touches,'lifecycle':'FRESH' if touches==0 else 'RETESTED',
            'structural_bos':bos,'base_bars':count,'atr':a,'source_type':'BASE_DISPLACEMENT',
            'role':'UTAMA' if tf in {'H4','H1'} else 'REAKSI / REFINEMENT','probability':None})
    return zones

def project(zones, price):
    """Project the price map; TF roles and priority are not probabilities."""
    unique={}
    for item in sorted(zones,key=lambda x:x['available_at'],reverse=True):
        unique.setdefault((item['direction'],item['timeframe'],round(item['low'],4),round(item['high'],4)),dict(item))
    rows=list(unique.values())
    for z in rows:
        low,high=z['low'],z['high'];buy=z['direction']=='BUY'
        z['distance']=max(low-price,price-high,0.)
        z['eligible']=bool(low<=price if buy else high>=price)
        z['position']='DI ZONA' if low<=price<=high else 'DI BAWAH HARGA' if high<price else 'DI ATAS HARGA'
        z['overlap']=any(x['direction']!=z['direction'] and max(low,x['low'])<min(high,x['high']) for x in rows)
        z['major_conflict']=any(x['direction']!=z['direction'] and x['timeframe'] in {'H4','H1'} and max(low,x['low'])<min(high,x['high']) for x in rows)
        # A target behind the actual snapshot price has already been passed.
        opposing=[x for x in rows if x['direction']!=z['direction'] and x['timeframe'] in {'H4','H1'} and (x['low']>max(high,price) if buy else x['high']<min(low,price))]
        opposing.sort(key=lambda x:x['low'] if buy else -x['high'])
        target=(opposing[0]['low'] if buy else opposing[0]['high']) if opposing else None
        z.update(tp1_reference=target,target_structural=target,confirmation_required='Reclaim M15 selesai, lalu break tiga candle lokal M5 setelahnya.',probability=None)
    rows.sort(key=lambda z:(z['distance'],['H4','H1','M15','M5'].index(z['timeframe']),z['available_at']))
    selected=[]
    for tf in ['H4','H1','M15','M5']:
        for side in ['BUY','SELL']:
            group=[x for x in rows if x['timeframe']==tf and x['direction']==side]
            # Eligibility precedes the cap: two above-price BUY zones cannot hide demand below price.
            selected.extend(([x for x in group if x['eligible']]+[x for x in group if not x['eligible']])[:2])
    return selected


def _fresh_frame(f, tf, now):
    if f.empty:return False
    closed=f.iloc[-1].timestamp+pd.Timedelta(minutes=MINUTES[tf])
    return 0<=(timestamp(now)-closed).total_seconds()<=(MINUTES[tf]+10)*60


def reversal_phase(zone, frames, price, now):
    """Observable closed-candle stages, never an instruction to place an order."""
    side=1 if zone['direction']=='BUY' else -1
    out={'phase':'MENUNGGU_HARGA','rejection_m15_at':None,'confirmation_m5_at':None,
         'confirmation_reference':None,'probability':None}
    if zone.get('major_conflict'):return {**out,'phase':'KONFLIK_H1_H4'}
    if side*(price-zone['invalidation'])<=0:return {**out,'phase':'LEWATI_BATAS_SKENARIO'}
    if not all(_fresh_frame(frames.get(tf,pd.DataFrame()),tf,now) for tf in ['M15','M5']):
        return {**out,'phase':'DATA_KONFIRMASI_BELUM_LENGKAP'}
    m15=frames['M15'];m5=frames['M5'];available=timestamp(zone['available_at'])
    contact=m15.loc[(m15.timestamp>=available)&(m15.timestamp>=timestamp(now)-pd.Timedelta(hours=8))&
        (m15.high>=zone['low'])&(m15.low<=zone['high'])]
    if contact.empty:
        return {**out,'phase':'MENUNGGU_RECLAIM_M15' if zone['low']<=price<=zone['high'] else 'MENUNGGU_HARGA'}
    # Always use the most recent contact; an old confirmation cannot survive a new retest.
    touch=contact.iloc[-1];reclaim=touch.close>zone['high'] if side==1 else touch.close<zone['low']
    if not reclaim or side*(touch.close-touch.open)<=0:return {**out,'phase':'MENUNGGU_RECLAIM_M15'}
    closed=touch.timestamp+pd.Timedelta(minutes=15);out['rejection_m15_at']=closed.isoformat()
    for i in range(3,len(m5)):
        bar=m5.iloc[i];at=bar.timestamp+pd.Timedelta(minutes=5)
        if bar.timestamp<closed or at>closed+pd.Timedelta(minutes=60):continue
        prev=m5.iloc[i-3:i]
        times=list(prev.timestamp)+[bar.timestamp]
        if any((b-a).total_seconds()!=5*60 for a,b in zip(times,times[1:])):continue
        if side==1:
            broken=bar.close>prev.high.max() and bar.close>zone['high']
        else:broken=bar.close<prev.low.min() and bar.close<zone['low']
        if not broken or side*(bar.close-bar.open)<=0:continue
        out.update(confirmation_m5_at=at.isoformat(),confirmation_reference=float(bar.close))
        if (timestamp(now)-at).total_seconds()>30*60:return {**out,'phase':'KONFIRMASI_LAMA'}
        # A closed M5 crossing the distal after confirmation cancels this event.
        later=m5.iloc[i+1:]
        if ((later.close-zone['invalidation'])*side<=0).any():return {**out,'phase':'KONFIRMASI_BATAL'}
        span=max(float(bar.high-bar.low),.01)
        if side*(price-float(bar.close))>span:return {**out,'phase':'GERAK_SUDAH_BERJALAN'}
        return {**out,'phase':'KONFIRMASI_STRUKTUR'}
    return {**out,'phase':'MENUNGGU_BREAK_M5' if timestamp(now)<=closed+pd.Timedelta(minutes=60) else 'RECLAIM_LAMA_TUNGGU_ULANG'}


def build_plans(zones,frames,price,now):
    plans=[]
    for side in ['BUY','SELL']:
        eligible=[z for z in zones if z['direction']==side and z['eligible'] and z['timeframe'] in {'H4','H1'} and _fresh_frame(frames.get(z['timeframe'],pd.DataFrame()),z['timeframe'],now)]
        # H1 is the actionable anchor; H4 supplies larger context, not a fake confidence boost.
        eligible.sort(key=lambda z:(z['timeframe']!='H1',z['distance']))
        if not eligible:continue
        anchor=eligible[0];same=[z for z in eligible if z['timeframe']=='H4']
        context=min(same,key=lambda z:z['distance']) if same else None
        refinements=[z for z in zones if z['direction']==side and z['timeframe'] in {'M15','M5'} and _fresh_frame(frames.get(z['timeframe'],pd.DataFrame()),z['timeframe'],now) and max(z['low'],anchor['low'])<min(z['high'],anchor['high'])]
        phase=reversal_phase(anchor,frames,price,now)
        plans.append({'direction':side,'anchor':anchor,'context_h4':context,
            'refinements':refinements,'target_reference':anchor['target_structural'],
            'target_distance_usd':abs(anchor['target_structural']-price) if anchor['target_structural'] is not None else None,
            'invalidation_rule':'Close '+anchor['timeframe']+' melewati batas skenario.',
            'execution_authority':False,'execution_influence':False,**phase})
    return plans


def evaluate(bars, *, now=None):
    now=timestamp(now or datetime.now(UTC));m1=frame(bars.get('M1',[]),'M1',now)
    payload={'contract':CONTRACT,'symbol':'XAUUSD','as_of':now.isoformat(),
        'execution_authority':False,'execution_influence':False,'validation_status':'MANUAL_REFERENCE_NOT_CALIBRATED',
        'probability':None,'zones':[],'plans':[],'state':'DATA_UNAVAILABLE'}
    if m1.empty:return payload
    last=m1.iloc[-1];close_time=last.timestamp+pd.Timedelta(minutes=1);price=float(last.close)
    frames={tf:frame(bars.get(tf,[]),tf,now) for tf in ['H4','H1','M15','M5']}
    raw=[z for tf in frames for z in detect(bars.get(tf,[]),tf,now)];zones=project(raw,price)
    age=(now-close_time).total_seconds();fresh=0<=age<=420
    return {**payload,'state':'MAP_AVAILABLE' if fresh else 'STALE_PRICE','price':price,
        'price_observed_at':close_time.isoformat(),'zones':zones,
        'plans':build_plans(zones,frames,price,now) if fresh else [],
        'bar_counts':{tf:len(f) for tf,f in frames.items()},
        'timeframe_fresh':{tf:_fresh_frame(f,tf,now) for tf,f in frames.items()},
        'timeframe_closed_at':{tf:(f.iloc[-1].timestamp+pd.Timedelta(minutes=MINUTES[tf])).isoformat() if len(f) else None for tf,f in frames.items()},
        'source':'CTRADER_MARKET_DATA_READ_ONLY','collection_interval_minutes':5}


def validate(payload, *, now=None):
    p=dict(payload)
    if p.get('contract')!=CONTRACT or p.get('symbol')!='XAUUSD' or p.get('execution_authority') is not False or p.get('execution_influence') is not False:
        raise ValueError('Kontrak peta manual tidak valid')
    if p.get('probability') is not None:raise ValueError('Probabilitas manual belum terkalibrasi')
    current=timestamp(now or datetime.now(UTC));age=(current-timestamp(p['as_of'])).total_seconds()
    price_age=(current-timestamp(p['price_observed_at'])).total_seconds() if p.get('price_observed_at') else None
    if p.get('price') is not None:
        p['price']=float(p['price'])
        if not math.isfinite(p['price']) or p['price']<=0:raise ValueError('Harga snapshot tidak valid')
    p['fresh']=bool(-5<=age<=420 and price_age is not None and -5<=price_age<=420 and p.get('state')=='MAP_AVAILABLE')
    p['age_seconds']=price_age
    for z in p.get('zones',[]):
        if z.get('direction') not in {'BUY','SELL'} or z.get('timeframe') not in MAX_AGE_HOURS or not all(math.isfinite(float(z[k])) for k in ['low','high','invalidation']) or not 0<z['low']<z['high']:
            raise ValueError('Geometri zona manual tidak valid')
        if timestamp(z['available_at'])>timestamp(p['as_of']):raise ValueError('Zona dari candle masa depan')
        if (z['direction']=='BUY' and z['invalidation']>=z['low']) or (z['direction']=='SELL' and z['invalidation']<=z['high']):raise ValueError('Invalidasi tidak di luar zona')
        if z.get('probability') is not None:raise ValueError('Probabilitas zona belum terkalibrasi')
    indexed={z['zone_id']:z for z in p.get('zones',[])}
    for plan in p.get('plans',[]):
        anchor=plan.get('anchor') or {}
        if anchor.get('zone_id') not in indexed or anchor!=indexed[anchor['zone_id']] or anchor.get('timeframe') not in {'H4','H1'} or not anchor.get('eligible') or plan.get('direction')!=anchor.get('direction'):
            raise ValueError('Acuan utama harus H4/H1 yang valid')
        if plan.get('execution_authority') is not False or plan.get('execution_influence') is not False or plan.get('probability') is not None:raise ValueError('Rencana manual tidak boleh mengatur eksekusi')
        for field in ['rejection_m15_at','confirmation_m5_at']:
            if plan.get(field) and timestamp(plan[field])>timestamp(p['as_of']):raise ValueError('Konfirmasi dari masa depan')
        if plan.get('confirmation_m5_at') and (not plan.get('rejection_m15_at') or timestamp(plan['confirmation_m5_at'])<=timestamp(plan['rejection_m15_at'])):raise ValueError('Urutan konfirmasi tidak valid')
        target=plan.get('target_reference')
        if target is not None and (not math.isfinite(float(target)) or (float(target)-p['price'])*(1 if plan['direction']=='BUY' else -1)<=0):raise ValueError('Target sudah dilewati harga')
    return p
