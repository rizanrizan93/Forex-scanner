"""Tick-marked test equity for the five train/validation-chosen review cases."""
import sys,pathlib,json,numpy as np,pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'research_r1'))
from build_bars import load_ticks
from select_r2 import key
OUT=ROOT/'r2_results';FIG=ROOT/'r2_figures';FIG.mkdir(exist_ok=True)
cfg=json.loads((OUT/'review_configs.json').read_text());cm={key(c):c for c in cfg};t=pd.read_csv(OUT/'review_base_trades.csv.gz');cut=pd.Timestamp('2024-01-01',tz='Asia/Jakarta').timestamp()*1000;t=t[t.entry_ms>=cut]
curves={k:[(cut,10000.,0.)] for k in cm};peaks={k:10000. for k in cm}
for p in sorted((ROOT/'data').glob('XAUUSD_*.parquet')):
 if int(p.name[7:11])<2024:continue
 ts,bid,ask=load_ticks(p)
 for k,c in cm.items():
  for row in t[(t.candidate==k)&(t.entry_ms>=ts[0])&(t.entry_ms<=ts[-1])].itertuples():
   i=np.searchsorted(ts,row.entry_ms,side='left');islimit=c['family'] in ['HTF_FVG','R1_FVG_REF']
   while i<len(ts) and ts[i]==row.entry_ms:
    quote=ask[i] if row.side==1 else bid[i];ok=(row.side*(quote-row.entry)<=1e-9) if islimit else abs(quote+row.side*.1-row.entry)<1e-8
    if ok:break
    i+=1
   end=max(i,np.searchsorted(ts,row.exit_ms,side='left'))
   while end<len(ts) and ts[end]==row.exit_ms:
    quote=bid[end] if row.side==1 else ask[end];hit=row.side*(quote-row.sl)<=0 if row.exit_reason==1 else row.side*(quote-row.tp)>=0 if row.exit_reason==2 else True
    if hit:break
    end+=1
   before=row.balance-row.net_profit;curves[k].append((row.entry_ms-1,before,(peaks[k]-before)/peaks[k]))
   time=ts[i:end+1];q=bid[i:end+1] if row.side==1 else ask[i:end+1];eq=before-3*row.units_oz/100+row.side*(q-row.entry)*row.units_oz;eq[-1]=row.balance
   peak=np.maximum.accumulate(np.r_[peaks[k],eq])[1:];dd=(peak-eq)/peak;minute=time//60000;keep=np.unique(np.r_[0,np.where(np.diff(minute)!=0)[0],len(time)-1,np.argmax(eq),np.argmin(eq),np.argmax(dd)])
   curves[k]+=[(time[j],eq[j],dd[j]) for j in keep];peaks[k]=float(peak[-1])
 print(p.name,flush=True)
fig,axes=plt.subplots(2,1,figsize=(12,8),sharex=True,gridspec_kw={'height_ratios':[2,1]})
for k,rows in curves.items():
 end=pd.Timestamp('2026-03-31T13:00',tz='Asia/Jakarta').timestamp()*1000;rows.append((end,rows[-1][1],(peaks[k]-rows[-1][1])/peaks[k]));d=pd.DataFrame(rows,columns=['timestamp_ms','equity','floating_drawdown']);d['time_utc']=pd.to_datetime(d.timestamp_ms,unit='ms',utc=True);d.to_csv(OUT/(k+'_test_curve.csv.gz'),index=False)
 label=cm[k]['family']+('_NEWS' if cm[k].get('news')=='AFTER' else '')+('_YIELD' if cm[k].get('macro') else '')
 axes[0].plot(d.time_utc,d.equity,label=label,lw=1.25);axes[1].plot(d.time_utc,-100*d.floating_drawdown,lw=1.1)
axes[0].axhline(10000,color='#777',lw=.7);axes[0].set_ylabel('Marked equity (USD)');axes[1].set_ylabel('Floating drawdown (%)');axes[0].set_title('RIZAN Asia R2 — historical TEST Jan 2024–Mar 2026\nFive diagnostic cases; none passes the required discovery/validation gate');axes[0].legend(fontsize=8,ncol=2)
for a in axes:a.grid(alpha=.2)
fig.autofmt_xdate();fig.tight_layout();fig.savefig(FIG/'test_equity_drawdown.png',dpi=150);plt.close(fig)
