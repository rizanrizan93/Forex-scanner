"""Independent pure-Python reconstruction of frozen trailing exits."""
from pathlib import Path
import sys,json,re
import pandas as pd
import numpy as np
P=Path(__file__).resolve().parent
if '--phase2' in sys.argv:P=P/'phase2'
c=json.loads((P/'FROZEN_CONFIG.json').read_text())
r=pd.read_csv(P/'FROZEN_LEDGER.csv')
d=pd.read_csv(sys.argv[1],usecols=['timestamp','open','high','low','close','spread'])
t=pd.to_datetime(d.pop('timestamp'),utc=True).astype('int64').to_numpy()//10**9
d.index=pd.to_datetime(t,unit='s',utc=True)
h=d.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
tr=pd.concat([h.high-h.low,(h.high-h.close.shift()).abs(),(h.low-h.close.shift()).abs()],axis=1).max(axis=1)
atr=tr.rolling(14).mean();atr.index+=pd.Timedelta(hours=1)
o,hi,lo,cl,sp=[d[x].to_numpy() for x in ['open','high','low','close','spread']]
minutes,window,confirm=map(int,re.search(r'M(\d+)_reclaim(\d+)_structure(\d+)',c['family']).groups())
sb=d.resample(f'{minutes}min').agg({'high':'max','low':'min','close':'last','spread':'count'}).dropna()
st=pd.concat([sb.high-sb.low,(sb.high-sb.close.shift()).abs(),(sb.low-sb.close.shift()).abs()],axis=1).max(axis=1)
sa=st.rolling(14).mean()
freq='1D' if c['family'].startswith('day') else 'W-MON'
ref=d.resample(freq,closed='left',label='left').agg({'high':'max','low':'min'}).dropna()
maxerr=0.;previous=-1;touch_rechecks=0
for row in r.itertuples():
    j,k=int(row.entry_i),int(row.exit_i);s=int(row.side)
    assert j>previous and j<=k and t[j]>=row.signal_clock
    clock=pd.to_datetime(row.signal_clock,unit='s',utc=True)
    trigger=sb.index.get_loc(clock-pd.Timedelta(minutes=minutes))
    matched=False
    for sweep in range(max(3,trigger-window-3),trigger+1):
        date=sb.index[sweep].normalize()
        key=date-pd.Timedelta(days=1) if freq=='1D' else date-pd.Timedelta(days=date.dayofweek+7)
        if key not in ref.index:continue
        level=float(ref.loc[key,'low' if s==1 else 'high'])
        if s*(float(sb.close.iloc[sweep-1])-level)<0:continue
        if not (float(sb.low.iloc[sweep])<level if s==1 else float(sb.high.iloc[sweep])>level):continue
        reclaimed=None
        for v in range(sweep,min(sweep+window,len(sb))):
            if s*(float(sb.close.iloc[v])-level)>0:reclaimed=v;break
        if reclaimed is None:continue
        expected=reclaimed
        if confirm:
            expected=None
            cross=float(sb.high.iloc[sweep-3:sweep].max()) if s==1 else float(sb.low.iloc[sweep-3:sweep].min())
            for v in range(reclaimed+1,min(reclaimed+4,len(sb))):
                if s*(float(sb.close.iloc[v])-level)<=0:break
                if s*(float(sb.close.iloc[v])-cross)>0:expected=v;break
        if expected!=trigger:continue
        low=float(sb.low.iloc[sweep:trigger+1].min());high=float(sb.high.iloc[sweep:trigger+1].max())
        expect_sl=(low if s==1 else high)-s*.1*float(sa.iloc[trigger])+(sp[j] if s==-1 else 0)
        if abs(expect_sl-row.original_sl)<1e-7:
            assert (sb.spread.iloc[sweep-3:trigger+1]==minutes).all()
            assert sb.index[trigger]-sb.index[sweep]==pd.Timedelta(minutes=minutes*(trigger-sweep))
            matched=True;break
    assert matched,('signal not reconstructable',row.entry_utc)
    previous=k
    stop=row.original_sl;water=row.entry;mfe=0.;px=None
    if c['entrymode']==0:assert abs(row.entry-(o[j]+(sp[j] if s==1 else 0)))<1e-8
    else:
        start=np.searchsorted(t,row.signal_clock)
        hit=np.flatnonzero(lo[start:j+1]+sp[start:j+1]<=row.entry) if s==1 else np.flatnonzero(hi[start:j+1]>=row.entry)
        assert len(hit) and start+hit[0]==j
        touch_rechecks+=1
    a=float(atr.asof(pd.to_datetime(row.signal_clock,unit='s',utc=True)))
    risk=abs(row.entry-row.original_sl)
    dist=[5.,10.,15.,a,2*a,.75*risk,1.5*risk,2.5*risk][c['trailkind']]
    activation=c['activation'] if c['activation']>=0 else -c['activation']*risk
    target_clock=t[j]+c['hold']*3600
    for x in range(j,k+1):
        adverse=lo[x] if s==1 else hi[x]+sp[x]
        op=o[x]+(sp[x] if s==-1 else 0)
        if s*(adverse-stop)<=0:
            px=min(stop,op) if s==1 else max(stop,op)
            assert x==k and row.reason==1;break
        if t[x]>=target_clock:
            px=op;assert x==k and row.reason==2;break
        if x==j and c['entrymode']==1:continue
        fav=hi[x] if s==1 else lo[x]+sp[x]
        water=max(water,fav) if s==1 else min(water,fav)
        mfe=max(mfe,s*(water-row.entry))
        if mfe>=activation:
            quote=cl[x]+(sp[x] if s==-1 else 0)
            proposal=min(water-dist,quote-.01) if s==1 else max(water+dist,quote+.01)
            prior=stop;stop=max(stop,proposal) if s==1 else min(stop,proposal)
            assert s*(stop-prior)>=-1e-9
    assert px is not None
    net=s*(px-row.entry)-.17-.1*(t[k]-t[j])/86400
    err=max(abs(px-row.exit),abs(net-row.net_usd_per_oz),abs(mfe-row.MFE))
    maxerr=max(maxerr,err);assert err<1e-7
    assert abs(net/abs(row.entry-row.original_sl)-row.net_R)<1e-7
result={'status':'PASS','rows':len(r),'max_absolute_price_pnl_mfe_error':maxerr,
        'limit_first_touch_rechecks':touch_rechecks,'checks':['adverse gap','stop first',
        'closed minute trailing update','never loosen stop','chronological FIFO',
        'costs and carry','H1 ATR available at signal','no favorable limit fill-bar credit',
        'preceding completed UTC level','closed bar sweep-reclaim-structure reconstruction',
        'initial structural stop and buffer'],
        'scope':'Reconstructs frozen accepted signals and exits; not a full independent enumeration of rejected or omitted signals.'}
(P/'INDEPENDENT_EXIT_AUDIT.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
