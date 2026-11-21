"""RIZAN R11 — 100,663,296 enumerated H1/H4 BUY/SELL parameter tuples.
Immutable historical R10 bars, causal D1/W1 from FIXED r102_calibrated.
12 distinct family anchors x 8^7 parameter choices x 2 timeframes x 2 sides.
Research only. NO LIVE trading, no claim of 100M unique signal sequences.
"""
from __future__ import annotations
import argparse,glob,hashlib,heapq,json,os
from pathlib import Path
import numpy as np
import pandas as pd
from r102_calibrated import prepare,context
from r10_million import load,ohlc_indicators,wilson

OUT=Path('artifacts');OUT.mkdir(exist_ok=True)
FAMILIES=['unconditional','d1_trend','w1_trend','dual_trend',
          'breakout','liquidity_sweep','adx_impulse','adx_range',
          'volatility_expansion','volatility_compression','displacement','pullback']
SPACE=8**7
GROUP_NAMES=['higher_timeframe','trend_strength','momentum','pressure',
             'volatility','liquidity','session']
def asbool(v,index):
    if isinstance(v,bool):return np.full(len(index),v,dtype=bool)
    a=np.asarray(v)
    if len(a)!=len(index):raise ValueError('predicate length mismatch')
    return np.asarray(pd.Series(a,index=index).fillna(False),dtype=bool)
def rules(z,side):
    s=1 if side=='BUY' else -1
    f=lambda v:s*v>0
    u=lambda x:[asbool(a,z.index) for a in x]
    d=z.discount;hour=z.index.hour
    groups=[
      [True,f(z.d1_mom),f(z.w1_mom),f(z.d1_mom)&f(z.w1_mom),
       f(z.d1_trend),f(z.w1_trend),f(z.ema8-z.ema21),f(z.d1_mom)|f(z.w1_mom)],
      [True,z.adx14>15,z.adx14>20,z.adx14>25,z.adx7>20,z.adx21>20,
       f(z.di),(z.adx14>20)&f(z.di)],
      [True,f(z.roc3),f(z.roc8),f(z.macdh),f(z.rsi14-50),
       (z.rsi14>55 if s==1 else z.rsi14<45),f(z.ema8-z.ema21),f(z.eff3)],
      [True,f(z.body),f(z.body)&(z.body.abs()>.4),f(z.clv),
       f(z.clv)&(z.clv.abs()>.4),f(z.wick),f(z.b3),f(z.sweep5)],
      [True,z.atr_rank>.3,z.atr_rank>.6,z.atr_rank<.6,z.rangeratio>1.15,
       z.rangeratio<.85,z.bbwidth>z.bbmedian,z.bbwidth<z.bbmedian],
      [True,f(z.break8),f(z.sweep5),(d<.25 if s==1 else d>.75),
       (d>.75 if s==1 else d<.25),f(z.clv)&(z.rangeratio>1.5),
       f(z.roc3)&(z.rangeratio<.85),f(z.di)],
      [True,(hour>=0)&(hour<6),(hour>=6)&(hour<12),
       (hour>=12)&(hour<18),(hour>=18)&(hour<24),
       (hour>=6)&(hour<16),(hour>=12)&(hour<21),
       ((hour>=13)&(hour<17))|((hour>=0)&(hour<3))]
    ]
    return [u(g) for g in groups]
def anchor(z,side,family):
    s=1 if side=='BUY' else -1
    f=lambda v:s*v>0
    anchors=[
      True, f(z.d1_mom),f(z.w1_mom),f(z.d1_mom)&f(z.w1_mom),
      f(z.break8),f(z.sweep5),(z.adx14>25)&f(z.di),(z.adx14<20),
      (z.atr_rank>.6)&(z.rangeratio>1),(z.atr_rank<.45)&(z.bbwidth<z.bbmedian),
      f(z.clv)&f(z.body)&(z.body.abs()>.25),
      f(z.d1_mom)&(~f(z.roc3))&(z.adx14>15)]
    return asbool(anchors[family],z.index)
def bitpack(a):
    return np.packbits(np.asarray(a,dtype=np.uint8),bitorder='little')
def wlo(k,n):
    n=np.asarray(n,dtype=float);k=np.asarray(k,dtype=float)
    with np.errstate(divide='ignore',invalid='ignore'):
        q=k/np.maximum(1,n);zz=1.96
        v=(q+zz*zz/(2*n)-zz*np.sqrt(q*(1-q)/n+zz*zz/(4*n*n)))/(1+zz*zz/n)
    return np.where(n>0,v,0.)
def metric(y,mask,valid,ret=None,side='BUY',entry=None,high=None,low=None):
    m=mask&valid;n=int(m.sum());correct=int(np.sum(y[m]==(1 if side=='BUY' else 0)))
    result={'n':n,'correct':correct,'accuracy':round(correct/n,6) if n else None,
            'wilson_lower95':round(wilson(correct,n),6) if n else None,
            'coverage':round(n/max(1,int(valid.sum())),6)}
    if ret is not None and n:
        directed=ret[m]*(1 if side=='BUY' else -1)
        result['gross_mean_close_to_close_usd_oz']=round(float(np.mean(directed)),6)
        result['net_mean_cost_scenario_0_7_usd_oz']=round(float(np.mean(directed)-.7),6)
        if entry is not None:
            mfe=high[m]-entry[m] if side=='BUY' else entry[m]-low[m]
            mae=entry[m]-low[m] if side=='BUY' else high[m]-entry[m]
            result['mfe_gte_10_usd_fraction']=round(float(np.mean(mfe>=10)),6)
            result['avg_mfe_usd_oz']=round(float(np.mean(mfe)),6)
            result['avg_mae_usd_oz']=round(float(np.mean(mae)),6)
    return result
def getdataset(tf):
    d,z,x,y,valid=prepare(tf)
    years=z.index.year
    tr=np.asarray(valid&(years>=2019)&(years<=2022))
    va=np.asarray(valid&(years==2023))
    te=np.asarray(valid&(years>=2024)&(years<=2026))
    assert sum(tr)>1000 and sum(va)>200 and sum(te)>500,(sum(tr),sum(va),sum(te))
    return d,z,y,valid,tr,va,te
def exactmask(anchor_all,rule_all,cfg):
    m=anchor_all.copy()
    for axis in range(7):m &= rule_all[axis][(cfg>>(3*axis))&7]
    return m
def pilot(tf):
    d,z,y,valid,tr,va,te=getdataset(tf)
    hours=1 if tf=='1h' else 4
    fullh1=load('1h')
    sample=[]
    ids=np.flatnonzero(valid & z.index.year.isin([2020,2022,2024,2026]))
    for ix in ids[np.linspace(0,len(ids)-1,min(16,len(ids)),dtype=int)]:
        ts=z.index[ix]
        prefix_d=d.loc[d.index<=ts]
        prefix_h1=fullh1.loc[fullh1.index<ts+pd.Timedelta(hours=hours)]
        ctx=ohlc_indicators(prefix_d)
        context(ctx,prefix_h1,hours)
        keys=['d1_mom','d1_trend','d1_body','w1_mom','w1_trend','w1_body',
              'adx14','rsi14','atr_rank','macdh','sweep5','break8']
        failed=[]
        for key in keys:
            a=z.loc[ts,key];b=ctx.loc[ts,key]
            if not np.isclose(a,b,atol=1e-9,rtol=1e-9,equal_nan=True):failed.append(key)
        sample.append({'time':str(ts),'mismatch':failed})
    expected=(d.index.to_series().shift(-1)-d.index.to_series()==pd.Timedelta(hours=hours))
    assert np.all(expected.to_numpy()[valid]),'label has non-contiguous bars'
    assert all(not q['mismatch'] for q in sample),'CAUSAL PREFIX INVARIANCE FAILED'
    result={'tf':tf,'causality':'pass','samples':sample,'label':'closed current candle close to next close; contiguous only',
            'training_bars':int(tr.sum()),'validation_bars':int(va.sum()),'previously_inspected_evaluation_bars':int(te.sum()),
            'last_bar':str(d.index.max())}
    (OUT/f'r11-causal-{tf}.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'stage':'pilot_ok','tf':tf,'samples':len(sample),'train':int(tr.sum()),'validation':int(va.sum()),'evaluation':int(te.sum())}),flush=True)
def sweep(tf,side,family,cap):
    d,z,y,valid,tr,va,te=getdataset(tf)
    anchor_all=anchor(z,side,family)
    rule_all=rules(z,side)
    packed=np.stack([[bitpack(a[tr]) for a in group] for group in rule_all],axis=0)
    anc=bitpack(anchor_all[tr])
    correct=(y[tr]==(1 if side=='BUY' else 0))
    truth=bitpack(correct)
    heap=[];eligible=0;tested=0
    chunk=1024
    for start in range(0,cap,chunk):
        stop=min(cap,start+chunk)
        ids=np.arange(start,stop,dtype=np.uint32)
        m=np.broadcast_to(anc,(len(ids),len(anc))).copy()
        for axis in range(7):
            m &= packed[axis,(ids>>(axis*3))&7]
        n=np.bitwise_count(m).sum(axis=1,dtype=np.int32)
        k=np.bitwise_count(m&truth).sum(axis=1,dtype=np.int32)
        tested+=len(ids)
        eligible_indices=np.flatnonzero(n>=150)
        eligible+=len(eligible_indices)
        if not len(eligible_indices):continue
        lb=wlo(k[eligible_indices],n[eligible_indices])
        selected=eligible_indices[np.argsort(lb)[-min(15,len(lb)):]]
        for j in selected:
            item=(float(wlo(k[j],n[j])),int(ids[j]),int(n[j]),int(k[j]))
            if len(heap)<250:heapq.heappush(heap,item)
            elif item>heap[0]:heapq.heapreplace(heap,item)
        if tested%524288==0:
            print(json.dumps({'stage':'sweep_progress','tf':tf,'side':side,'family':family,'tested':tested,'eligible':eligible}),flush=True)
    cand=sorted(heap,reverse=True)
    seen_train=set();seen_val=set();records=[]
    ret=(d.c.shift(-1)-d.c).to_numpy()
    nxt_hi=d.h.shift(-1).to_numpy();nxt_lo=d.l.shift(-1).to_numpy();entry=d.c.to_numpy()
    for score,cfg,n,k in cand:
        mask=exactmask(anchor_all,rule_all,cfg)
        htrain=hashlib.sha256(bitpack(mask[tr])).hexdigest()
        hval=hashlib.sha256(bitpack(mask[va])).hexdigest()
        if htrain in seen_train or hval in seen_val:continue
        seen_train.add(htrain);seen_val.add(hval)
        v=metric(y,mask,va,side=side)
        if v['n']<35:continue
        a=metric(y,mask,tr,side=side)
        rank=min(float(v['wilson_lower95']),float(a['wilson_lower95']))
        records.append({'family':FAMILIES[family],'family_id':family,'tf':tf,'side':side,
                        'config_index':cfg,'group_choices':[(cfg>>(i*3))&7 for i in range(7)],
                        'rank_on_development_only':rank,'train':a,'validation':v,
                        'training_signal_sha256':htrain,'validation_signal_sha256':hval})
    records.sort(key=lambda a:(a['rank_on_development_only'],a['validation']['n']),reverse=True)
    records=records[:20]
    for item in records:
        mask=exactmask(anchor_all,rule_all,item['config_index'])
        item['evaluation']=metric(y,mask,te,ret,side,entry,nxt_hi,nxt_lo)
        item['evaluation_years']=[]
        for year in [2024,2025,2026]:
            v=te&(z.index.year==year)
            item['evaluation_years'].append({'year':year,**metric(y,mask,v,side=side)})
    report={'version':'R11','tf':tf,'side':side,'family_id':family,'family':FAMILIES[family],
        'parameter_configurations_evaluated':tested,'search_space_per_job':SPACE,
        'eligible_development':eligible,'deduplicated_development_shortlist':len(records),
        'train_years':'2019-2022','validation_year':'2023','evaluation_years':'2024-2026 (previously inspected; NOT pristine)',
        'source':'R10 histdata M1-derived archived candles, job 44901264975',
        'causal_context':'r102_calibrated positional lagged daily and weekly features',
        'strategy_family_anchor':FAMILIES[family],'axes':GROUP_NAMES,
        'candidate_results':records,
        'caveats':['Parameter vectors distinct; signal sequences may repeat','No model selected on evaluation metrics',
            'Multiple-comparison bias across 100M rules; requires unseen forward test',
            'Broker-specific spread/slippage is unknown; 0.7 USD/oz is only hypothetical',
            'MFE>=10 is intrabar high/low reachability, not a realized TP outcome']}
    fn=OUT/f'r11-{tf}-{side}-{family:02d}.json'
    fn.write_text(json.dumps(report,indent=2))
    print(json.dumps({'stage':'sweep_done','file':str(fn),'tf':tf,'side':side,
           'family':family,'tested':tested,'eligible':eligible,'unique_shortlist':len(records),
           'best_validation':records[0]['validation'] if records else None}),flush=True)
def aggregate():
    paths=sorted(glob.glob('/tmp/r11result/r11-*.json'))
    reports=[json.loads(Path(p).read_text()) for p in paths if '-causal-' not in p]
    names={(q['tf'],q['side'],q['family_id']) for q in reports}
    assert len(reports)==48 and len(names)==48,('incomplete sweep',len(reports),len(names))
    assert all(x['parameter_configurations_evaluated']==SPACE for x in reports)
    all_candidates=sum(len(x['candidate_results']) for x in reports)
    summary={'version':'R11','runs':len(reports),'per_job_configurations':SPACE,
          'parameter_configurations_evaluated':sum(x['parameter_configurations_evaluated'] for x in reports),
          'unique_parameter_vectors':len(names)*SPACE,
          'unique_signal_sequences':'NOT measured for all combinations; shortlisted candidates deduplicated by train/validation bitmaps',
          'candidate_shortlists':all_candidates,'eligible_development_total':sum(x['eligible_development'] for x in reports),
          'selected':{},'passing':{},'caveats':[
           '2019-22 training, 2023 validation, 2024-26 previously inspected evaluation, not pristine holdout',
           '100M parameter vectors do not guarantee 100M distinct strategy behaviors',
           'Selection on 2023 across 100M trials has multiple testing risk; no inference of significance without new future period',
           'No production, no live trading, no verified FP Markets spread/slippage']}
    for tf in ['1h','4h']:
        for side in ['BUY','SELL']:
            cand=[c for q in reports if q['tf']==tf and q['side']==side for c in q['candidate_results']]
            cand.sort(key=lambda x:(x['rank_on_development_only'],x['validation']['n']),reverse=True)
            key=f'{tf}_{side}'
            if not cand:summary['selected'][key]=None;summary['passing'][key]=False;continue
            winner=cand[0]
            summary['selected'][key]=winner
            e=winner['evaluation']
            summary['passing'][key]=bool(e['n']>=100 and e['accuracy'] is not None and e['accuracy']>=.6)
    summary['both_directions_both_timeframes_pass']=all(summary['passing'].values())
    OUT.joinpath('r11-100million-summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({'stage':'aggregate_done','tested':summary['parameter_configurations_evaluated'],
        'candidate_shortlists':all_candidates,'passing':summary['passing'],'winners':{k:v['evaluation'] if v else None for k,v in summary['selected'].items()}}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['pilot','sweep','aggregate'])
    p.add_argument('--tf',choices=['1h','4h']);p.add_argument('--side',choices=['BUY','SELL'])
    p.add_argument('--family',type=int);p.add_argument('--cap',type=int,default=SPACE)
    a=p.parse_args()
    if a.mode=='pilot':assert a.tf;pilot(a.tf)
    if a.mode=='sweep':
        assert a.tf and a.side and a.family is not None and 0<=a.family<12 and 1<=a.cap<=SPACE
        sweep(a.tf,a.side,a.family,a.cap)
    if a.mode=='aggregate':aggregate()
