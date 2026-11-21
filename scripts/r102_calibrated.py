"""RIZAN R10.2. Research-only calibrated classification with close-to-close labels.
Reads immutable candle artifacts from R10 run 44901264975; never places orders.
Train 2019-2022, probability calibration 2023H1, rule selection 2023H2,
report 2024-2026 (previously inspected data; NOT pristine holdout).
"""
import argparse, glob, json, warnings
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import brier_score_loss, log_loss
from scipy.special import logit
from r10_million import load, ohlc_indicators, wilson
warnings.filterwarnings('ignore',category=RuntimeWarning)
OUT=Path('artifacts');OUT.mkdir(exist_ok=True)
def context(z,h1,hours):
    h=h1.copy()
    d=h.resample('1D',label='left',closed='left').agg(c=('c','last'),o=('o','first'),bars=('c','count'))
    d=d[d.bars>=16]
    day=pd.DataFrame({'d1_mom':d.c.pct_change(3),'d1_trend':d.c/d.c.ewm(span=10,adjust=False).mean()-1,'d1_body':(d.c-d.o)/d.o},index=d.index+pd.Timedelta(days=1))
    start=h.index.floor('D')-pd.to_timedelta(h.index.dayofweek,unit='D')
    w=h.groupby(start).agg(c=('c','last'),o=('o','first'),bars=('c','count'))
    w=w[w.bars>=55]
    weekly=pd.DataFrame({'w1_mom':w.c.pct_change(),'w1_trend':w.c/w.c.ewm(span=5,adjust=False).mean()-1,'w1_body':(w.c-w.o)/w.o},index=w.index+pd.Timedelta(days=7))
    signal_time=z.index+pd.Timedelta(hours=hours)
    for a in [day,weekly]:
        a=a.loc[~a.index.duplicated()].sort_index()
        vals=a.reindex(signal_time,method='ffill')
        for k in vals.columns:z[k]=vals[k].to_numpy()
def prepare(tf):
    h1=load('1h');d=load(tf);hours=1 if tf=='1h' else 4
    z=ohlc_indicators(d);context(z,h1,hours)
    c=d.c.to_numpy(dtype=float);future=d.c.shift(-1).to_numpy(dtype=float)
    distance=(d.index.to_series().shift(-1)-d.index.to_series()==pd.Timedelta(hours=hours)).to_numpy()
    y=(future>c).astype('int8')
    valid=distance & np.isfinite(future)&(future!=c)
    x=z.drop(columns=['c','o','h','l','prev5h','prev5l','prev8h','prev8l','prev20h','prev20l']).copy()
    for k in ['sweep5','break8']:
        x[k]=pd.to_numeric(x[k],errors='coerce')
    x['hour_sin']=np.sin(2*np.pi*z.index.hour/24)
    x['hour_cos']=np.cos(2*np.pi*z.index.hour/24)
    x['weekday_sin']=np.sin(2*np.pi*z.index.dayofweek/7)
    x['weekday_cos']=np.cos(2*np.pi*z.index.dayofweek/7)
    x=x.replace([np.inf,-np.inf],np.nan)
    valid &= x.notna().all(axis=1).to_numpy()
    return d,z,x,y,valid
def metrics(y,p,cut,ret,cost):
    b=p>=cut;s=p<=1-cut
    if cut==0.5:s=p<0.5
    def each(m,side):
        n=int(m.sum());k=int((y[m]==side).sum())
        pnl=(ret[m]*(1 if side else -1))-cost
        return {'n':n,'correct':k,'accuracy':round(k/n,6) if n else None,
                'wilson_lower95':round(wilson(k,n),6) if n else None,
                'gross_mean_usd_oz':round(float(np.mean(ret[m]*(1 if side else -1))),5) if n else None,
                'net_mean_after_cost_scenario_usd_oz':round(float(np.mean(pnl)),5) if n else None}
    return {'buy':each(b,1),'sell':each(s,0),'coverage':round(float((b|s).mean()),6),
            'brier':round(float(brier_score_loss(y,p)),6)}
def platt(cal_p,cal_y,p):
    calib=LogisticRegression(C=.3,max_iter=1000).fit(logit(np.clip(cal_p,1e-5,1-1e-5)).reshape(-1,1),cal_y)
    return calib.predict_proba(logit(np.clip(p,1e-5,1-1e-5)).reshape(-1,1))[:,1]
def run(tf):
    d,z,x,y,valid=prepare(tf);years=z.index.year
    train=valid&(years>=2019)&(years<=2022)
    cal=valid&(years==2023)&(z.index.month<=6)
    val=valid&(years==2023)&(z.index.month>=7)
    test=valid&(years>=2024)&(years<=2026)
    assert train.sum()>1000 and cal.sum()>100 and val.sum()>100 and test.sum()>500
    print(json.dumps({'step':'prepare','tf':tf,'dataset_size':len(z),'train':int(train.sum()),'calibration':int(cal.sum()),'validation':int(val.sum()),'evaluation':int(test.sum()),'last':str(z.index.max())}),flush=True)
    data=x.to_numpy(dtype=np.float32)
    # Median imputation not needed: valid filters all nonfinite observations.
    candidates=[]
    configs=[]
    for C in [0.03,0.3,3,30]:
        configs.append(('logistic',C,None,make_pipeline(StandardScaler(),LogisticRegression(C=C,max_iter=400))))
    for depth in [3,5]:
        for leaves in [15,31]:
            for l2 in [1,20]:
                configs.append(('histgb',(depth,leaves,l2),None,HistGradientBoostingClassifier(max_iter=120,max_depth=depth,max_leaf_nodes=leaves,l2_regularization=l2,learning_rate=.05,random_state=42)))
    for idx,(family,param,_,model) in enumerate(configs):
        model.fit(data[train],y[train])
        pc=model.predict_proba(data[cal])[:,1];pv=model.predict_proba(data[val])[:,1];pt=model.predict_proba(data[test])[:,1]
        for typ in ['raw','platt']:
            vp=pv if typ=='raw' else platt(pc,y[cal],pv)
            tp=pt if typ=='raw' else platt(pc,y[cal],pt)
            for cut in [.50,.52,.54,.56,.58,.60,.62,.65,.68]:
                m=metrics(y[val],vp,cut,(d.c.shift(-1)-d.c).to_numpy()[val],cost=.7)
                # Per-side n>=40 in 2023H2. Balanced selection, avoid tiny samples.
                eligible=min(m['buy']['n'],m['sell']['n'])>=40
                quality=min(m['buy']['wilson_lower95'] or 0,m['sell']['wilson_lower95'] or 0) if eligible else -1
                candidates.append({'family':family,'params':str(param),'calibration':typ,'cut':cut,
                    'validation':m,'selection_quality':quality,'evaluation':metrics(y[test],tp,cut,(d.c.shift(-1)-d.c).to_numpy()[test],cost=.7),
                    'id':idx,'eligible':eligible})
        print(json.dumps({'step':'trained','tf':tf,'model':idx+1,'total_models':len(configs)}),flush=True)
    candidates.sort(key=lambda a:(a['selection_quality'],a['validation']['coverage']),reverse=True)
    chosen=candidates[0]
    tm=chosen['evaluation']
    annual=[]
    model=configs[chosen['id']][3]
    pt=model.predict_proba(data[test])[:,1]
    if chosen['calibration']=='platt':
        pc=model.predict_proba(data[cal])[:,1]
        pt=platt(pc,y[cal],pt)
    for year in [2024,2025,2026]:
        m=test&(years==year)
        if m.sum():
            pp=pt[years[test]==year]
            annual.append({'year':year,**metrics(y[m],pp,chosen['cut'],(d.c.shift(-1)-d.c).to_numpy()[m],cost=.7)})
    # Trade baseline: sign of previous closed candle is directional; unconditional is buy=base rate.
    eval_ret=(d.c.shift(-1)-d.c).to_numpy()[test]
    baseline={'base_buy_rate':float(y[test].mean()),'persistence_accuracy':float(np.mean((z.body.to_numpy()[test]>0)==y[test])),
       'cost_scenario_usd_oz':0.7}
    summary={'version':'R10.2','tf':tf,'data':'HistData derived H1/H4 shards, 2019-2026','label':'direction from current CLOSED candle close to NEXT candle close','time_alignment':'OHLC features known at current bar close; D1 updated after day close, W1 available following Monday 00:00 UTC','periods':{'train':'2019-22','platt_calibration':'2023 Jan-Jun','rule_selection':'2023 Jul-Dec','evaluation':'2024-26 not pristine; prior experiments inspected'},
     'no_macros_claimed':True,'models_trained':len(configs),'candidate_decision_rules_evaluated':len(candidates),
     'selected':{k:v for k,v in chosen.items() if k not in ['id','eligible']},'annual_evaluation':annual,'baseline':baseline,
     'passes_target':tm['buy']['n']>=100 and tm['sell']['n']>=100 and tm['buy']['accuracy']>=.6 and tm['sell']['accuracy']>=.6,
     'notes':['Model selected only using second half 2023; no tuning on evaluation','Cost=0.7 USD/oz is a scenario, not verified FP Markets spread','No leakage from incomplete current D1/W1 candle','2024-26 not pristine since previous experiments inspected','Accuracy is direction, not MFE $10 nor executable trade outcome']}
    (OUT/f'r102-{tf}.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({'step':'done','tf':tf,'chosen':summary['selected'],'baseline':baseline,'pass':summary['passes_target']}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--tf',choices=['1h','4h'],required=True)
    run(p.parse_args().tf)
