import pandas as pd,numpy as np,json,glob
from itertools import combinations,product
from pathlib import Path
parts=[]
for p in sorted(glob.glob('/tmp/r97-*.csv')):
 d=pd.read_csv(p,parse_dates=['timestamp']).set_index('timestamp')
 d.index=pd.to_datetime(d.index,utc=True)
 a=d.resample('1D').agg(o=('open','first'),h=('high','max'),l=('low','min'),c=('close','last'),n=('close','size'))
 parts.append(a[a.n>=900])
d=pd.concat(parts).sort_index();d=d[~d.index.duplicated()];d=d[d.index.dayofweek<5]
c=d.c; r=c.pct_change(); f=[]
for w in [2,3,5,8,10,13,20,21,30,40,50,60,90,120]:
 for x in [c.pct_change(w),c/c.rolling(w).mean()-1,(c-d.l.rolling(w).min())/(d.h.rolling(w).max()-d.l.rolling(w).min())-.5,r.rolling(w).mean()/r.rolling(w).std()]:
  f.append(x.shift(1))
X=pd.concat(f,axis=1).to_numpy(); y=np.sign(d.c/d.o-1).to_numpy(); years=d.index.year.to_numpy()
# All thresholds fit on development years only; 2023-24 untouched within this search.
tr=years<=2021; va=years==2022; te=years>=2023
mu=np.nanmean(X[tr],axis=0); sd=np.nanstd(X[tr],axis=0); X=np.clip((X-mu)/np.maximum(sd,1e-9),-5,5)
best=[]; count=0
def metrics(s,m):
 b=(s>0)&m; a=(s<0)&m
 return [int(b.sum()),int(a.sum()),float((y[b]>0).mean()) if b.any() else 0,float((y[a]<0).mean()) if a.any() else 0]
for i,j in combinations(range(X.shape[1]),2):
 for a,b,t in product([-2,-1,-.5,.5,1,2],[-2,-1,-.5,.5,1,2],[0,.15,.3,.5,.75,1,1.5,2,2.5,3]):
  z=a*X[:,i]+b*X[:,j]; s=np.where(z>t,1,np.where(z<-t,-1,0)); count+=1
  m=metrics(s,va)
  if min(m[:2])>=25: best.append((min(m[2:]),i,j,a,b,t,m))
best.sort(reverse=True); out=[]
for score,i,j,a,b,t,m in best[:10]:
 z=a*X[:,i]+b*X[:,j];s=np.where(z>t,1,np.where(z<-t,-1,0))
 out.append(dict(config=[i,j,a,b,t],validation=m,test=metrics(s,te)))
Path('artifacts').mkdir(exist_ok=True)
Path('artifacts/r97.json').write_text(json.dumps(dict(count=count,years=sorted(set(map(int,years))),candidates=out,metric_order=['buy_n','sell_n','buy_accuracy','sell_accuracy']),indent=2))
