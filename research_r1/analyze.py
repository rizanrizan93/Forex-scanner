import pathlib,json,numpy as np,pandas as pd
from signals import SETUPS,SESSIONS
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'results';OUT.mkdir(exist_ok=True)
def prepared(t):
 t=t.copy();t['entry_time']=pd.to_datetime(t.entry_ms,unit='ms',utc=True).dt.tz_convert('Asia/Jakarta');t['year']=t.entry_time.dt.year;t['month']=t.entry_time.dt.strftime('%Y-%m');t['day']=t.entry_time.dt.strftime('%Y-%m-%d');return t
def floating_dd(t,initial):
 peak=initial;dd=0.
 for row in t.itertuples():
  dd=max(dd,float(row.local_floating_dd),(peak-float(row.intra_low_equity))/peak)
  peak=max(peak,float(row.intra_peak_equity),float(row.balance))
 return max(0.,dd)
def metrics(t,initial=10000.,months=None):
 if not len(t):return {'starting_equity':initial,'ending_equity':initial,'net_profit':0.,'trades':0}
 # Translate subset equity back to its own starting point only for USD fixed-risk reporting.
 t=t.copy();offset=initial-(t.balance.iloc[0]-t.net_profit.iloc[0]);t['balance']+=offset;t['intra_peak_equity']+=offset;t['intra_low_equity']+=offset
 # local DD denominator is tied to the original account and is exact only when offset is zero.
 # Re-express local USD drawdown with the translated local equity peak.
 t['local_floating_dd']=t.local_floating_dd*(t.intra_peak_equity-offset)/t.intra_peak_equity
 pnl=t.net_profit.to_numpy();eq=np.r_[initial,t.balance.to_numpy()];peak=np.maximum.accumulate(eq);closed=float(np.max((peak-eq)/peak))
 dd=floating_dd(t,initial);wins=float(pnl[pnl>0].sum());loss=float(-pnl[pnl<0].sum());streak=0;longest=0
 for x in pnl:
  streak=streak+1 if x<0 else 0;longest=max(longest,streak)
 m=t.groupby('month').net_profit.sum()
 duration=months if months is not None else max(1,t.month.nunique())
 return {'starting_equity':initial,'ending_equity':float(eq[-1]),'net_profit':float(pnl.sum()),'profit_factor':wins/loss if loss else np.nan,'win_rate':float((pnl>0).mean()),'expectancy_usd':float(pnl.mean()),'trades':len(t),'trades_per_month':len(t)/duration,'closed_balance_dd':closed,'floating_equity_dd':dd,'return_over_dd':(float(pnl.sum())/initial)/dd if dd else np.nan,'worst_month':str(m.idxmin()),'worst_month_profit':float(m.min()),'longest_losing_streak':longest,'incomplete_exit_count':int((t.exit_reason==4).sum()),'held_gap_gt5m_count':int((t.max_gap_ms>300000).sum())}
def initial_of(t,default=10000.):return float(t.balance.iloc[0]-t.net_profit.iloc[0]) if len(t) else default
def bootstrap(t,n=3000):
 # Five-trading-day circular moving blocks, including zero-trade weekdays.
 if not len(t):return {}
 dates=pd.bdate_range(t.entry_time.min().date(),t.entry_time.max().date());daily=t.groupby('day').agg(pnl=('net_profit','sum'),trades=('net_profit','size')).reindex(dates.strftime('%Y-%m-%d'),fill_value=0)
 a=daily.to_numpy();rng=np.random.default_rng(125);stats=[]
 for _ in range(n):
  starts=rng.integers(0,len(a),size=int(np.ceil(len(a)/5)));ix=((starts[:,None]+np.arange(5))%len(a)).ravel()[:len(a)];v=a[ix].sum(axis=0)
  if v[1]:stats.append(v[0]/v[1])
 observed=t.net_profit.mean();stats=np.array(stats);p=float((np.sum(stats-observed>=observed)+1)/(len(stats)+1))
 return {'expectancy_usd':float(observed),'ci95_low':float(np.quantile(stats,.025)),'ci95_high':float(np.quantile(stats,.975)),'one_sided_centered_bootstrap_p':p,'prob_expectancy_positive':float((stats>0).mean()),'replicates':len(stats),'block_trading_days':5}
def main():
 t=prepared(pd.read_csv(OUT/'BASE/trades.csv.gz'));split=prepared(pd.read_csv(OUT/'BASE_PERIODS/trades.csv.gz'));reset=prepared(pd.read_csv(OUT/'BASE_ANNUAL/trades.csv.gz'));records=[];annual=[];period=[]
 months={'TRAIN':36,'VALIDATION':24,'OOS':27,'ALL':87}
 for key,g in t.groupby('candidate'):
  records.append({'candidate':key,**metrics(g,months=87)})
  for year in range(2019,2027):
   q=reset[(reset.candidate==key)&(reset.year==year)];annual.append({'candidate':key,'year':str(year)+(' YTD to March' if year==2026 else ''),'coverage_months':3 if year==2026 else 12,**metrics(q,10000.,3 if year==2026 else 12)})
  g=split[split.candidate==key]
  for label,mask in [('TRAIN',g.year<=2021),('VALIDATION',(g.year>=2022)&(g.year<=2023)),('OOS',g.year>=2024)]:
   q=g[mask];period.append({'candidate':key,'period':label,**metrics(q,10000.,months[label])})
 pd.DataFrame(records).to_csv(OUT/'all_candidates.csv',index=False);pd.DataFrame(annual).to_csv(OUT/'annual_all_candidates.csv',index=False);pd.DataFrame(period).to_csv(OUT/'period_metrics.csv',index=False)
 p=pd.DataFrame(period);selected=[];configs=[]
 for session in SESSIONS:
  for setup in SETUPS:
   f=p[(p.period=='TRAIN')&p.candidate.str.startswith(setup+'_'+session+'_')&(p.trades>=50)].sort_values(['expectancy_usd','profit_factor'],ascending=False)
   key=f.iloc[0].candidate if len(f) else setup+'_'+session+'_R2.0';target=float(key.rsplit('_R',1)[1]);selected.append(key)
   if session=='ASIA_FULL':configs.append((session,setup,target))
 (OUT/'selected_configs.json').write_text(json.dumps(configs,indent=2));(OUT/'selected_ids.json').write_text(json.dumps(selected,indent=2))
 p[p.candidate.isin(selected)].to_csv(OUT/'selected_period_metrics.csv',index=False)
 # Walk-forward TP selection uses the preceding three full years only.
 wf=[]
 for year in range(2022,2027):
  for session in SESSIONS:
   for setup in SETUPS:
    groups=[]
    for key,g in reset[reset.candidate.str.startswith(setup+'_'+session+'_')].groupby('candidate'):
     train=g[(g.year>=year-3)&(g.year<year)]
     if len(train)>=50:groups.append((float(train.net_profit.mean()),key))
    if groups:
     key=max(groups)[1];q=reset[(reset.candidate==key)&(reset.year==year)];wf.append({'year':year,'candidate':key,'session':session,'setup':setup,**metrics(q,10000.,3 if year==2026 else 12)})
 pd.DataFrame(wf).to_csv(OUT/'walk_forward.csv',index=False)
 boots=[]
 for key in selected:
  if '_ASIA_FULL_' in key:boots.append({'candidate':key,**bootstrap(split[(split.candidate==key)&(split.year>=2024)])})
 b=pd.DataFrame(boots)
 if len(b):
  order=np.argsort(b.one_sided_centered_bootstrap_p.fillna(1).to_numpy());adj=np.zeros(len(b));prior=0
  for rank,i in enumerate(order):prior=max(prior,min(1.,float(b.iloc[i].one_sided_centered_bootstrap_p)*(len(b)-rank)));adj[i]=prior
  b['holm_p_5_asia_setups']=adj
 b.to_csv(OUT/'oos_block_bootstrap.csv',index=False)
 # Hour-of-entry net expectancy is descriptive; it must not select a new deployable strategy on test data.
 q=split[split.candidate.isin(selected)&split.candidate.str.contains('_ASIA_FULL_')].copy();q['hour_wib']=q.entry_time.dt.hour
 q.groupby(['candidate','year','hour_wib']).net_profit.agg(['count','mean','sum']).to_csv(OUT/'entry_hour_profit.csv')
 print(pd.DataFrame(records).sort_values('net_profit',ascending=False).head(8).to_string(index=False))
 print('Selected full Asia',configs)
if __name__=='__main__':main()
