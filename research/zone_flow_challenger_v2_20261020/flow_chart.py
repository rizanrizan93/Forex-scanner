"""Show the first chronologically observed absorption proxy, never the best PnL."""
from pathlib import Path
import numpy as np,pandas as pd,matplotlib.pyplot as plt,matplotlib.dates as mdates
from challenger import load_day,flow_arrays
ROOT=Path(__file__).resolve().parent

def main():
    obs=pd.read_csv(ROOT/'ORDERFLOW_EVIDENCE.csv')
    accepted=obs[obs.signal_ms.notna()].sort_values(['signal_ms','event_id'])
    if accepted.empty:return
    h1=accepted[accepted.family.eq('H1_SD')]
    e=(h1 if len(h1) else accepted).iloc[0]
    raw,t,q,mid,bars=load_day(e.day);flow=flow_arrays(e.day,t)
    lo=e.touch_ms-300_000;hi=e.signal_ms+1_200_000;mask=(t>=lo)&(t<=hi)
    dates=pd.to_datetime(t[mask],unit='ms',utc=True)
    fig,axes=plt.subplots(3,1,figsize=(12,8),sharex=True,gridspec_kw={'height_ratios':[3,1.4,1.4]})
    ax=axes[0];ax.plot(dates,mid[mask],c='#286c9b',lw=1,label='Mid-price,1s')
    ax.axhspan(e.low,e.high,color='#77b8a3',alpha=.25,label='Zone known before touch')
    ax.axhline(e.stop,c='#b7414b',ls='--',label='Locked invalidation')
    for ms,label,c in [(e.touch_ms,'First touch','#444'),(e.signal_ms,'Absorption proxy','#008765')]:
        ax.axvline(pd.to_datetime(ms,unit='ms',utc=True),c=c,ls=':',label=label)
    if pd.notna(e.reclaim_ms):ax.axvline(pd.to_datetime(e.reclaim_ms,unit='ms',utc=True),c='#9e6b12',ls=':',label='Closed-M1 reclaim')
    ax.set_ylabel('USDT');ax.legend(fontsize=8,loc='best');ax.set_title(f'Actual tape + L2 | {e.day} | {e.family} | '+('BUY' if e.side==1 else 'SELL'),loc='left')
    counter=flow['sell15'] if e.side==1 else flow['buy15'];p75=flow['sell_p75'] if e.side==1 else flow['buy_p75']
    axes[1].plot(dates,counter[mask]/1e6,label='Counter-side taker flow,15s',c='#ac4855')
    axes[1].plot(dates,p75[mask]/1e6,label='Prior30min p75',c='#666',ls='--');axes[1].set_ylabel('USDT million');axes[1].legend(fontsize=8)
    cvd=(flow['buy15']-flow['sell15'])/(flow['buy15']+flow['sell15']+1e-12)
    den=q[:,2]+q[:,3];imb=np.divide(q[:,2]-q[:,3],den,out=np.full(len(t),np.nan),where=den>0)
    axes[2].plot(dates,cvd[mask],c='#6a53a4',label='Aggressor imbalance,15s')
    axes[2].plot(dates,imb[mask],c='#259d86',alpha=.6,lw=.7,label='Resting depth imbalance,5bp')
    axes[2].set_ylim(-1,1);axes[2].legend(fontsize=8);axes[2].set_xlabel('UTC — data after marker is shown for review, never used before decision')
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M',tz=__import__('datetime').timezone.utc))
    for a in axes:a.spines[['top','right']].set_visible(False)
    fig.tight_layout();fig.savefig(ROOT/'ACTUAL_TAPE_ZONE_EXAMPLE.png',dpi=150);plt.close(fig)
    (ROOT/'CHART_SELECTION.txt').write_text('First chronologically observed H1 absorption proxy, fallback first control if no H1. No selection by PnL.\n'+e.event_id+'\n')

if __name__=='__main__':main()
