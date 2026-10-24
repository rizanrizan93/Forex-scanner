from pathlib import Path
import pandas as pd,numpy as np,json,sys
P=Path(__file__).parent;tag=sys.argv[1];cfg=json.loads((P/(tag+'_config.json')).read_text());cost=int(cfg['cost']);d=pd.read_csv(P/(tag+'_ledger.csv'));zones=pd.read_csv(Path('reversal_search_v2/zones.csv')).set_index('zone_id')
with open(Path('reversal_search_v2/prices.bin'),'rb') as f:
 n=int(np.fromfile(f,'<i8',1)[0]);t=np.fromfile(f,'<i8',n);o,h,l,c,sp=[np.fromfile(f,'<f8',n) for _ in range(5)]
maxdiff=0.;details=[]
for r in d.itertuples():
 z=zones.loc[r.zone_id];j=r.entry_i;k=r.exit_i;start=int(np.searchsorted(t,z.created_s+cfg.get("delay_seconds",0)));side=int(z.side)
 assert t[j]>=z.created_s and j>=start and k>=j
 e=z.hi-cfg['frac']*(z.hi-z.lo) if side==1 else z.lo+cfg['frac']*(z.hi-z.lo)
 assert abs(e-r.entry)<1e-6
 hits=np.flatnonzero(l[start:j+1]+cost*sp[start:j+1]<=e) if side==1 else np.flatnonzero(h[start:j+1]>=e)
 assert len(hits) and hits[0]+start==j
 sl=e-side*cfg['target']*abs(cfg['buffer']) if cfg['buffer']<0 else (z.lo-cfg['buffer']*z.atr if side==1 else z.hi+cfg['buffer']*z.atr)
 assert abs(sl-r.sl)<1e-6 and abs(r.tp-e-side*cfg['target'])<1e-6
 assert (t[j]-z.created_s)/3600<=cfg['ttl']
 hour=pd.to_datetime(t[j],unit='s',utc=True).hour
 if cfg['session']==3:assert 7<=hour<17
 if cfg['session']==1:assert 7<=hour<12
 if cfg['session']==2:assert 12<=hour<17
 if cfg['session']==4:assert 0<=hour<7
 if cfg['session']==5:assert 17<=hour<22
 if cfg.get('direction',0):assert side==cfg['direction']
 a=np.flatnonzero(l[j:k+1]<=sl) if side==1 else np.flatnonzero(h[j:k+1]+cost*sp[j:k+1]>=sl)
 b=np.flatnonzero(h[j+1:k+1]>=r.tp) if side==1 else np.flatnonzero(l[j+1:k+1]+cost*sp[j+1:k+1]<=r.tp)
 si=j+a[0] if len(a) else n;ti=j+1+b[0] if len(b) else n
 reason=1 if si<=ti and si<=k else (2 if ti<=k else 3)
 assert reason==r.reason
 if reason==1:px=min(sl,o[k]) if side==1 else max(sl,o[k]+cost*sp[k])
 elif reason==2:px=r.tp
 else:px=o[k]+(cost*sp[k] if side==-1 else 0)
 nr=(side*(px-e)-.17*cost-.1*(t[k]-t[j])/86400)/(side*(e-sl));maxdiff=max(maxdiff,abs(nr-r.net_R));assert abs(nr-r.net_R)<1e-6
 details.append({'entry_utc':str(pd.to_datetime(t[j],unit='s',utc=True)),'exit_utc':str(pd.to_datetime(t[k],unit='s',utc=True)),'entry_i':j,'MFE_bid':max(0,h[j:k+1].max()-e) if side==1 else max(0,e-l[j:k+1].min()),'MAE_bid':max(0,e-l[j:k+1].min()) if side==1 else max(0,h[j:k+1].max()-e),'hours':(t[k]-t[j])/3600})
assert (d.entry_i.iloc[1:].to_numpy()>d.exit_i.iloc[:-1].to_numpy()).all()
full=pd.concat([d.reset_index(drop=True),pd.DataFrame(details)],axis=1);full.to_csv(P/(tag+'_detailed.csv'),index=False)
def stats(g):
 r=g.net_R;loss=-r[r<0].sum();return {'n':len(g),'win_pct':100*(r>0).mean() if len(g) else 0,'full_tp_pct':100*(g.reason==2).mean() if len(g) else 0,'pf':r[r>0].sum()/loss if loss else None,'net_R':r.sum(),'mean_sl_distance':g.risk.mean(),'median_hold_hours':g.hours.median()}
entry=pd.to_datetime(full.entry_utc,utc=True);train=entry<=pd.Timestamp('2023-01-01',tz='UTC')-pd.Timedelta(hours=cfg['hold']);review=(entry>=pd.Timestamp('2023-01-01',tz='UTC'))&(entry<=pd.Timestamp('2026-01-01',tz='UTC')-pd.Timedelta(hours=cfg['hold']))
results={'independent_first_passage':'PASS','rows':len(d),'max_R_difference':maxdiff,'all':stats(full),'train':stats(full[train]),'review':stats(full[review]),'q1_2026':stats(full[entry.dt.year==2026]),'annual':{str(y):stats(full[entry.dt.year==y]) for y in sorted(entry.dt.year.unique())}}
# Descriptive monthly block bootstrap on review, not corrected for model search.
g=full[review].copy();g['month']=entry[review].dt.strftime('%Y-%m');blocks=[q.net_R.to_numpy() for _,q in g.groupby('month')];rng=np.random.default_rng(2401026);pfs=[]
if blocks:
 for _ in range(2000):
  r=np.concatenate([blocks[i] for i in rng.integers(0,len(blocks),len(blocks))]);loss=-r[r<0].sum()
  if loss:pfs.append(r[r>0].sum()/loss)
results['review_pf_bootstrap95_nominal']=np.quantile(pfs,[.025,.975]).tolist() if pfs else None
(P/(tag+'_audit.json')).write_text(json.dumps(results,indent=2));print(tag,json.dumps(results,default=float))
