from pathlib import Path
import numpy as np,pandas as pd,json,hashlib,gc,math,time
w=Path(__file__).resolve().parent;r=w;out=r/'data';out.mkdir(parents=True,exist_ok=True)

candtype=np.dtype([('t','<i8'),('idx','<i4'),('symbol','<i4'),('side','<i4'),('trend','<i4'),('atr','<f8'),('anchor','<f8')]);assert candtype.itemsize==40
metadata={'candidate_bytes':40,'symbols':[],'bases':[{'tf':tf,'family':fam,'lb':lb} for tf in [5,15,60] for fam in range(3) for lb in [8,16,32,64]],'started':time.time()}
def agg(m,tf):
 g=m.resample(f'{tf}min').agg({'open':'first','high':'max','low':'min','close':'last'});g['count']=m.close.resample(f'{tf}min').count();g=g.dropna();pc=g.close.shift().fillna(g.open);tr=pd.concat([g.high-g.low,(g.high-pc).abs(),(g.low-pc).abs()],axis=1).max(axis=1);g['atr']=tr.ewm(alpha=1/14,adjust=False).mean();return g
for sid,symbol,name in [(0,'EURUSD','eur_2012_2026.csv'),(2,'BTCUSD','BTCUSD_M1.csv')]:
 pieces=[];use=['timestamp','open','high','low','close']+(['spread'] if sid==1 else [])
 for p in pd.read_csv(w.parent/'replay_recovery/inputs'/name,usecols=use,chunksize=500000):
  p=p[p.timestamp>='2018-01-01']
  if len(p):pieces.append(p)
 m=pd.concat(pieces,ignore_index=True);del pieces;m.index=pd.to_datetime(m.pop('timestamp'),utc=True);assert m.index.is_monotonic_increasing and not m.index.has_duplicates
 if sid==0:m['spread']=.00001
 if sid==2:m['spread']=m.open*.0005
 assert ((m.high>=m[['open','close','low']].max(axis=1))&(m.low<=m[['open','close','high']].min(axis=1))).all()
 times=(m.index.asi8//60_000_000_000).astype('<i8');times.tofile(out/f'{sid}_times.i64');m[['open','high','low','close','spread']].to_numpy(dtype='<f8').tofile(out/f'{sid}_m1.f64')
 higher={}
 for tf in [60,240]:
  h=agg(m,tf);h['e20']=h.close.ewm(span=20,adjust=False).mean();h['e80']=h.close.ewm(span=80,adjust=False).mean();h['trend']=np.sign(h.e20-h.e80);h.index+=pd.Timedelta(minutes=tf);higher[tf]=h[['trend','count']]
 totals=[]
 for tf in [5,15,60]:
  h=agg(m,tf);at=h.index+pd.Timedelta(minutes=tf);mins=at.asi8//60_000_000_000;idx=np.searchsorted(times,mins);exists=(idx<len(times));okidx=np.minimum(idx,len(times)-1);exists &=times[okidx]==mins
  common=(h['count'].to_numpy()==tf)&(at.year>=2019)&(at.dayofweek<5)&(at.hour<20)&exists&np.isfinite(h.atr.to_numpy())&(h.atr.to_numpy()>0)
  trendmat={}
  for ht in [60,240]:
   src=higher[ht];j=src.index.get_indexer(at,method='pad');valid=j>=0;jj=np.maximum(j,0);age=(at.asi8-src.index.asi8[jj])/60e9;valid &=(age>=0)&(age<=2*ht)&(src['count'].to_numpy()[jj]==ht);trendmat[ht]=np.where(valid,src.trend.to_numpy()[jj],0)
  for fam in range(3):
   for lb in [8,16,32,64]:
    hi=h.high.shift().rolling(lb).max();lo=h.low.shift().rolling(lb).min();atr=h.atr;closepos=(h.close-h.low)/(h.high-h.low).replace(0,np.nan);fast=h.close.ewm(span=lb,adjust=False).mean();slow=h.close.ewm(span=4*lb,adjust=False).mean()
    if fam==0:
     buy=(h.close>hi+.05*atr)&(h.close>h.open);sell=(h.close<lo-.05*atr)&(h.close<h.open)
    elif fam==1:
     buy=(h.low<lo)&(h.close>lo+.05*atr)&(h.close>h.open)&(closepos>=.65);sell=(h.high>hi)&(h.close<hi-.05*atr)&(h.close<h.open)&(closepos<=.35)
    else:
     buy=(fast>slow)&(h.low<=fast)&(h.close>fast)&(h.close>h.high.shift())&(h.close>h.open);sell=(fast<slow)&(h.high>=fast)&(h.close<fast)&(h.close<h.low.shift())&(h.close<h.open)
    warm=np.arange(len(h))>=max(4*lb,80);arr=[]
    for side,test in [(1,buy),(-1,sell)]:
     jj=np.flatnonzero(common&warm&test.to_numpy());a=np.zeros(len(jj),dtype=candtype);a['t']=mins[jj];a['idx']=idx[jj];a['symbol']=sid;a['side']=side;a['atr']=atr.to_numpy()[jj];a['anchor']=(h.low.to_numpy()[jj]-.05*a['atr']) if side==1 else (h.high.to_numpy()[jj]+.05*a['atr']);a['trend']=1+2*(trendmat[60][jj]==side)+4*(trendmat[240][jj]==side);arr.append(a)
    a=np.concatenate(arr);a.sort(order=['t','symbol']);bid=metadata['bases'].index({'tf':tf,'family':fam,'lb':lb});a.tofile(out/f'base{bid}_symbol{sid}.bin');totals.append(len(a))
  print(symbol,'TF',tf,'candidates',sum(totals),flush=True)
 metadata['symbols'].append({'id':sid,'name':symbol,'rows':len(m),'first':str(m.index[0]),'last':str(m.index[-1]),'candidate_total':sum(totals),'by_base':totals});(r/'DATA_PREPARATION.json').write_text(json.dumps(metadata,indent=2));del m,h,higher;gc.collect()
metadata['finished']=time.time();(r/'DATA_PREPARATION.json').write_text(json.dumps(metadata,indent=2));print('PREPARED',metadata['finished']-metadata['started'],flush=True)

