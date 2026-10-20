"""Scientific depth heatmap and optional local read-only replay slider."""
from pathlib import Path
import argparse, json
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.colors import LogNorm
ROOT=Path(__file__).resolve().parent

def heatmap(day, center_ms, window_minutes=120, interactive=False):
    x=np.load(ROOT/'derived'/f'{day}.npz')
    e=pd.read_csv(ROOT/'EVENT_LEDGER.csv')
    ts=x['ts']; q=x['quotes'];ht=x['heat_t'];h=x['heat'];edges=x['price_edges']
    mid=(q[:,0]+q[:,1])/2
    fig,(ax,of)=plt.subplots(2,1,figsize=(13,7.5),gridspec_kw={'height_ratios':[4,1]},sharex=True)
    fig.patch.set_facecolor('#101923')
    for a in (ax,of):
        a.set_facecolor('#101923');a.tick_params(colors='#c3d2df')
        a.yaxis.label.set_color('#c3d2df');a.xaxis.label.set_color('#c3d2df')
    scalar=plt.cm.ScalarMappable(norm=LogNorm(.1,1000),cmap='inferno')
    cbar=fig.colorbar(scalar,ax=[ax,of],fraction=.02,pad=.02)
    cbar.set_label('Displayed BTC / $10 bin',color='#c3d2df');cbar.ax.tick_params(colors='#c3d2df')
    def draw(center):
        ax.clear();of.clear()
        lo=center-window_minutes*30_000;hi=center+window_minutes*30_000
        mask=(ts>=lo)&(ts<=hi)&np.isfinite(mid)
        if not mask.any():return
        hm=(ht>=lo)&(ht<=hi)
        bottom=np.floor(mid[mask].min()/10)*10-30;top=np.ceil(mid[mask].max()/10)*10+30
        yi=(edges[:-1]>=bottom)&(edges[:-1]<=top)
        times=mdates.date2num(pd.to_datetime(ht[hm],unit='ms',utc=True).to_pydatetime())
        z=h[hm][:,yi].T
        # Actual resting BTC quantity in fixed $10 price bins, 30s snapshots.
        ax.pcolormesh(times,edges[:-1][yi]+5,np.maximum(z,.001),shading='nearest',cmap='inferno',norm=LogNorm(.1,1000),rasterized=True)
        t=pd.to_datetime(ts[mask],unit='ms',utc=True)
        ax.plot(t,mid[mask],color='#91f1ff',lw=1,label='Mid-price (1s samples)')
        ev=e[e.cohort.eq('exante_touch') & (e.mapped_ms>=lo) & (e.mapped_ms<=hi)]
        for row in ev.itertuples():
            a=pd.to_datetime(row.mapped_ms,unit='ms',utc=True);b=pd.to_datetime(row.mapped_ms+900000,unit='ms',utc=True)
            ax.plot([a,b],[row.level,row.level],color='#68e3a8' if row.side==1 else '#ff9ea5',lw=1.3,ls='--')
            if row.decision_ms<=hi:
                ax.scatter(pd.to_datetime(row.decision_ms,unit='ms',utc=True),row.level,
                           marker='^' if row.side==1 else 'v',s=35,color='#78f8aa' if row.imbalance_filter else '#f4f4f4',edgecolor='#101923')
        ax.set_ylim(bottom,top);ax.set_ylabel('BTCUSDT price (USDT)')
        ax.set_title('RIZAN L2 + REVERSAL ZONES | Bybit BTCUSDT | Historical research replay',color='#f0f4f8',loc='left',pad=14)
        ax.text(.01,.99,'Heat: resting BTC / $10 bin, every 30s | dashed: prior known 4h extreme | green marker: imbalance accepted',
                transform=ax.transAxes,color='#e1e6ec',fontsize=8,va='top')
        den=q[mask,2]+q[mask,3]
        imb=np.divide(q[mask,2]-q[mask,3],den,out=np.full(sum(mask),np.nan),where=den>0)
        of.plot(t,imb,color='#79c9ff',lw=.6)
        of.axhline(.2,color='#5fe3a5',ls='--',lw=.7);of.axhline(-.2,color='#ff8795',ls='--',lw=.7)
        of.set_ylim(-1,1);of.set_ylabel('5bp depth\nimbalance');of.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M',tz=__import__('datetime').timezone.utc))
        of.set_xlabel(f'{day} UTC | Public L2 only; no trade bubbles/CVD, no live orders')
        ax.legend(loc='lower left',fontsize=8,facecolor='#182735',labelcolor='white')
        for a in (ax,of):a.tick_params(colors='#c3d2df');a.yaxis.label.set_color('#c3d2df');a.xaxis.label.set_color('#c3d2df')
        fig.canvas.draw_idle()
    draw(center_ms)
    fig.subplots_adjust(left=.08,right=.82,bottom=.1,top=.90,hspace=.13)
    if interactive:
        from matplotlib.widgets import Slider
        fig.subplots_adjust(bottom=.18)
        slider_ax=fig.add_axes([.15,.05,.7,.025])
        slider=Slider(slider_ax,'UTC hour',0,23.99,valinit=(center_ms-ts[0])/3_600_000)
        slider.on_changed(lambda hour:draw(ts[0]+hour*3_600_000))
        plt.show()
    else:
        fig.savefig(ROOT/'HEATMAP_ZONE_REPLAY.png',dpi=160,facecolor=fig.get_facecolor())
        plt.close(fig)

def comparison():
    s=pd.read_csv(ROOT/'COMPARISON.csv')
    x=s[(s.split=='holdout')&(s.cost_multiplier==1)&s['filter'].isin(['baseline','imbalance'])].copy()
    fig,axes=plt.subplots(1,3,figsize=(13,4.8))
    labels=['Ex-ante touch','Repo H1 / M5','Sweep / reclaim'];cohorts=['exante_touch','repo_h1_m5','sweep_reclaim']
    for ax,key,title in zip(axes,['win_pct','mean_net_R','coverage_pct'],['Net win rate (%)','Mean net R per accepted event','Accepted opportunities (%)']):
        for k,f in enumerate(['baseline','imbalance']):
            vals=[x[(x.cohort==c)&(x['filter']==f)][key].iloc[0] for c in cohorts]
            bars=ax.bar(np.arange(3)+(k-.5)*.34,vals,width=.34,label='Baseline' if k==0 else 'L2 imbalance',color='#536d84' if k==0 else '#1a9e86')
            for bar,v in zip(bars,vals):ax.annotate(f'{v:.1f}' if key!='mean_net_R' else f'{v:.3f}',(bar.get_x()+bar.get_width()/2,v),ha='center',va='bottom' if v>=0 else 'top',fontsize=8)
        ax.set_xticks(np.arange(3),labels,rotation=18);ax.set_title(title,fontsize=10);ax.axhline(0,color='#999',lw=.5)
        ax.spines[['top','right']].set_visible(False)
    axes[0].legend(loc='upper right',fontsize=8)
    fig.suptitle('Diagnostic holdout: 6–8 January 2024 | BTCUSDT | 1× modeled costs',fontsize=13)
    fig.text(.02,.01,'Paired event study; small samples, overlapping observations. No demonstrated net-positive edge or XAU/EUR validation.',fontsize=9)
    fig.tight_layout(rect=[0,.04,1,.95]);fig.savefig(ROOT/'HOLDOUT_COMPARISON.png',dpi=160);plt.close(fig)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--interactive',action='store_true');parser.add_argument('--day',default='2024-01-06');args=parser.parse_args()
    e=pd.read_csv(ROOT/'EVENT_LEDGER.csv');sample=e[(e.cohort=='exante_touch')&(e.decision_utc.str.startswith(args.day))].iloc[0]
    heatmap(args.day,int(sample.decision_ms),interactive=args.interactive)
    if not args.interactive:comparison()
