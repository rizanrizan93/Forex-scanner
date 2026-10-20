"""Exploratory point-in-time M15 reversal families on Dukascopy-tick-derived BID M1.
No macro history present. Outputs NOT broker-native execution simulation.
"""
import os, time, json, gc
import numpy as np, pandas as pd
from numba import njit
OUT='/mnt/data/reversal_discovery_20261020'
IN='/mnt/data/reversal_pair_comparison'
@njit(cache=True)
def sim_one(t,o,h,l,spread,entry,side,stop,rr,holding,commission,slip):
    n=len(entry); ret=np.full(n,np.nan); exits=np.full(n,-1,dtype=np.int64); status=np.zeros(n,dtype=np.int8)
    # BID M1 levels and simulated spread/fees; stop first when intrabar path ambiguous.
    for k in range(n):
        j=entry[k]
        if j<0 or j>=len(t):continue
        s=side[k]; sl=stop[k]; ep=o[j]; risk=(ep-sl)*s
        if risk<=0:continue
        tp=ep+s*risk*rr
        fee=max(spread[j],0.) + commission + 2*slip
        # Enforce max 24h wall-clock and leave position outstanding through market closure.
        end=t[j]+holding*60*1000000000
        ix=j
        while ix<len(t) and t[ix]<=end:
            if s==1:
                stop_hit=l[ix]<=sl; target_hit=h[ix]>=tp
            else:
                stop_hit=h[ix]>=sl; target_hit=l[ix]<=tp
            if stop_hit:
                # Market reopen stop gap is filled at worse of target vs open.
                ex=min(sl,o[ix]) if s==1 else max(sl,o[ix])
                ret[k]=(s*(ex-ep)-fee)/risk; exits[k]=ix; status[k]=1;break
            if target_hit:
                ret[k]=(s*(tp-ep)-fee)/risk; exits[k]=ix; status[k]=2;break
            ix+=1
        if exits[k]<0 and ix<len(t) and t[ix]-end<=72*3600*1000000000:
            ex=o[ix] if t[ix]>end else o[max(ix-1,j)]
            ret[k]=(s*(ex-ep)-fee)/risk;exits[k]=ix;status[k]=3
    return ret,exits,status

def calc_pf(v):
    v=np.asarray(v); v=v[np.isfinite(v)]; pos=v[v>0].sum(); neg=-v[v<0].sum()
    return round(pos/neg,4) if neg>0 else np.nan

def metrics(trades,period):
    x=trades.loc[period];p=x['pnl_r'].to_numpy(); p=p[np.isfinite(p)]
    return {'n':len(p),'PF_R':calc_pf(p),'win_pct':round(float((p>0).mean()*100),2) if len(p) else 0,
            'mean_R':round(float(p.mean()),5) if len(p) else np.nan,
            'sum_R':round(float(p.sum()),3) if len(p) else 0}

def load(symbol):
    path=f'{IN}/{symbol}_m1_from_ticks.csv'; t0=time.time()
    # Read all actual Dukascopy tick-derived rows with no synthetic fills.
    df=pd.read_csv(path,usecols=['timestamp','open','high','low','close','spread'],dtype={'open':'float64','high':'float64','low':'float64','close':'float64','spread':'float64'})
    df['timestamp']=pd.to_datetime(df['timestamp'],utc=True);df.sort_values('timestamp',inplace=True)
    if df.timestamp.duplicated().any():raise ValueError('duplicate timestamps')
    print(symbol,'M1 read',len(df),'seconds',round(time.time()-t0,1),flush=True)
    k=df.set_index('timestamp')
    m=k.resample('15min',label='left',closed='left').agg(open=('open','first'),high=('high','max'),low=('low','min'),close=('close','last'),count=('close','count'))
    m=m.dropna().copy(); m['valid']=m['count']>=12
    prev=m['close'].shift(1)
    tr=pd.concat([m.high-m.low,(m.high-prev).abs(),(m.low-prev).abs()],axis=1).max(axis=1)
    m['atr']=tr.rolling(56,min_periods=56).mean().shift(1)  # 14h lookback, prior completed bars
    m['bar_range']=m.high-m.low
    # Avoid source gaps by requiring candles adjacent, current and prior completed.
    m['previous_adjacent']=m.index.to_series().diff().eq(pd.Timedelta(minutes=15))
    # Previous fully completed UTC trading day with sufficiently many M15 bars, not unfinished day.
    days=m.resample('D').agg(day_high=('high','max'), day_low=('low','min'), n=('close','size'))
    days.loc[days.n<32,['day_high','day_low']]=np.nan
    days[['day_high','day_low']]=days[['day_high','day_low']].ffill().shift(1)
    m=m.join(days[['day_high','day_low']].reindex(m.index.floor('D')).set_axis(m.index))
    # Prior known time windows, no future extremum leakage.
    for w in (16,32,64,96):
        m[f'prev_hi_{w}']=m.high.shift(1).rolling(w,min_periods=w).max()
        m[f'prev_lo_{w}']=m.low.shift(1).rolling(w,min_periods=w).min()
    for w in (32,64,128):
        m[f'mean_{w}']=m.close.rolling(w,min_periods=w).mean().shift(1)
        m[f'std_{w}']=m.close.rolling(w,min_periods=w).std().shift(1)
        m[f'ema_{w}']=m.close.ewm(span=w,adjust=False,min_periods=w).mean().shift(1)
    m['idx'] = np.searchsorted(df.timestamp.to_numpy(dtype='datetime64[ns]'),(m.index+pd.Timedelta(minutes=15)).to_numpy(dtype='datetime64[ns]')).astype('int64')
    valid_idx=m['idx'].to_numpy(); m1_ns=df.timestamp.array.asi8
    expected=(m.index.asi8+15*60*10**9)
    mintime=m1_ns[np.minimum(valid_idx,len(df)-1)]-expected
    m['can_enter']=(valid_idx<len(df))&(mintime>=0)&(mintime<=120*10**9)&m['valid']&m['previous_adjacent']&(m.atr>0)
    return df,m

def generate(m):
    atr=m.atr.to_numpy(); high=m.high.to_numpy();low=m.low.to_numpy();close=m.close.to_numpy();op=m.open.to_numpy();prev_close=np.roll(close,1);rng=m.bar_range.to_numpy();mask=m.can_enter.to_numpy()
    entries=[]
    def append(family,variant,signal,sl_anchor):
        select=mask&(signal!=0)&np.isfinite(sl_anchor)&np.isfinite(atr)
        idx=np.flatnonzero(select);dirs=signal[idx]; stops=sl_anchor[idx]
        # Physical sanity: initial stop is 0.15-4 ATR away from bid entry; no tuning here.
        entries.append((family,variant,idx,dirs,stops))
    for w in (16,32,64,96):
        h=m[f'prev_hi_{w}'].to_numpy();l=m[f'prev_lo_{w}'].to_numpy()
        topwick=(high-np.maximum(op,close))/np.maximum(rng,1.e-15)
        botwick=(np.minimum(op,close)-low)/np.maximum(rng,1.e-15)
        for depth in (0.0,0.1,0.2):
            for wick in (0.3,0.5,0.65):
                sel=np.zeros(len(m),dtype=np.int8)
                sell=(high>h+depth*atr)&(close<h)&(topwick>=wick)
                buy=(low<l-depth*atr)&(close>l)&(botwick>=wick)
                sel[sell]=-1;sel[buy]=1
                stop=np.where(sel==1,low-.1*atr,high+.1*atr)
                append('liquidity_sweep',f'lookback={w}|sweep_atr={depth}|wick={wick}',sel,stop)
    for w in (32,64,128):
        mean=m[f'mean_{w}'].to_numpy();std=m[f'std_{w}'].to_numpy()
        z=(close-mean)/np.maximum(std,1.e-10)
        zp=np.roll(z,1)
        for extreme in (1.5,2.0,2.5):
            for rec in (0.4,0.8):
                sel=np.zeros(len(m),dtype=np.int8)
                sel[(zp< -extreme)&(z> -extreme+rec)&(close>op)]=1
                sel[(zp> extreme)&(z<extreme-rec)&(close<op)]=-1
                stop=np.where(sel==1,low-.1*atr,high+.1*atr)
                append('mean_reentry',f'window={w}|z={extreme}|recovery={rec}',sel,stop)
    for w in (32,64,128):
        mean=m[f'ema_{w}'].to_numpy();delta=(prev_close-mean)/np.maximum(atr,1.e-10)
        for ext in (1.5,2.5,3.5):
            for strength in (0.2,0.4):
                bod=np.abs(close-op)/np.maximum(rng,1.e-15)
                sel=np.zeros(len(m),dtype=np.int8)
                sel[(delta<-ext)&(close>op)&(bod>=strength)&(close>prev_close)]=1
                sel[(delta>ext)&(close<op)&(bod>=strength)&(close<prev_close)]=-1
                stop=np.where(sel==1,low-.1*atr,high+.1*atr)
                append('exhaustion_reversal',f'ema={w}|extension_atr={ext}|body={strength}',sel,stop)
    # Specific previous-day liquidity: independent of rolling 4/8/24h extremes.
    dh=m.day_high.to_numpy();dl=m.day_low.to_numpy()
    topwick=(high-np.maximum(op,close))/np.maximum(rng,1.e-15)
    botwick=(np.minimum(op,close)-low)/np.maximum(rng,1.e-15)
    for depth in (0.0,0.1,0.2):
        for wick in (0.3,0.5,0.65):
            sel=np.zeros(len(m),dtype=np.int8)
            sel[(high>dh+depth*atr)&(close<dh)&(topwick>=wick)]=-1
            sel[(low<dl-depth*atr)&(close>dl)&(botwick>=wick)]=1
            stop=np.where(sel==1,low-.1*atr,high+.1*atr)
            append('previous_day_sweep',f'depth_atr={depth}|wick={wick}',sel,stop)
    return entries

def run(symbol):
    df,m=load(symbol)
    ts=df.timestamp.array.asi8
    o=df.open.to_numpy();h=df.high.to_numpy();l=df.low.to_numpy();s=df.spread.to_numpy()
    atr=m.atr.to_numpy(); m1i=m.idx.to_numpy();close_m15=m.close.to_numpy()
    year=m.index.year.to_numpy()
    rr_list=(.75,1.,1.25,1.5,2.)
    cost_com=0.07 if symbol=='XAUUSD' else 0.00007
    cost_slip=0.05 if symbol=='XAUUSD' else 0.000005
    generated=generate(m)
    print(symbol,'generated',len(generated),'variants',flush=True)
    results=[];top_ledgers=[]
    for family,var,ix,dir,stop in generated:
        if len(ix)<35:continue
        ent=m1i[ix]; r=(o[ent]-stop)*dir
        ok=(r>=0.15*atr[ix])&(r<=4*atr[ix])
        ix=ix[ok];ent=ent[ok];dir=dir[ok];stop=stop[ok]
        if len(ix)<35:continue
        for rr in rr_list:
            ret,exit_i,status=sim_one(ts,o,h,l,s,ent,dir,stop,rr,24,cost_com,cost_slip)
            accepted=[];last_exit=-1
            for k in range(len(ix)):
                if ent[k]<=last_exit or not np.isfinite(ret[k]) or exit_i[k]<0:continue
                accepted.append(k);last_exit=int(exit_i[k])
            if not accepted:continue
            sel=np.asarray(accepted);v=ret[sel];yrs=year[ix[sel]]; n=len(sel)
            train=v[yrs<=2023];val=v[(yrs>=2024)&(yrs<=2025)];recent=v[yrs>=2026]
            r0={'symbol':symbol,'family':family,'config':var,'rr':rr,'n_all':n,'n_train':len(train),'pf_train':calc_pf(train),
                'win_train':round(100*(train>0).mean(),2) if len(train) else np.nan,
                'n_valid':len(val),'pf_valid':calc_pf(val),'win_valid':round(100*(val>0).mean(),2) if len(val) else np.nan,
                'n_2026q1':len(recent),'pf_2026q1':calc_pf(recent),'win_2026q1':round(100*(recent>0).mean(),2) if len(recent) else np.nan,
                'pf_all':calc_pf(v),'win_all':round(100*(v>0).mean(),2),'mean_R':round(float(v.mean()),5),'sum_R':round(float(v.sum()),4)}
            results.append(r0)
            # Retain candidate trade details for independent re-sorting and uncertainty calculation.
            if len(train)>=65 and len(val)>=20 and r0['pf_train']>1.0:
                top_ledgers.append((r0, pd.DataFrame({'entry_at':pd.to_datetime(ts[ent[sel]],utc=True),'exit_at':pd.to_datetime(ts[exit_i[sel]],utc=True),
                     'side':dir[sel],'pnl_r':v,'status':status[sel],'rr':rr,'family':family,'config':var})))
    result=pd.DataFrame(results)
    result.to_csv(f'{OUT}/{symbol}_all_family_results.csv',index=False)
    train_r=result.query('n_train>=65 and n_valid>=20 and pf_train>=1.0').sort_values(['pf_train','n_train'],ascending=[False,False]);train_r.to_csv(f'{OUT}/{symbol}_train_eligible.csv',index=False)
    print(symbol,'total',len(result),'train eligible',len(train_r),flush=True)
    # Pick a family winner solely on TRAIN, with sufficient n; no validation selection.
    chosen=[]
    for family in sorted(result.family.unique()):
        cand=train_r[train_r.family==family]
        if len(cand):
            best=cand.iloc[0];chosen.append(best.to_dict());print(symbol,'family',family,'train=',best.pf_train,'valid=',best.pf_valid,'q1=',best.pf_2026q1,'n',best.n_train,best.n_valid, best['config'],best.rr,flush=True)
            ledger=next((z for r0,z in top_ledgers if r0['family']==family and r0['config']==best['config'] and r0['rr']==best.rr),None)
            if ledger is not None:ledger.to_csv(f'{OUT}/{symbol}_{family}_train_selected_trades.csv',index=False)
    pd.DataFrame(chosen).to_csv(f'{OUT}/{symbol}_train_chosen_families.csv',index=False)
    del df,m;gc.collect()
    return chosen

if __name__=='__main__':
    start=time.time();print('start',pd.Timestamp.utcnow(),flush=True)
    # Warm compile small dummy input and process pairs separately.
    t=np.array([0,60*10**9,120*10**9],np.int64);v=np.array([10.,10.,10.]);
    sim_one(t,v,v+.1,v-.1,np.array([.02,.02,.02]),np.array([0]),np.array([1],np.int8),np.array([9.9]),1.,1,.01,.001)
    allchosen=[]
    for sym in ['XAUUSD','EURUSD']:
        allchosen+=run(sym)
        print('Elapsed total',round(time.time()-start,1),'sec',flush=True)
    with open(f'{OUT}/metadata.json','w') as f:json.dump({'period':'2019-01 through 2026-03','research':'M15 causal reversal families with M1 stop-first synthetic bid fills, not raw tick, no macro vintage', 'settings':'H1/H2/H4 Candidate A unrelated; family-selected on 2019-23 only', 'n_train_candidate_min':65,'n_validation_candidate_min':20},f,indent=2)
