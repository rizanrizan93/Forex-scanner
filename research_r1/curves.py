"""Minute marks plus exact per-trade extrema, using original quote paths."""
import pathlib,json,numpy as np,pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
from build_bars import load_ticks
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'results';FIG=ROOT/'figures';FIG.mkdir(exist_ok=True)
t=pd.read_csv(OUT/'BASE_PERIODS/trades.csv.gz');ids=[f'{setup}_{session}_R{r}' for session,setup,r in json.loads((OUT/'selected_configs.json').read_text())]
cut=pd.Timestamp('2024-01-01',tz='Asia/Jakarta').timestamp()*1000;t=t[(t.candidate.isin(ids))&(t.entry_ms>=cut)]
curves={key:[(cut,10000.,0.)] for key in ids};peaks={key:10000. for key in ids}
for p in sorted((ROOT/'data').glob('XAUUSD_*.parquet')):
 if int(p.name[7:11])<2024:continue
 ts,bid,ask=load_ticks(p)
 for key in ids:
  q=t[(t.candidate==key)&(t.entry_ms>=ts[0])&(t.entry_ms<=ts[-1])]
  for row in q.itertuples():
   i=np.searchsorted(ts,row.entry_ms,side='left')
   limit_order=key.startswith('TREND_FVG') or key.startswith('SWEEP_MSS_FVG')
   while i<len(ts) and ts[i]==row.entry_ms:
    entry_quote=ask[i] if row.side==1 else bid[i]
    ok=(row.side*(entry_quote-row.entry)<=1e-9) if limit_order else abs(entry_quote+row.side*.1-row.entry)<1e-8
    if ok:break
    i+=1
   exit_index=max(i,np.searchsorted(ts,row.exit_ms,side='left'))
   while exit_index<len(ts) and ts[exit_index]==row.exit_ms:
    exit_quote=bid[exit_index] if row.side==1 else ask[exit_index]
    if row.exit_reason==1:trigger=row.side*(exit_quote-row.sl)<=0
    elif row.exit_reason==2:trigger=row.side*(exit_quote-row.tp)>=0
    else:trigger=True
    if trigger:break
    exit_index+=1
   j=exit_index+1;time=ts[i:j]
   if not len(time):continue
   quote=bid[i:j] if row.side==1 else ask[i:j]
   before=row.balance-row.net_profit;eq=before-3*row.units_oz/100+row.side*(quote-row.entry)*row.units_oz
   eq[-1]=row.balance
   peak=np.maximum.accumulate(np.r_[peaks[key],eq])[1:];dd=(peak-eq)/peak
   minute=time//60000;keep=np.r_[np.where(np.diff(minute)!=0)[0],len(time)-1,np.argmax(eq),np.argmin(eq),np.argmax(dd)]
   for k in np.unique(keep):curves[key].append((time[k],eq[k],dd[k]))
   peaks[key]=float(peak[-1])
 print(p.name,flush=True)
fig,ax=plt.subplots(2,1,figsize=(12,8),sharex=True,gridspec_kw={'height_ratios':[2,1]})
for key,rows in curves.items():
 rows.append((pd.Timestamp('2026-03-31T13:00:00',tz='Asia/Jakarta').timestamp()*1000,rows[-1][1],(peaks[key]-rows[-1][1])/peaks[key]))
 c=pd.DataFrame(rows,columns=['timestamp_ms','equity','floating_drawdown']);c['time_utc']=pd.to_datetime(c.timestamp_ms,unit='ms',utc=True);c.to_csv(OUT/(key+'_oos_curve.csv.gz'),index=False)
 label=key.split('_ASIA_FULL_')[0];ax[0].plot(c.time_utc,c.equity,label=label,lw=1.2);ax[1].plot(c.time_utc,-100*c.floating_drawdown,lw=1.)
ax[0].axhline(10000,color='#888',lw=.7);ax[0].set_ylabel('Marked equity (USD)');ax[1].set_ylabel('Floating drawdown (%)');ax[0].set_title('RIZAN R1 — independently funded historical test, Jan 2024–Mar 2026\nDukascopy archive, modeled Raw costs, USD 10,000 start / USD 50 fixed risk budget')
for a in ax:a.grid(alpha=.2)
ax[0].legend(ncol=2,fontsize=9);fig.autofmt_xdate();fig.tight_layout();fig.savefig(FIG/'oos_equity_drawdown.png',dpi=160);plt.close(fig)
# Historical intraday profile, not an optimized trading recommendation.
h=pd.read_csv(OUT/'hourly_summary.csv');fig,ax=plt.subplots(figsize=(11,4));ax.bar(h.hour_wib,h.mean_range,color='#be9153');ax.set_xticks(range(24));ax.set_xlabel('Hour WIB');ax.set_ylabel('Mean high–low range (USD/oz)');ax.set_title('XAUUSD hourly range, Jan 2019–Mar 2026 — range does not equal expectancy');ax.grid(axis='y',alpha=.2);fig.tight_layout();fig.savefig(FIG/'hourly_range.png',dpi=160);plt.close(fig)
