import os,sys,json,hashlib,glob
from pathlib import Path
import numpy as np,pandas as pd
from itertools import product
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import make_pipeline
from sklearn.metrics import brier_score_loss
from scipy.special import logit,expit
P=Path('artifacts');P.mkdir(exist_ok=True)
if sys.argv[1]=='shard':
 y=int(os.environ['XAU_V193_YEAR']); p=Path(os.environ['XAU_V193_PRICE_CSV'])
 v=json.loads(Path(os.environ['XAU_V193_PRICE_PROVENANCE']).read_text())
 assert hashlib.sha256(p.read_bytes()).hexdigest()==v['normalized_csv_sha256']
 d=pd.read_csv(p);d.index=pd.to_datetime(d.pop('timestamp'),utc=True)
 d=d[d.index.year==y];a=d.resample('1D').agg(o=('open','first'),h=('high','max'),l=('low','min'),c=('close','last'),n=('close','size'))
 a=a[(a.n>=1200)&(a.index.dayofweek<5)]
 if y==2026:a=a[a.index<pd.Timestamp.now(tz='UTC').floor('D')]
 a.to_csv(P/f'daily-{y}.csv');(P/f'prov-{y}.json').write_text(json.dumps(v));sys.exit()
paths=sorted(glob.glob('/tmp/r98/daily-*.csv'))
assert len(paths)>=10,paths
d=pd.concat([pd.read_csv(p,index_col=0,parse_dates=True) for p in paths]).sort_index()
d=d[~d.index.duplicated()];c=d.c;r=c.pct_change();f={}
for w in [2,3,5,8,10,13,20,30,50,90,120]:
 f[f'mom{w}']=c.pct_change(w)
 f[f'trend{w}']=c/c.rolling(w).mean()-1
 f[f'pos{w}']=(c-d.l.rolling(w).min())/(d.h.rolling(w).max()-d.l.rolling(w).min())
 f[f'vol{w}']=r.rolling(w).std()
 f[f'eff{w}']=c.diff(w)/c.diff().abs().rolling(w).sum()
f['body']=(d.c-d.o)/(d.h-d.l);f['range']=(d.h-d.l)/c
X=pd.DataFrame(f).shift(1).replace([np.inf,-np.inf],np.nan)
Y=(d.c>d.o).astype(int);ok=X.notna().all(axis=1)&(d.c!=d.o);X=X[ok];Y=Y[ok];yr=X.index.year
def met(y,p,t):
 b=p>=t;s=p<=1-t
 if t==.5:s=p<.5
 return dict(buy_n=int(b.sum()),sell_n=int(s.sum()),buy_acc=float(y[b].mean()) if b.any() else None,sell_acc=float(1-y[s].mean()) if s.any() else None,coverage=float((b|s).mean()),brier=float(brier_score_loss(y,p)))
rows=[];preds=[]
for family,w,C in product(['logit','hgb'],[3,5,10,99],[.03,.3,3]):
 for year in sorted(set(yr)):
  if year<2017:continue
  train=(yr<year-1)&(yr>=year-w-1);cal=yr==year-1;test=yr==year
  if train.sum()<300 or cal.sum()<100 or not test.any():continue
  model=make_pipeline(StandardScaler(),LogisticRegression(C=C,max_iter=500)) if family=='logit' else HistGradientBoostingClassifier(max_iter=80,max_leaf_nodes=7,l2_regularization=C,random_state=42)
  model.fit(X[train],Y[train])
  cp=model.predict_proba(X[cal])[:,1];tp=model.predict_proba(X[test])[:,1]
  z=logit(np.clip(cp,1e-5,1-1e-5)).reshape(-1,1)
  pl=LogisticRegression(C=1).fit(z,Y[cal])
  pp=pl.predict_proba(logit(np.clip(tp,1e-5,1-1e-5)).reshape(-1,1))[:,1]
  for typ,p in [('raw',tp),('platt',pp)]:
   for t in [.5,.52,.55,.57,.6,.65,.7]:
    rows.append(dict(family=family,window=w,C=C,year=int(year),calibration=typ,threshold=t,**met(Y[test].to_numpy(),p,t)))
   preds.extend(dict(date=str(dt),family=family,window=w,C=C,calibration=typ,p=float(v),y=int(y)) for dt,v,y in zip(X[test].index,p,Y[test]))
pd.DataFrame(rows).to_csv(P/'r98-yearly.csv',index=False)
pr=pd.DataFrame(preds);pr.to_csv(P/'r98-predictions.csv',index=False)
out=[]
for k,g in pr.groupby(['family','window','C','calibration']):
 for t in [.5,.52,.55,.57,.6,.65,.7]:
  rec=dict(config=list(k),threshold=t)
  for name,mask in [('development',g.date.str[:4].astype(int)<=2020),('evaluation',g.date.str[:4].astype(int)>=2021)]:
   a=g[mask];rec[name]=met(a.y.to_numpy(),a.p.to_numpy(),t)
  out.append(rec)
out.sort(key=lambda a:min(a['development']['buy_acc'] or 0,a['development']['sell_acc'] or 0) if min(a['development']['buy_n'],a['development']['sell_n'])>=100 else -1,reverse=True)
(P/'r98-results.json').write_text(json.dumps(dict(years=sorted(set(map(int,yr))),configurations=len(out),candidates=out[:20],all_results=out),indent=2))
print(json.dumps(out[:3]))
