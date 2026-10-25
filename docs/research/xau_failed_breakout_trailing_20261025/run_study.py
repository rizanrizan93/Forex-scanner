"""Reproducible, closed-bar failed-breakout research. No execution APIs."""
from pathlib import Path
import argparse, hashlib, itertools, json, time
import numpy as np
import pandas as pd
from numba import njit

P=Path(__file__).resolve().parent
SPLIT=pd.Timestamp('2023-01-01',tz='UTC').timestamp()
REVIEW_END=pd.Timestamp('2026-01-01',tz='UTC').timestamp()

def prepare(path):
    df=pd.read_csv(path,usecols=['timestamp','open','high','low','close','spread'])
    df.index=pd.to_datetime(df.pop('timestamp'),utc=True)
    ts=df.index.astype('int64').to_numpy()//10**9
    prices=np.column_stack([ts,df[['open','high','low','close','spread']].to_numpy()])
    assert np.all(np.diff(ts)>0) and np.isfinite(prices).all()
    assert (df.spread>=0).all() and (df.high>=df.low).all()
    def bars(freq):
        b=df.resample(freq,closed='left',label='left').agg(
            {'open':'first','high':'max','low':'min','close':'last','spread':'count'})
        b=b.rename(columns={'spread':'count'}).dropna()
        tr=pd.concat([b.high-b.low,(b.high-b.close.shift()).abs(),
                      (b.low-b.close.shift()).abs()],axis=1).max(axis=1)
        b['atr']=tr.rolling(14,min_periods=14).mean()
        return b
    d=bars('1D'); e=d.close.ewm(span=20,adjust=False).mean()
    d['regime']=np.where((d.close>e)&(e>e.shift(5)),1,
                         np.where((d.close<e)&(e<e.shift(5)),-1,0))
    d.loc[d.index[:40],'regime']=9
    dc=d.copy();dc.index+=pd.Timedelta(days=1)
    hourly=bars('1h');hourly.index+=pd.Timedelta(hours=1)
    w=bars('W-MON') # pandas label/closed specified left: Monday starts
    signals=[]
    for minutes in (5,15):
        b=bars(f'{minutes}min'); close_clock=b.index+pd.Timedelta(minutes=minutes)
        ht=hourly.atr.reindex(close_clock,method='ffill').to_numpy()
        regime=dc.regime.reindex(close_clock,method='ffill').fillna(9).to_numpy()
        daykey=b.index.normalize()-pd.Timedelta(days=1)
        weekkey=b.index.normalize()-pd.to_timedelta(b.index.dayofweek,unit='D')-pd.Timedelta(days=7)
        for levname,ref,key,mincount in [('day',d,daykey,500),('week',w,weekkey,2000)]:
            levels=ref.reindex(key)
            hi,lo=levels.high.to_numpy(),levels.low.to_numpy()
            valid=levels['count'].fillna(0).to_numpy()>=mincount
            bo,bh,bl,bc,atr=[b[x].to_numpy() for x in ['open','high','low','close','atr']]
            count=b['count'].to_numpy()
            bt=close_clock.astype('int64').to_numpy()//10**9
            for window,confirm in itertools.product((1,3),(0,1)):
                out=[]
                for side in (1,-1):
                    last=-1
                    for k in range(3,len(b)-4):
                        if k<=last or not valid[k] or regime[k]==9 or not np.isfinite(atr[k]+ht[k]):continue
                        if (count[k-3:k+1]!=minutes).any():continue
                        level=lo[k] if side==1 else hi[k]
                        sweep=bl[k]<level if side==1 else bh[k]>level
                        if not sweep:continue
                        # Require approach from inside, rather than repeated sweeps from outside.
                        if side*(bc[k-1]-level)<0:continue
                        cross=bh[k-3:k].max() if side==1 else bl[k-3:k].min()
                        reclaimed=-1
                        for j in range(k,k+window):
                            if bt[j]-bt[k]!=(j-k)*minutes*60 or count[j]!=minutes:break
                            if side*(bc[j]-level)>0:reclaimed=j;break
                        if reclaimed<0:continue
                        trigger=reclaimed
                        if confirm:
                            trigger=-1
                            for j in range(reclaimed+1,reclaimed+4):
                                if bt[j]-bt[k]!=(j-k)*minutes*60 or count[j]!=minutes:break
                                if side*(bc[j]-level)<=0:break
                                if side*(bc[j]-cross)>0:trigger=j;break
                            if trigger<0:continue
                        extreme=bl[k:trigger+1].min() if side==1 else bh[k:trigger+1].max()
                        stop=extreme-side*.1*atr[trigger]
                        i=int(np.searchsorted(ts,bt[trigger]))
                        if i>=len(ts) or ts[i]-bt[trigger]>60:continue
                        out.append((i,side,level,stop,ht[trigger],regime[trigger],bt[trigger]))
                        last=trigger
                out.sort(key=lambda r:(r[0],-r[1]))
                name=f'{levname}_M{minutes}_reclaim{window}_structure{confirm}'
                signals.append((name,np.array(out,dtype=np.float64).reshape(-1,7)))
    # Retrospective coverage mask, not a trading feature. Exclude sparse long breaks.
    bad=np.r_[0,np.cumsum(np.diff(ts)>72*3600)].astype(np.int64)
    return prices,signals,bad

@njit(cache=True)
def replay(p,sigs,bad,entrymode,cap,trailkind,activation,hold,aligned,cost=1.,delay=0,trainonly=False):
    # columns: entry_i exit_i side entry exit originalSL netUSD R MFE regime reason signal_clock
    rows=np.zeros((len(sigs),12));n=0;busy=-1;end=len(p)
    for q in range(len(sigs)):
        sig=sigs[q];a=int(sig[0]);side=int(sig[1]);level=sig[2];sl=sig[3];at=sig[4];reg=int(sig[5]);clock=sig[6]
        if trainonly and clock>=SPLIT:break
        if aligned and reg!=side:continue
        if a<=busy:continue
        if a<24000 or bad[a]!=bad[a-24000]:continue
        j=a
        if entrymode==1:
            # Original first touch is final: no re-credit on a later retouch.
            while j<end and p[j,0]-clock<=3600:
                hit=p[j,3]+cost*p[j,5]<=level if side==1 else p[j,2]>=level
                if hit:break
                j+=1
            if j>=end or p[j,0]-clock>3600 or p[j,0]<clock+delay:continue
            ep=level
        else:
            while j<end and p[j,0]<clock+delay:j+=1
            if j>=end or p[j,0]-clock-delay>60:continue
            ep=p[j,1]+(cost*p[j,5] if side==1 else 0.)
        if j<=busy:continue
        # Stop for short is expressed on ask, hence costs are part of short risk.
        origsl=sl+(cost*p[j,5] if side==-1 else 0.)
        risk=side*(ep-origsl)
        if risk<1 or risk>cap:continue
        t=p[j,0]
        if (t<SPLIT and t>SPLIT-72*3600) or (t<REVIEW_END and t>REVIEW_END-72*3600):continue
        last=j
        while last<end and p[last,0]<t+hold*3600:last+=1
        if last>=end:continue
        if bad[last]!=bad[j]:continue
        stop=origsl;water=ep;mfe=0.;reason=0;px=ep;k=j
        for k in range(j,last+1):
            op=p[k,1]+(cost*p[k,5] if side==-1 else 0.)
            adverse=p[k,3] if side==1 else p[k,2]+cost*p[k,5]
            if side*(adverse-stop)<=0:
                px=min(stop,op) if side==1 else max(stop,op)
                reason=1;break
            if k==last:px=op;reason=2;break
            # Limit fill bar intraminute ordering unknown: grant no favorable excursion.
            if k==j and entrymode==1:continue
            fav=p[k,2] if side==1 else p[k,3]+cost*p[k,5]
            water=max(water,fav) if side==1 else min(water,fav)
            mfe=max(mfe,side*(water-ep))
            threshold=activation if activation>=0 else -activation*risk
            if mfe>=threshold:
                dist=5. if trailkind==0 else (10. if trailkind==1 else (15. if trailkind==2 else (at if trailkind==3 else (2*at if trailkind==4 else (.75*risk if trailkind==5 else (1.5*risk if trailkind==6 else 2.5*risk))))))
                proposed=water-side*dist
                # Valid only on next bar; avoid placing a stop across current executable quote.
                quote=p[k,4]+(cost*p[k,5] if side==-1 else 0.)
                proposed=min(proposed,quote-.01) if side==1 else max(proposed,quote+.01)
                stop=max(stop,proposed) if side==1 else min(stop,proposed)
        net=side*(px-ep)-.17*cost-.1*(p[k,0]-t)/86400
        rows[n]=np.array([j,k,side,ep,px,origsl,net,net/risk,mfe,reg,reason,clock])
        n+=1;busy=k
    return rows[:n]

def stats(r):
    if len(r)==0:return {'n':0,'win_pct':0.,'pf':0.,'net_R':0.,'net_usd_per_oz':0.}
    v=r[:,7];loss=-v[v<0].sum();cum=np.r_[0,np.cumsum(v)]
    usd=r[:,6];usd_loss=-usd[usd<0].sum()
    streak=mx=0
    for x in v:streak=streak+1 if x<0 else 0;mx=max(mx,streak)
    return dict(n=len(r),win_pct=float(100*(v>0).mean()),pf=float(v[v>0].sum()/loss) if loss else 999.,
        pf_equal_oz=float(usd[usd>0].sum()/usd_loss) if usd_loss else 999.,
        net_R=float(v.sum()),net_usd_per_oz=float(r[:,6].sum()),
        mean_risk=float(np.mean(abs(r[:,3]-r[:,5]))),net_ge25_pct=float(100*(r[:,6]>=25).mean()),
        mfe_ge25_pct=float(100*(r[:,8]>=25).mean()),max_R_drawdown=float(np.max(np.maximum.accumulate(cum)-cum)),
        max_consecutive_losses=mx,median_net_usd_per_oz=float(np.median(r[:,6])))

def describe(p,r):
    entry=p[r[:,0].astype(int),0] if len(r) else np.array([])
    tr=r[entry<SPLIT];rv=r[(entry>=SPLIT)&(entry<REVIEW_END)];q=r[entry>=REVIEW_END]
    result={'all':stats(r),'train':stats(tr),'review':stats(rv),'q1_2026':stats(q)}
    for label,x in [('train',tr),('review',rv),('q1',q)]:
        result[label+'_sides']={str(z):stats(x[x[:,2]==z]) for z in (1,-1)}
        result[label+'_regimes']={str(z):stats(x[x[:,9]==z]) for z in (1,0,-1)}
    years=pd.to_datetime(entry,unit='s',utc=True).year.to_numpy()
    result['annual']={str(y):stats(r[years==y]) for y in np.unique(years)}
    return result

def main():
    global P
    ap=argparse.ArgumentParser();ap.add_argument('data');ap.add_argument('--phase',type=int,default=1);args=ap.parse_args()
    if args.phase==2:P=P/'phase2';P.mkdir(exist_ok=True)
    started=time.time();p,groups,bad=prepare(args.data)
    print('Prepared',len(p),'bars',sum(len(s) for _,s in groups),'signals',flush=True)
    grid=[]
    for gi,(name,s) in enumerate(groups):
        kinds=range(8) if args.phase==2 else range(5)
        acts=(0,5,10,25,-.5,-1,-2) if args.phase==2 else (10,25)
        for entry,cap,trail,act,hold,align in itertools.product((0,1),(10,15,20),kinds,acts,(24,72),(0,1)):
            cfg=dict(group=gi,family=name,entrymode=entry,cap=cap,trailkind=trail,activation=act,hold=hold,aligned=align)
            r=replay(p,s,bad,entry,cap,trail,act,hold,align,trainonly=True)
            a=stats(r);b=stats(r[r[:,2]==1]);c=stats(r[r[:,2]==-1])
            qualified=a['n']>=60 and min(b['n'],c['n'])>=20 and a['pf']>=1.5 and a['win_pct']>=50 and min(b['pf'],c['pf'])>=1.2
            grid.append({**cfg,**{'train_'+k:v for k,v in a.items()},'buy_n':b['n'],'sell_n':c['n'],
                         'min_side_pf':min(b['pf'],c['pf']),'qualified':qualified})
        print('Train group',gi+1,'/',len(groups),'elapsed',round(time.time()-started),flush=True)
    grid=pd.DataFrame(grid);grid.to_csv(P/'TRAIN_GRID.csv',index=False)
    eligible=grid[grid.qualified]
    if eligible.empty:eligible=grid[(grid.train_n>=60)&(grid.buy_n>=20)&(grid.sell_n>=20)]
    if eligible.empty:raise RuntimeError('No adequate two-sided sample')
    ranked=eligible.sort_values(['min_side_pf','train_pf','train_n'],ascending=False).head(10)
    ranked.to_csv(P/'TRAIN_FROZEN_TOP10.csv',index=False)
    cfgkeys=['group','entrymode','cap','trailkind','activation','hold','aligned']
    frozen={k:float(ranked.iloc[0][k]) if k=='activation' else int(ranked.iloc[0][k]) for k in cfgkeys}
    frozen['family']=ranked.iloc[0].family
    (P/'FROZEN_CONFIG.json').write_text(json.dumps(frozen,indent=2))
    print('FROZEN BEFORE REVIEW',frozen,flush=True)
    results=[]
    for rank,row in enumerate(ranked.itertuples()):
        cfg={k:float(getattr(row,k)) if k=='activation' else int(getattr(row,k)) for k in cfgkeys};s=groups[cfg['group']][1]
        a=[cfg[k] for k in cfgkeys if k!='group'];r=replay(p,s,bad,*a)
        desc=describe(p,r);results.append({'rank':rank+1,'config':cfg,'metrics':desc})
        if rank==0:
            cols=['entry_i','exit_i','side','entry','exit','original_sl','net_usd_per_oz','net_R','MFE','regime','reason','signal_clock']
            ledger=pd.DataFrame(r,columns=cols)
            for col,idx in [('entry_utc',0),('exit_utc',1)]:ledger[col]=pd.to_datetime(p[r[:,idx].astype(int),0],unit='s',utc=True)
            ledger.to_csv(P/'FROZEN_LEDGER.csv',index=False)
            variants={}
            for cost,delay in [(1,0),(2,0),(1,60),(1,300)]:
                v=replay(p,s,bad,*a,cost=cost,delay=delay);variants[f'cost{cost}_delay{delay}']=describe(p,v)
            (P/'FROZEN_RESULTS.json').write_text(json.dumps(variants,indent=2))
            print('Frozen result',json.dumps(desc),flush=True)
    (P/'TOP10_REVIEW.json').write_text(json.dumps(results,indent=2))
    (P/'DATA.json').write_text(json.dumps({'source_sha256':hashlib.sha256(Path(args.data).read_bytes()).hexdigest(),
        'bars':len(p),'first_utc':str(pd.to_datetime(p[0,0],unit='s',utc=True)),
        'last_utc':str(pd.to_datetime(p[-1,0],unit='s',utc=True)),'scenarios':len(grid),
        'train_qualified':int(grid.qualified.sum()),'elapsed_seconds':time.time()-started},indent=2))

if __name__=='__main__':main()
