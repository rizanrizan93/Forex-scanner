"""Prior-day high/low resting limits at pre-known levels, synthetic BID M1, 2019-2026Q1.
Entry inside touch minute is ambiguous: stop-first, target never allowed until next minute.
"""
import numpy as np,pandas as pd,gc,time
from numba import njit
from run_research import calc_pf,OUT,IN
@njit(cache=True)
def evaluate_event(t,o,h,l,sp,en,di,level,stop_distance,rr,hold,commission,slip):
 n=len(en);v=np.full(n,np.nan);ex=np.full(n,-1,dtype=np.int64)
 for k in range(n):
  j=en[k]; direction=di[k]; entry=level[k];dist=stop_distance[k]
  if j<0 or dist<=0:continue
  sl=entry-direction*dist;tp=entry+direction*dist*rr
  cost=max(sp[j],0)+commission+2*slip
  cap=t[j]+hold*3600*10**9
  ix=j
  while ix<len(t) and t[ix]<=cap:
   if direction==1:
    hitstop=l[ix]<=sl;hittp=h[ix]>=tp
   else:
    hitstop=h[ix]>=sl;hittp=l[ix]<=tp
   if hitstop:
    # stop first, use worse bid opening price on gaps
    price=min(sl,o[ix]) if direction==1 else max(sl,o[ix])
    v[k]=(direction*(price-entry)-cost)/dist;ex[k]=ix;break
   if ix>j and hittp:
    v[k]=(dist*rr-cost)/dist;ex[k]=ix;break
   ix+=1
  if ex[k]<0 and ix<len(t) and t[ix]-cap<=72*3600*10**9:
   v[k]=(direction*(o[ix]-entry)-cost)/dist;ex[k]=ix
 return v,ex

def run(sym):
 a=time.time(); df=pd.read_csv(f'{IN}/{sym}_m1_from_ticks.csv',usecols=['timestamp','open','high','low','close','spread']);df['timestamp']=pd.to_datetime(df.timestamp,utc=True)
 df.sort_values('timestamp',inplace=True)
 k=df.set_index('timestamp');d=k.resample('D').agg(hi=('high','max'),lo=('low','min'),close=('close','last'),count=('close','count'))
 active=d.loc[d['count']>=500,['hi','lo','close']].copy()
 pc=active.close.shift(1);tr=pd.concat([active.hi-active.lo,(active.hi-pc).abs(),(active.lo-pc).abs()],axis=1).max(axis=1)
 d['ATR']=tr.rolling(14,min_periods=14).mean().shift(1).reindex(d.index).ffill()
 d.loc[d['count']<500,['hi','lo','close']]=np.nan
 d[['prior_hi','prior_lo']]=d[['hi','lo']].ffill().shift(1).set_axis(['prior_hi','prior_lo'],axis=1)
 d['date']=d.index
 dates=df.timestamp.dt.floor('D');groups=df.groupby(dates,sort=True).indices
 tm=df.timestamp.array.asi8;op=df.open.to_numpy();h=df.high.to_numpy();l=df.low.to_numpy();sp=df.spread.to_numpy()
 events=[]
 for at,locs in groups.items():
  if at not in d.index:continue
  row=d.loc[at];ah=float(row['prior_hi']);al=float(row['prior_lo']);atr=float(row['ATR'])
  if not (np.isfinite(ah) and np.isfinite(al) and np.isfinite(atr)) or atr<=0 or ah<=al:continue
  # Day opening must be between yesterday's levels (otherwise already broken at release).
  lo0=op[locs[0]]
  if not al<lo0<ah:continue
  for offset in (0.,.05,.1,.2):
   upp=ah+offset*atr;low=al-offset*atr
   # For BUY limit at ask <=low, require BID low + spread <=low.
   bt=np.flatnonzero(l[locs]+sp[locs]<=low)
   st=np.flatnonzero(h[locs]>=upp)
   if len(bt)==0 and len(st)==0:continue
   bi=bt[0] if len(bt) else len(locs)+1;si=st[0] if len(st) else len(locs)+1
   if bi==si:continue
   side=1 if bi<si else -1;idx=locs[min(bi,si)]
   # Reject gap-through: a resting limit is not modeled if candle starts beyond the threshold.
   if side==1 and op[idx]+sp[idx]<low:continue
   if side==-1 and op[idx]>upp:continue
   level=low if side==1 else upp
   events.append((at,offset,idx,side,level,atr))
 event=pd.DataFrame(events,columns=['date','offset','idx','side','level','atr'])
 print(sym,'eligible day events',len(event),'read secs',round(time.time()-a,1),flush=True)
 cost_com=0.07 if sym=='XAUUSD' else 0.00007;cost_slip=0.05 if sym=='XAUUSD' else 0.000005
 rows=[]
 for offset,group in event.groupby('offset'):
  e=group.idx.to_numpy(np.int64);side=group.side.to_numpy(np.int8);p=group.level.to_numpy(float);a=group.atr.to_numpy(float)
  for stop_a in (.15,.25,.4,.6):
   risk=a*stop_a
   for rr in (.5,.75,1.,1.5,2.):
    for hold in (8,24):
     v,ex=evaluate_event(tm,op,h,l,sp,e,side,p,risk,rr,hold,cost_com,cost_slip)
     selected=[];last=-1
     for i in range(len(e)):
      if e[i]<=last or ex[i]<0 or not np.isfinite(v[i]):continue
      selected.append(i);last=int(ex[i])
     if not selected:continue
     take=np.asarray(selected);vv=v[take];year=group.date.dt.year.to_numpy()[take]
     tr=vv[year<=2023];va=vv[(year>=2024)&(year<=2025)];q=vv[year>=2026]
     rows.append({'symbol':sym,'offset_dayATR':offset,'stop_dayATR':stop_a,'rr':rr,'holding_h':hold,
        'n_train':len(tr),'pf_train':calc_pf(tr),'win_train':round(100*(tr>0).mean(),1) if len(tr) else np.nan,
        'n_valid':len(va),'pf_valid':calc_pf(va),'win_valid':round(100*(va>0).mean(),1) if len(va) else np.nan,
        'n_2026q1':len(q),'pf_2026q1':calc_pf(q),'win_2026q1':round(100*(q>0).mean(),1) if len(q) else np.nan,
        'pf_all':calc_pf(vv),'win_all':round(100*(vv>0).mean(),1),
        'sum_R':round(float(np.sum(vv)),3)})
 out=pd.DataFrame(rows);out.to_csv(f'{OUT}/{sym}_exante_prior_day_levels.csv',index=False)
 print(sym,'configs',len(out),'best train PF',out.loc[out.n_train>=150,'pf_train'].max(),flush=True)
 print(out.query('n_train>=150').sort_values('pf_train',ascending=False).head(6).to_string(index=False),flush=True)
 gc.collect()
if __name__=='__main__':
 t=np.array([0,60*10**9,120*10**9],np.int64);x=np.array([10.,10.,10.]);evaluate_event(t,x,x+.1,x-.1,np.array([.02,.02,.02]),np.array([0]),np.array([1],np.int8),np.array([10.]),np.array([.1]),1.,1,.01,.001)
 for sym in ['XAUUSD','EURUSD']:run(sym)
