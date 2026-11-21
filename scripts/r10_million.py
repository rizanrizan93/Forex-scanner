"""RIZAN R10: bit-packed, auditable multi-timeframe setup sweep.
Research only. No orders, no production writes.
Data: HistData XAUUSD M1 normalized to UTC by v193 downloader.
"""
import argparse, hashlib, json, os, heapq, glob
from pathlib import Path
import numpy as np
import pandas as pd

OUT = Path('artifacts'); OUT.mkdir(exist_ok=True)

def shard():
    year = int(os.environ['XAU_V193_YEAR'])
    source = Path(os.environ['XAU_V193_PRICE_CSV'])
    prov = json.loads(Path(os.environ['XAU_V193_PRICE_PROVENANCE']).read_text())
    assert hashlib.sha256(source.read_bytes()).hexdigest() == prov['normalized_csv_sha256'], 'source checksum mismatch'
    a = pd.read_csv(source)
    a.index = pd.to_datetime(a.pop('timestamp'), utc=True)
    a = a.loc[a.index.year == year]
    assert a.index.is_monotonic_increasing and a.index.is_unique
    for tf, minimum in [('1h', 40), ('4h', 160)]:
        x = a.resample(tf, label='left', closed='left').agg(o=('open','first'), h=('high','max'), l=('low','min'), c=('close','last'), minutes=('close','count'))
        x = x[x.minutes >= minimum]
        x.to_csv(OUT / f'r10-{tf}-{year}.csv')
    (OUT/f'r10-provenance-{year}.json').write_text(json.dumps({**prov,'derived_by':'r10_million.py','year':year},indent=2))
    print(json.dumps({'stage':'shard','year':year,'input_rows':len(a),'failed_periods':len(prov.get('failed_periods',[])),'sha':prov['normalized_csv_sha256']}))

def rsi(c,n):
    q=c.diff();up=q.clip(lower=0).ewm(alpha=1/n,adjust=False).mean();dn=(-q.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean()
    return 100-100/(1+up/dn.replace(0,np.nan))

def ohlc_indicators(d):
    c,h,l,o = (d[k].astype(float) for k in ['c','h','l','o'])
    z = pd.DataFrame(index=d.index)
    rng = (h-l).replace(0,np.nan)
    z['clv'] = (2*c-h-l)/rng
    z['body'] = (c-o)/rng
    z['wick'] = ((o.where(o<c,c)-l)-(h-o.where(o>c,c)))/rng
    z['b3'] = z['body'].rolling(3).mean()
    z['eff3'] = c.diff(3) / c.diff().abs().rolling(3).sum().replace(0,np.nan)
    z['rsi7'] = rsi(c,7);z['rsi14'] = rsi(c,14)
    z['roc3'] = c.pct_change(3);z['roc8'] = c.pct_change(8)
    z['ema8'] = c.ewm(span=8,adjust=False).mean()
    z['ema21'] = c.ewm(span=21,adjust=False).mean()
    e12 = c.ewm(span=12,adjust=False).mean();e26 = c.ewm(span=26,adjust=False).mean()
    z['macdh'] = (e12-e26)-(e12-e26).ewm(span=9,adjust=False).mean()
    tr = pd.concat([(h-l).abs(),(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    z['atr14'] = tr.ewm(alpha=1/14,adjust=False).mean()
    plus = h.diff().clip(lower=0).where(h.diff()>-l.diff(),0)
    minus = (-l.diff()).clip(lower=0).where((-l.diff())>h.diff(),0)
    for window in [7,14,21,28]:
        atr = tr.ewm(alpha=1/window,adjust=False).mean()
        pdi = 100*plus.ewm(alpha=1/window,adjust=False).mean()/atr.replace(0,np.nan)
        mdi = 100*minus.ewm(alpha=1/window,adjust=False).mean()/atr.replace(0,np.nan)
        dx = 100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
        z[f'adx{window}'] = dx.ewm(alpha=1/window,adjust=False).mean()
        if window==14:z['di'] = pdi-mdi
    z['atr_pct'] = (z.atr14/c)
    z['atr_rank'] = z.atr_pct.rolling(100,min_periods=50).rank(pct=True)
    z['bbwidth'] = 4*c.rolling(20).std()/c.rolling(20).mean()
    z['bbmedian'] = z.bbwidth.rolling(40).median()
    z['rangeratio'] = rng/rng.rolling(20).median()
    z['prev5h'] = h.shift(1).rolling(5).max();z['prev5l'] = l.shift(1).rolling(5).min()
    z['prev8h'] = h.shift(1).rolling(8).max();z['prev8l'] = l.shift(1).rolling(8).min()
    z['prev20h'] = h.shift(1).rolling(20).max();z['prev20l'] = l.shift(1).rolling(20).min()
    z['discount'] = (c-z.prev20l)/(z.prev20h-z.prev20l).replace(0,np.nan)
    z['break8'] = np.sign(c-z.prev8h).where(c>z.prev8h,np.sign(c-z.prev8l).where(c<z.prev8l,0))
    z['sweep5'] = np.select([(l<z.prev5l)&(c>z.prev5l), (h>z.prev5h)&(c<z.prev5h)], [1,-1],default=0)
    z['c']=c;z['o']=o;z['h']=h;z['l']=l
    return z

def align_context(z, base, daytf, name):
    # base is completed-bar OHLC indexed at period OPEN (UTC).
    # d1 close available next calendar day 00:00 UTC; W1 Fri close available Sat 00:00 UTC.
    if daytf=='D':
        d=base.resample('1D',closed='left',label='left').agg(c=('c','last'),o=('o','first'),n=('c','count'))
        d=d[d.n>=16];available=d.index+pd.Timedelta(days=1)
    else:
        d=base.resample('W-FRI',closed='right',label='right').agg(c=('c','last'),o=('o','first'),n=('c','count'))
        d=d[d.n>=55];available=d.index+pd.Timedelta(days=1)
    changes=d.c.pct_change()
    df=pd.DataFrame({'mom':changes.values,'ema':(d.c/d.c.ewm(span=5,adjust=False).mean()-1).values},index=available)
    df=df[~df.index.duplicated()].sort_index()
    lagged=df.reindex(z.index,method='ffill')
    z[name+'_mom']=lagged['mom'];z[name+'_ema']=lagged['ema']

def load(tf):
    paths=sorted(glob.glob(f'/tmp/r10/r10-{tf}-*.csv'))
    assert len(paths)>=6, f'missing shards {tf}: {paths}'
    d=pd.concat([pd.read_csv(p,index_col=0,parse_dates=True) for p in paths]).sort_index()
    d=d[~d.index.duplicated()]
    assert d.index.tz is not None and (d.index.year>=2019).all()
    return d

def predicates(z, side, tf):
    s=1 if side=='BUY' else -1
    gt=lambda x:(s*x)>0
    p=[]
    trend=[None,gt(z.d1_mom),gt(z.w1_mom),gt(z.d1_mom)&gt(z.w1_mom),gt(z.d1_ema),gt(z.w1_ema),gt(z.d1_ema)&gt(z.w1_ema),gt(z.roc8)]
    p.append(trend)
    adx=[None,z.adx7>15,z.adx14>15,z.adx14>20,z.adx14>25,z.adx21>15, (z.adx14>20)&gt(z.di), (z.adx28>20)&gt(z.di)]
    p.append(adx)
    mom=[None,gt(z.rsi14-50),((z.rsi14>55) if s==1 else (z.rsi14<45)),gt(z.rsi7-50),gt(z.roc3),gt(z.roc8),gt(z.ema8-z.ema21),gt(z.macdh)]
    p.append(mom)
    pressure=[None,gt(z.body),gt(z.b3),((z.clv>.4) if s==1 else (z.clv<-.4)),gt(z.wick),gt(z.body)&(z.body.abs()>.55),gt(z.eff3)&(z.eff3.abs()>.4),gt(z.break8)]
    p.append(pressure)
    vol=[None,z.atr_rank>.3,z.atr_rank>.5,z.atr_rank<.6,z.bbwidth>z.bbmedian,z.bbwidth<z.bbmedian,z.rangeratio>1.15,z.rangeratio<.9]
    p.append(vol)
    zone=[None,gt(z.break8),gt(z.sweep5), (z.discount<.25 if s==1 else z.discount>.75), (z.discount>.75 if s==1 else z.discount<.25),gt(z.clv)&(z.rangeratio>1.5),gt(z.roc3)&(z.rangeratio<.85),gt(z.di)]
    p.append(zone)
    hr=z.index.hour
    session=[None,(hr>=1)&(hr<7),(hr>=7)&(hr<13),(hr>=13)&(hr<21),(hr>=13)&(hr<17),(hr>=19)|(hr<2),(hr>=1)&(hr<6),(hr>=6)&(hr<16)]
    p.append(session)
    return [[np.ones(len(z),bool) if x is None else np.asarray(pd.Series(x,index=z.index).fillna(False),dtype=bool) for x in g] for g in p]

def pack(a):return np.packbits(np.asarray(a,dtype=np.uint8),bitorder='little')

def calc_metrics(z, mask, yr_min, yr_max, target, valid):
    ix=mask & valid & (z.index.year>=yr_min)&(z.index.year<=yr_max)
    n=int(ix.sum());correct=int((target[ix]).sum())
    return {'n':n,'accuracy':round(correct/n,6) if n else None, 'correct':correct, 'coverage':round(n/max(1,int((valid&(z.index.year>=yr_min)&(z.index.year<=yr_max)).sum())),6)}

def wilson(k,n):
    if n==0:return 0.
    q=k/n; z=1.96
    return (q+z*z/(2*n)-z*np.sqrt(q*(1-q)/n+z*z/(4*n*n)))/(1+z*z/n)

def unpack_rules(cfg,z,pred):
    mask=np.ones(len(z),dtype=bool)
    for a in range(7):mask &= pred[a][(cfg>>(3*a))&7]
    return mask

def sweep(tf):
    h1=load('1h')
    d=load(tf)
    z=ohlc_indicators(d)
    align_context(z,h1,'D','d1');align_context(z,h1,'W','w1')
    hours=1 if tf=='1h' else 4
    next_o=d.o.shift(-1);next_c=d.c.shift(-1)
    contiguous=(d.index.to_series().shift(-1)-d.index.to_series()==pd.Timedelta(hours=hours)).to_numpy()
    target_buy=np.asarray(next_c>next_o);target_sell=np.asarray(next_c<next_o)
    valid=contiguous & np.isfinite(z.atr14.to_numpy()) & np.isfinite(z.d1_mom.to_numpy()) & np.isfinite(z.w1_mom.to_numpy()) & (next_c.to_numpy()!=next_o.to_numpy())
    tr=valid & (z.index.year<=2022);va=valid & (z.index.year==2023);te=valid & (z.index.year>=2024)
    assert tr.sum()>1000 and va.sum()>500 and te.sum()>500,(tr.sum(),va.sum(),te.sum())
    print(json.dumps({'stage':'dataset','tf':tf,'train':int(tr.sum()),'validation':int(va.sum()),'evaluation':int(te.sum()),'first':str(z.index.min()),'last':str(z.index.max())}),flush=True)
    space=8**7;cap=min(space,int(os.getenv('R10_MAX_CONFIGS',str(space))));chunk=512
    records=[];stats=[]
    for side,correct in [('BUY',target_buy),('SELL',target_sell)]:
        p=predicates(z,side,tf)
        pv=np.stack([[pack(a[tr]) for a in g] for g in p],axis=0)
        base=pack(np.ones(tr.sum(),bool));truth=pack(correct[tr])
        heap=[];evaluated=0;eligible=0
        for start in range(0,cap,chunk):
            stop=min(cap,start+chunk)
            ids=np.arange(start,stop,dtype=np.uint32)
            m=np.broadcast_to(base,(len(ids),len(base))).copy()
            for axis in range(7):
                np.bitwise_and(m,pv[axis,((ids>>(3*axis))&7)],out=m)
            nn=np.bitwise_count(m).sum(axis=1,dtype=np.int32)
            kk=np.bitwise_count(np.bitwise_and(m,truth)).sum(axis=1,dtype=np.int32)
            evaluated+=len(ids)
            good=np.flatnonzero(nn>=100);eligible+=len(good)
            if not len(good):continue
            q=kk[good]/nn[good]
            score=q-1.96*np.sqrt(q*(1-q)/nn[good])
            pick=good[np.argsort(score)[-min(25,len(good)):]]
            for j in pick:
                n=int(nn[j]);k=int(kk[j]);lb=wilson(k,n)
                item=(lb,int(ids[j]),n,k)
                if len(heap)<300:heapq.heappush(heap,item)
                elif item>heap[0]:heapq.heapreplace(heap,item)
            if start and start%(chunk*250)==0:
                print(json.dumps({'stage':'screening','tf':tf,'side':side,'evaluated':evaluated,'eligible':eligible}),flush=True)
        # Validate leading development candidates, dedup validation signal sequences.
        candidates=sorted(heap,reverse=True)
        seen=set();validated=[]
        for lb,cfg,nt,kt in candidates:
            mask=unpack_rules(cfg,z,p)
            sig=hashlib.sha256(pack(mask[va]).tobytes()).hexdigest()
            if sig in seen:continue
            seen.add(sig)
            met=calc_metrics(z,mask,2023,2023,correct,valid)
            if met['n']<30:continue
            vlb=wilson(met['correct'],met['n'])
            validated.append((vlb,cfg,lb,met))
        validated.sort(reverse=True)
        selected=validated[0] if validated else None
        stats.append({'side':side,'parameter_combinations_evaluated':evaluated,'eligible_development':eligible,'candidate_configs_tested_on_validation':len(validated),'selected':selected[1] if selected else None})
        if selected:
            vlb,cfg,tlb,vmet=selected
            mask=unpack_rules(cfg,z,p)
            testmet=calc_metrics(z,mask,2024,2026,correct,valid)
            trainmet=calc_metrics(z,mask,2019,2022,correct,valid)
            # Entry at preceding completed-bar close, next candle max favorable move; spread/slippage excluded.
            next_h=d.h.shift(-1).to_numpy();next_l=d.l.shift(-1).to_numpy();entry=d.c.to_numpy()
            favorable=next_h-entry if side=='BUY' else entry-next_l
            mae=entry-next_l if side=='BUY' else next_h-entry
            ti=mask & te
            move10=float((favorable[ti]>=10).mean()) if ti.any() else None
            avg_mfe=float(np.nanmean(favorable[ti])) if ti.any() else None
            avg_mae=float(np.nanmean(mae[ti])) if ti.any() else None
            records.append({'side':side,'config_id':int(cfg),'axis_choices':[((cfg>>(3*i))&7) for i in range(7)],'train':trainmet,'validation':vmet,'evaluation':testmet,'evaluation_wilson95_lower':wilson(testmet['correct'],testmet['n']),'evaluation_mfe_gte_10_fraction':move10,'evaluation_avg_mfe_usd':avg_mfe,'evaluation_avg_mae_usd':avg_mae,'val_signal_sha256':hashlib.sha256(pack(mask[va])).hexdigest()})
        print(json.dumps({'stage':'side_complete','tf':tf,'side':side,'evaluated':evaluated,'eligible':eligible,'selected':records[-1] if selected else None}),flush=True)
    report={'stage':'R10 million-configuration pilot','timeframe':tf,'time_boundary':'UTC candle left labels; last fully closed D1/W1 context only','data_source':'HistData XAUUSD M1 (secondary) via v193','price_feature_types':'OHLC and derived pressure PROXY; not actual institutional order flow','periods':{'train':'2019-2022','validation':'2023','evaluation':'2024-2026 (not pristine; earlier research used these years)'},'search_space_per_side':space,'axis_names':['trend D1/W1','ADX/DI','momentum','candle pressure','volatility','liquidity zone','session'],'parameters':stats,'selected_results':records,'passes_target':all(x['evaluation']['n']>=100 and x['evaluation']['accuracy']>=.60 for x in records) and len(records)==2,'note':'Search evaluates each enumerated combination on training only; validation used for selection, evaluation for report. No spread/slippage included. OOS 2024-26 is NOT pristine holdout.'}
    (OUT/f'r10-results-{tf}.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'stage':'done','tf':tf,'tested':sum(x['parameter_combinations_evaluated'] for x in stats),'results':records,'pass':report['passes_target']}),flush=True)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('mode',choices=['shard','sweep']);a.add_argument('--tf',choices=['1h','4h']);args=a.parse_args()
    if args.mode=='shard':shard()
    else:sweep(args.tf)
