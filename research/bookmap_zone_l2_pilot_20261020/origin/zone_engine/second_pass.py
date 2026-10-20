"""Second pass: vary stop geometry and excursion horizon for 4 distinct M15 reversal signal families.
Data 2019-March 2026, same bid-M1 synthetic fills, no macro backfilled.
"""
from run_research import load,generate,sim_one,calc_pf,OUT
import numpy as np,pandas as pd,time,os,gc

def run(sym):
    df,m=load(sym);tt=df.timestamp.array.asi8;o=df.open.to_numpy();h=df.high.to_numpy();l=df.low.to_numpy();sp=df.spread.to_numpy()
    atr=m.atr.to_numpy();entrymap=m.idx.to_numpy();years=m.index.year.to_numpy()
    commission=0.07 if sym=='XAUUSD' else 0.00007;slippage=0.05 if sym=='XAUUSD' else 0.000005
    rows=[];archive={}
    for fam,variant,ix,dirs,base_stops in generate(m):
        if len(ix)<40:continue
        ent=entrymap[ix];alpha=atr[ix];entry_price=o[ent]
        for atr_floor in (.75,1.25,2.):
            # Use whichever invalidation is more distant: sweep extreme or ATR volatility floor.
            raw_risk=(entry_price-base_stops)*dirs
            risk=np.maximum(raw_risk,atr_floor*alpha)
            good=(risk>0)&(risk<=4.*alpha)
            if good.sum()<40:continue
            ii=ix[good];en=ent[good];di=dirs[good];r=risk[good];stop=entry_price[good]-di*r
            for horizon in (12,24):
                for rr in (.5,.75,1.,1.5):
                    v,ex,status=sim_one(tt,o,h,l,sp,en,di,stop,rr,horizon,commission,slippage)
                    chosen=[];last=-1
                    for k in range(len(en)):
                        if en[k]<=last or not np.isfinite(v[k]) or ex[k]<0:continue
                        chosen.append(k);last=int(ex[k])
                    if len(chosen)<25:continue
                    ci=np.asarray(chosen);vals=v[ci];yr=years[ii[ci]]
                    tr=vals[yr<=2023];va=vals[(yr>=2024)&(yr<=2025)];q=vals[yr>=2026]
                    row={'symbol':sym,'family':fam,'variant':variant,'min_stop_atr':atr_floor,'hold_h':horizon,'rr':rr,
                         'n_train':len(tr),'pf_train':calc_pf(tr),'win_train':round(100*(tr>0).mean(),2) if len(tr) else None,
                         'n_valid':len(va),'pf_valid':calc_pf(va),'win_valid':round(100*(va>0).mean(),2) if len(va) else None,
                         'n_2026q1':len(q),'pf_2026q1':calc_pf(q),'win_2026q1':round(100*(q>0).mean(),2) if len(q) else None,
                         'pf_all':calc_pf(vals),'win_all':round(100*(vals>0).mean(),2),'mean_R':round(float(np.mean(vals)),5)}
                    rows.append(row)
                    if len(tr)>=75 and len(va)>=20 and row['pf_train']>=.9:
                        key=(fam,variant,atr_floor,horizon,rr)
                        archive[key]=pd.DataFrame({'entry_at':pd.to_datetime(tt[en[ci]],utc=True),
                            'exit_at':pd.to_datetime(tt[ex[ci]],utc=True), 'direction':di[ci],
                            'pnl_r':vals,'status':status[ci]})
    out=pd.DataFrame(rows);out.to_csv(f'{OUT}/{sym}_wide_stop_all.csv',index=False)
    eligible=out.query('n_train>=75 and n_valid>=20 and pf_train>=1.0').sort_values(['pf_train','n_train'],ascending=[False,False]);eligible.to_csv(f'{OUT}/{sym}_wide_stop_eligible.csv',index=False)
    print(sym,'total configurations',len(out),'eligible',len(eligible),'max train PF',out.loc[out.n_train>=75,'pf_train'].max(),flush=True)
    for fam in sorted(out.family.unique()):
        candidates=eligible[eligible.family==fam]
        if candidates.empty: continue
        best=candidates.iloc[0]
        print(sym,fam, 'TRAIN PF',best.pf_train,'VALID PF',best.pf_valid,'2026 PF',best.pf_2026q1,'count',best.n_train,best.n_valid,best.n_2026q1,'parameters',best['variant'],best.min_stop_atr,best.hold_h,best.rr,flush=True)
        key=(best.family,best.variant,best.min_stop_atr,best.hold_h,best.rr)
        if key in archive:archive[key].to_csv(f'{OUT}/{sym}_{fam}_wide_stop_selected.csv',index=False)
    gc.collect()
if __name__=='__main__':
    a=time.time()
    t=np.array([0,60*10**9,120*10**9],np.int64);x=np.array([10.,10.,10.]);sim_one(t,x,x+.1,x-.1,np.array([.02,.02,.02]),np.array([0]),np.array([1],np.int8),np.array([9.9]),1.,1,.01,.001)
    for sym in ['XAUUSD','EURUSD']:
        run(sym);print('elapsed',round(time.time()-a,1),'seconds',flush=True)
