"""Independent Python replay of locked candidate287447, no C++ imports.
Reconstruct H4 indicators/signals and each M1 cash path. Only supports this
no-add/no-BE geometry. Reproduces inherited expiry/SL/TP/stopout precedence.
"""
import pathlib,sys,json,hashlib
import numpy as np
import pandas as pd
src=pathlib.Path(sys.argv[1]);dest=pathlib.Path(sys.argv[2]);dest.mkdir(exist_ok=True)
assert hashlib.sha256(src.read_bytes()).hexdigest()=='c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504'
d=pd.read_csv(src);d.columns=['timestamp','open','high','low','close']+list(d.columns[5:])
t=(pd.to_datetime(d.timestamp).astype('int64')//60_000_000_000).to_numpy();o=d.open.to_numpy();hi=d.high.to_numpy();lo=d.low.to_numpy();cl=d.close.to_numpy()
g=d.assign(bucket=t//240*240,mi=np.arange(len(d))).groupby('bucket',sort=True)
h=g.agg(o=('open','first'),h=('high','max'),l=('low','min'),c=('close','last'),n=('close','size'),mi=('mi','first'))
ht=h.index.to_numpy();ho=h.o.to_numpy();hh=h.h.to_numpy();hl=h.l.to_numpy();hc=h.c.to_numpy();hm=h.mi.to_numpy();hn=h.n.to_numpy()
atr=np.zeros(len(h));e20=atr.copy();e80=atr.copy()
for i in range(len(h)):
 pc=hc[i-1] if i else ho[i];tr=max(hh[i]-hl[i],abs(hh[i]-pc),abs(hl[i]-pc))
 atr[i]=atr[i-1]+(tr-atr[i-1])/14 if i else tr
 e20[i]=e20[i-1]+2/21*(hc[i]-e20[i-1]) if i else hc[i]
 e80[i]=e80[i-1]+2/81*(hc[i]-e80[i-1]) if i else hc[i]
signals=[]
for i in range(100,len(h)-1):
 st=ht[i]+240
 if hn[i]<192 or ht[i+1]!=st or t[hm[i]]!=ht[i] or t[hm[i+1]]!=st or atr[i]<=0:continue
 body=(hc[i]-ho[i])/atr[i]
 side=1 if body>1.4 and hc[i]>hh[i-1] else -1 if body<-1.4 and hc[i]<hl[i-1] else 0
 trend=1 if hc[i]>e80[i] and e20[i]>e80[i] else -1 if hc[i]<e80[i] and e20[i]<e80[i] else 0
 if side and side==trend and st%1440<480:signals.append((st,int(hm[i+1]),side,atr[i]))
def replay(scale=1.,lev=10.,delay=0):
 bal=peak=bpeak=100.;dd=bdd=0.;busy=-1;rows=[];skips=0
 for st,idx,side,a in signals:
  if st<=busy:continue
  if delay:idx=int(np.searchsorted(t,st+delay))
  if idx>=len(t):continue
  first=o[idx]*(1+(.0005 if side>0 else 0)+side*.0001*scale);dist=2*a;stop=first-side*dist;tp=first+side*dist*12
  risk=.23 if side>0 else .02;frac=.95 if side>0 else .30
  pu=abs(first-stop)+2*first*.0005*scale+first*.0001*scale
  qty=np.floor(min(bal*risk/pu,bal*frac/(first*(1/lev+.0005*scale)),100)/.01+1e-12)*.01
  if qty<.01 or qty*first*(1/lev+.0005*scale)>bal*frac+1e-9:skips+=1;continue
  expiry=min(t[-1]+1,st+32*240)
  end=min(len(t),int(np.searchsorted(t,expiry))+1)
  ix=np.arange(idx,end);tt=t[ix];op=o[ix];high=hi[ix]*(1+(.0005 if side<0 else 0));low=lo[ix]*(1+(.0005 if side<0 else 0));exop=op*(1+(.0005 if side<0 else 0))
  stop_hit=low<=stop if side>0 else high>=stop;target_hit=high>=tp if side>0 else low<=tp
  expired=tt>=expiry
  feein=qty*first*.0005*scale
  dt=np.r_[0,np.diff(tt)]/1440.;fin=np.cumsum(qty*op*.0003*scale*dt)
  xp=np.where(expired,exop,np.where(stop_hit,np.minimum(stop,exop) if side>0 else np.maximum(stop,exop),np.where(target_hit,np.maximum(tp,exop) if side>0 else np.minimum(tp,exop),0.)))
  xp=np.where(xp>0,xp-side*exop*.0001*scale,0.)
  worst=low.copy() if side>0 else high.copy()
  worst=np.where(stop_hit,np.minimum(stop,exop) if side>0 else np.maximum(stop,exop),worst)
  worst=np.where(xp>0,np.minimum(worst,xp) if side>0 else np.maximum(worst,xp),worst)
  ew=bal+side*(worst-first)*qty-feein-fin-qty*worst*.0005*scale
  liquid=(ew<=qty*worst/lev*.5)&(xp==0)
  xp=np.where(liquid,worst-side*worst*.0001*scale,xp)
  hits=np.flatnonzero(xp>0);j=int(hits[0]) if len(hits) else len(ix)-1
  exitprice=xp[j]
  reason='EXPIRY' if expired[j] else 'SL' if stop_hit[j] else 'TP' if target_hit[j] else 'MODEL_STOPOUT' if liquid[j] else 'BOUNDARY_CLOSE'
  if not exitprice:exitprice=cl[ix[j]]*(1+(.0005 if side<0 else 0))-side*cl[ix[j]]*.0001*scale
  best=np.where(stop_hit,exop,np.minimum(high,tp) if side>0 else np.maximum(low,tp))
  eb=bal+side*(best-first)*qty-feein-fin-qty*best*.0005*scale
  close=cl[ix]*(1+(.0005 if side<0 else 0));ec=bal+side*(close-first)*qty-feein-fin-qty*close*.0005*scale
  path=np.column_stack([eb[:j+1],ew[:j+1],ec[:j+1]]).ravel()[:-1]
  running=np.maximum.accumulate(np.r_[peak,path]);dd=max(dd,float(np.max(100*(1-np.r_[peak,path]/running))));peak=float(running[-1])
  gross=side*(exitprice-first)*qty;feeout=qty*exitprice*.0005*scale;net=gross-feein-feeout-fin[j];bal+=net
  peak=max(peak,bal);dd=max(dd,100*(1-bal/peak));bpeak=max(bpeak,bal);bdd=max(bdd,100*(1-bal/bpeak));busy=int(tt[j])
  rows.append(dict(signal_minute=st,entry_minute=int(t[idx]),exit_minute=busy,side=side,quantity=qty,entry_average=first,exit_price=exitprice,gross_pnl=gross,entry_commission=feein,exit_commission=feeout,financing=fin[j],net_pnl=net,balance=bal,reason=reason))
  if bal<.01*o[int(np.searchsorted(t,st))]/(lev*2) or bal<=0:break
 ledger=pd.DataFrame(rows);return dict(equity=bal,floating_dd=dd,balance_dd=bdd,trades=len(rows),skips=skips),ledger
checks=[]
for case,scale,lev,delay in [('BASE',1,10,0),('COST1_5',1.5,10,0),('COST2',2,10,0),('DELAY_NEXT_M1',1,10,1),('LEVERAGE2',1,2,0),('LEVERAGE5',1,5,0)]:
 metrics,l=replay(scale,lev,delay);l.to_csv(dest/f'PYTHON_287447_{case}_ledger.csv',index=False)
 expected=pd.read_csv(pathlib.Path(sys.argv[3])/f'candidate_287447_{case}_ledger.csv')
 assert len(l)==len(expected)
 errors={k:float(abs(l[k]-expected[k]).max()) for k in ['side','quantity','entry_average','exit_price','gross_pnl','entry_commission','exit_commission','financing','net_pnl','balance']}
 target=pd.read_csv(pathlib.Path(sys.argv[3])/'RESULTS.csv');target=target[target['case']==case].iloc[0]
 for k in ['equity','floating_dd','balance_dd']:assert abs(metrics[k]-target[k])<max(1e-7,abs(target[k])*1e-9),(case,k,metrics[k],target[k])
 assert max(errors.values())<1e-5,(case,errors)
 checks.append(dict(case=case,metrics=metrics,ledger_max_errors=errors,passed=True))
 print(case,metrics,flush=True)
(dest/'INDEPENDENT_PYTHON_CHECK.json').write_text(json.dumps(checks,indent=2))
