"""Closed-bar outcome statistics. Not used to choose or time historical entries."""
import pathlib,numpy as np,pandas as pd
from signals import SESSIONS
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'results'
b=pd.read_parquet(ROOT/'derived/xau_m5.parquet');w=b.index.tz_convert('Asia/Jakarta');b['date']=w.strftime('%Y-%m-%d');b['minute']=w.hour*60+w.minute
daily=pd.read_csv(OUT/'session_daily_stats.csv');ny=daily[daily.session=='NY_COMPARATOR'].set_index('date').sort_index();records=[]
for session,(start,end) in SESSIONS.items():
 for day,f in b[(b.minute>=start)&(b.minute<end)].groupby('date'):
  f=f.dropna(subset=['close']);first=f[f.minute<start+30];later=f[f.minute>=start+30]
  if len(first)!=6 or len(f)<.9*(end-start)/5:continue
  hi=float(first.high.max());lo=float(first.low.min());ran=hi-lo
  if ran<=0:continue
  br=np.where((later.close>hi+.05*ran)|(later.close<lo-.05*ran))[0]
  result='NO_BREAKOUT';side=0
  if len(br):
   k=int(br[0]);side=1 if later.close.iloc[k]>hi else -1;path=later.close.iloc[k+1:].to_numpy();result='UNRESOLVED'
   for price in path:
    if (side==1 and price>=hi+.5*ran) or (side==-1 and price<=lo-.5*ran):result='CONTINUATION';break
    if (side==1 and price<hi) or (side==-1 and price>lo):result='FALSE_BREAKOUT';break
  up_sweep=bool(((later.high>hi+.05*ran)&(later.close<hi)).any());down_sweep=bool(((later.low<lo-.05*ran)&(later.close>lo)).any())
  prior=ny[ny.index<day];r={'session':session,'date':day,'breakout_outcome':result,'breakout_side':side,'opening_high_sweep':up_sweep,'opening_low_sweep':down_sweep,'previous_ny_high_sweep':None,'previous_ny_low_sweep':None}
  if len(prior):
   p=prior.iloc[-1];r['previous_ny_high_sweep']=bool(f.high.max()>p.high and f.close.iloc[-1]<p.high);r['previous_ny_low_sweep']=bool(f.low.min()<p.low and f.close.iloc[-1]>p.low)
  records.append(r)
d=pd.DataFrame(records);d.to_csv(OUT/'liquidity_daily_stats.csv',index=False)
summ=[]
for s,g in d.groupby('session'):
 events=g[g.breakout_outcome!='NO_BREAKOUT'];resolved=events[events.breakout_outcome!='UNRESOLVED']
 summ.append({'session':s,'days':len(g),'breakout_days':len(events),'continuations':int((events.breakout_outcome=='CONTINUATION').sum()),'false_breakouts':int((events.breakout_outcome=='FALSE_BREAKOUT').sum()),'unresolved':int((events.breakout_outcome=='UNRESOLVED').sum()),'continuation_given_resolved':float((resolved.breakout_outcome=='CONTINUATION').mean()) if len(resolved) else None,'opening_high_sweep_frequency':float(g.opening_high_sweep.mean()),'opening_low_sweep_frequency':float(g.opening_low_sweep.mean()),'previous_ny_high_sweep_frequency':float(g.previous_ny_high_sweep.mean()),'previous_ny_low_sweep_frequency':float(g.previous_ny_low_sweep.mean())})
pd.DataFrame(summ).to_csv(OUT/'liquidity_summary.csv',index=False)
