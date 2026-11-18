"""R2 H1/H4 bidirectional forecast tournament: training <=2023, 2024 selection, 2025-26 untouched test.

Never imports broker/bridge code. Strictly a historical research-only predictor.
"""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
from research.zone_rebound.h1h4_accuracy_r2 import (
    FEATURES,SOURCE,make_features,validate_m1,EXECUTION_AUTHORITY,EXECUTION_INFLUENCE)

COST_USD=.50  # scenario only, NOT an empirical FP Markets executable cost
THRESHOLDS=(.52,.55,.58,.60,.62,.65,.68,.70)
GATES=('ALL','HTF_ALIGN','TF_MOMENTUM')
MODEL_TYPES=('LOGIT','HGB')
CONTRACT='RIZAN_XAU_H1H4_ACCURACY_R2'
MIN_VAL={60:25,240:12}
MIN_TEST={60:100,240:40}
TRAIN=tuple(range(2019,2024))
VAL=(2024,)
TEST=(2025,2026)

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()

def generate_year(csv,year,output):
    price=validate_m1(pd.read_csv(csv))
    both=pd.concat([make_features(price,year,tf) for tf in (60,240)],ignore_index=True)
    output.parent.mkdir(parents=True,exist_ok=True)
    data=output.with_suffix('.csv.gz')
    both.to_csv(data,index=False,compression='gzip',float_format='%.11g')
    result={'contract':CONTRACT,'year':year,'csv':data.name,
            'data_sha256':sha(data),'original_sha256':sha(csv),
            'source':SOURCE,'rows':len(both),
            'rows_h1':int((both.timeframe==60).sum()),
            'rows_h4':int((both.timeframe==240).sum()),
            'complete_h1':int(((both.timeframe==60)&both.complete).sum()),
            'complete_h4':int(((both.timeframe==240)&both.complete).sum()),
            'max_data_utc':price.index[-1].isoformat(),
            'execution_authority':False,'execution_influence':False}
    output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result

def models():
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import HistGradientBoostingClassifier
    return {
        'LOGIT':make_pipeline(SimpleImputer(strategy='median',add_indicator=False),
                              StandardScaler(),
                              LogisticRegression(C=.16,max_iter=450,random_state=19)),
        'HGB':HistGradientBoostingClassifier(max_iter=110,max_leaf_nodes=7,max_depth=3,
                   learning_rate=.035,l2_regularization=18,min_samples_leaf=120,
                   early_stopping=False,random_state=19),
    }

def wilson(w,n,z=1.9599639845):
    if n==0:return 0.
    p=w/n; z2=z*z
    return (p+z2/(2*n)-z*np.sqrt((p*(1-p)+z2/(4*n))/n))/(1+z2/n)

def filter_gate(d,side,gate):
    if gate=='ALL':return np.ones(len(d),dtype=bool)
    if gate=='HTF_ALIGN':
        return (d['h4_ema20_slope'].to_numpy()*side>0)&(d['h4_ema20_dev'].to_numpy()*side>0)
    if gate=='TF_MOMENTUM':
        return (d['tf_ema20_slope'].to_numpy()*side>0)&(d['tf_return3'].to_numpy()*side>0)&(d['tf_adx'].to_numpy()>=.16)
    raise ValueError('UNKNOWN_GATE')

def propose(df,p_up,threshold,gate):
    sides=np.where(p_up>=threshold,1,np.where(p_up<=1-threshold,-1,0))
    buy=(sides==1)&filter_gate(df,1,gate)
    sell=(sides==-1)&filter_gate(df,-1,gate)
    return np.where(buy,1,np.where(sell,-1,0))

def evaluate(df,side,yrs):
    target=df.year.isin(yrs).to_numpy()
    coverage=int(target.sum())
    out={'universe':coverage,'selected':int(((side!=0)&target).sum()),'buy':{},'sell':{}}
    for label,s in (('buy',1),('sell',-1)):
        sel=target&(side==s)
        sample=df.loc[sel]
        n=int(len(sample))
        c=int(sample.complete.sum()) if n else 0
        net=sample.gross_forward_usd.to_numpy()*s-COST_USD if n else np.array([])
        wins=int(np.sum((net>0)&sample.complete.to_numpy())) if n else 0
        x={'signals':n,'evaluated':c,'gaps':n-c,'wins':wins,
           'accuracy':wins/c if c else None,
           'wilson_lower95':wilson(wins,c),
           'median_net_move':float(np.nanmedian(net)) if c else None}
        out[label]=x
    out['coverage']=out['selected']/coverage if coverage else 0
    return out

def load_dataset(shards):
    if len(shards)!=8:raise ValueError('EIGHT_YEAR_SHARDS_REQUIRED')
    manifests=[json.loads(p.read_text()) for p in shards]
    years=[int(m['year']) for m in manifests]
    if set(years)!=set(range(2019,2027)) or len(set(years))!=len(years):
        raise ValueError('YEARS_2019_2026_REQUIRED')
    frames=[]
    for p,m in zip(shards,manifests):
        if m['contract']!=CONTRACT or m.get('execution_authority') is not False:
            raise ValueError('INVALID_RESEARCH_SHARD')
        data=p.parent/m['csv']
        if sha(data)!=m['data_sha256']:raise ValueError('DATA_SHA_MISMATCH')
        q=pd.read_csv(data)
        if set(FEATURES)-set(q.columns):raise ValueError('FEATURE_SCHEMA_MISMATCH')
        if len(q)!=m['rows']:raise ValueError('ROW_COUNT_MISMATCH')
        if not (q.year==m['year']).all():raise ValueError('YEAR_CONTAMINATION')
        frames.append(q)
    return pd.concat(frames,ignore_index=True),manifests

def aggregate(shards,report_path):
    d,manifests=load_dataset(shards)
    selected={}; full_rank={}
    for tf in (60,240):
        q=d[(d.timeframe==tf)&d.complete].sort_values('timestamp').copy()
        # Training on 2019-2023 ONLY; 2024 chooses a frozen policy.
        train=q[q.year.isin(TRAIN)]
        x_train=train[FEATURES].replace([np.inf,-np.inf],np.nan)
        y=(train.gross_forward_usd>0).astype(int)
        if len(train)<200 or y.nunique()!=2:raise ValueError('TRAIN_INSUFFICIENT')
        fitted=models()
        for model in fitted.values():model.fit(x_train,y)
        # Test probabilities computed only after validation selection has been frozen.
        v=q[q.year.isin(VAL)]
        x_val=v[FEATURES].replace([np.inf,-np.inf],np.nan)
        trials=[]
        for model_name,model in fitted.items():
            prob=model.predict_proba(x_val)[:,1]
            for th in THRESHOLDS:
                for gate in GATES:
                    action=propose(v,prob,th,gate)
                    metrics=evaluate(v,action,VAL)
                    a=metrics['buy'];b=metrics['sell']
                    valid=(a['evaluated']>=MIN_VAL[tf] and b['evaluated']>=MIN_VAL[tf])
                    score=min(a['wilson_lower95'],b['wilson_lower95']) if valid else -1
                    trials.append({'model':model_name,'threshold':th,'gate':gate,
                                   'score':score,'validation':metrics,'eligible':valid})
        trials.sort(key=lambda x:(-x['score'],-x['validation']['selected'],x['model'],x['threshold'],x['gate']))
        full_rank[str(tf)]=trials
        best=next((x for x in trials if x['eligible']),None)
        if best is None:
            selected[str(tf)]={'status':'NO_ELIGIBLE_POLICY','validation':None,'test':None}
            continue
        model=fitted[best['model']]
        prob_all=model.predict_proba(q[FEATURES].replace([np.inf,-np.inf],np.nan))[:,1]
        action_all=propose(q,prob_all,best['threshold'],best['gate'])
        train_metrics=evaluate(q,action_all,TRAIN)
        validation=evaluate(q,action_all,VAL)
        test=evaluate(q,action_all,TEST)
        yearly={str(y):evaluate(q,action_all,(y,)) for y in range(2019,2027)}
        samples_ok=min(test[k]['evaluated'] for k in ('buy','sell'))>=MIN_TEST[tf]
        observed60=samples_ok and min(test[k]['accuracy'] or 0 for k in ('buy','sell'))>=.60
        ci60=samples_ok and min(test[k]['wilson_lower95'] for k in ('buy','sell'))>=.60
        selected[str(tf)]={'status':'EVALUATED_RESEARCH_ONLY',
            'policy':{k:best[k] for k in ('model','threshold','gate')},
            'selection_basis':'2024 maximize worse-side Wilson lower95 with sample floor',
            'training':train_metrics,'validation':validation,'test_2025_26':test,
            'annual':yearly,'observed_both_sides_60pct':bool(observed60),
            'both_sides_wilson_lower95_above_60pct':bool(ci60),
            'minimum_test_sample_met':bool(samples_ok)}
    report={'contract':CONTRACT+'_AGGREGATE','years':list(range(2019,2027)),
        'source':SOURCE,'cost_scenario_usd_per_oz':COST_USD,
        'split':{'train':'2019-2023','policy_selection':'2024','test':'2025-2026'},
        'no_fred_or_dxy_intraday':True,'real_market_replay':True,
        'not_fp_markets_executable':True,
        'execution_authority':False,'execution_influence':False,
        'warning':'2025-2026 already seen by earlier R1 project; not project-pristine OOS. Explore never implies a deploy-ready strategy.',
        'selected':selected,'ranking':full_rank,'shards':manifests}
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    for tf,p in selected.items():
        if p['status']!='EVALUATED_RESEARCH_ONLY':
            print('DIRECTION_R2',tf,p['status']);continue
        t=p['test_2025_26']
        print('DIRECTION_R2',tf,'policy',p['policy'],
              'test_buy',t['buy']['accuracy'],'n',t['buy']['evaluated'],
              'test_sell',t['sell']['accuracy'],'n',t['sell']['evaluated'],
              'pass60',p['observed_both_sides_60pct'])
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--csv',type=Path);p.add_argument('--year',type=int)
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--aggregate',nargs='*',type=Path)
    a=p.parse_args()
    if a.aggregate is not None:
        aggregate(a.aggregate,a.out)
    else:
        if a.csv is None or a.year not in range(2019,2027):
            p.error('Input CSV and year 2019..2026 required')
        result=generate_year(a.csv,a.year,a.out)
        print('DIRECTION_R2_SHARD',result['year'],result['rows'],
              'complete_h1',result['complete_h1'],'complete_h4',result['complete_h4'])
if __name__=='__main__':main()
