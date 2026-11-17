"""Causal H1 setup generation. Inputs stay outside the repository; no live access."""
from pathlib import Path
import sys,json,hashlib
import numpy as np
import pandas as pd

CODE=Path(__file__).resolve().parent
SCRATCH=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(CODE))
from input_loader import load_data,bars
OUT=SCRATCH/(sys.argv[3] if len(sys.argv)>3 else 'research_manual_h1_r4');(OUT/'inputs').mkdir(parents=True,exist_ok=True)
BD=np.dtype([('o','<f8'),('h','<f8'),('l','<f8'),('c','<f8'),('t','<i8'),('day','<i4'),('year','<i4'),('minute','<i2'),('dow','<i2')])
ED=np.dtype([('entry','<i4'),('touch','<i4'),('style','<i4'),('s','<i4'),('atr','<f8'),('level','<f8'),('trend','<i4')])
MIN=60_000_000_000

def atr(f):
    p=f.close.shift(1)
    tr=pd.concat([f.high-f.low,(f.high-p).abs(),(f.low-p).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()

def mapped(s,t):
    k=np.searchsorted(s.index.asi8,t,side='right')-1
    x=s.to_numpy()[np.maximum(k,0)].astype(float);x[k<0]=np.nan
    return x

def direction(f):
    e20=f.close.ewm(span=20,adjust=False,min_periods=20).mean()
    e50=f.close.ewm(span=50,adjust=False,min_periods=50).mean()
    return pd.Series(np.where((e20>e20.shift(3))&(f.close>e50),1,np.where((e20<e20.shift(3))&(f.close<e50),-1,0)),index=f.index)

def state(series,condition):
    at=pd.Series(series.index.asi8,index=series.index).where(condition).ffill()
    return series.where(condition).ffill(),at

def main():
    protocol=CODE/'protocol.json'
    registration={'protocol_sha256':hashlib.sha256(protocol.read_bytes()).hexdigest(),'generated_before_results':not (OUT/'results/screen.csv').exists()}
    (OUT/'registration.json').write_text(json.dumps(registration,indent=2))
    d,provenance=load_data()
    if len(sys.argv)>2:d=d[d.index<=pd.Timestamp(sys.argv[2])]
    t=d.index.asi8
    f=bars(d,5);h=bars(d,60);h4=bars(d,240);t5=f.index.asi8;start=t5-5*MIN
    a=atr(h);ah=mapped(a,start);a_entry=mapped(a,t5)
    hp=h.close.shift(1);tr=pd.concat([h.high-h.low,(h.high-hp).abs(),(h.low-hp).abs()],axis=1).max(axis=1)
    up=h.high.diff();down=-h.low.diff();plus=up.where((up>down)&(up>0),0).ewm(alpha=1/14,adjust=False).mean()
    minus=down.where((down>up)&(down>0),0).ewm(alpha=1/14,adjust=False).mean()
    dx=100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
    adx=dx.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    bh=mapped(direction(h),t5);b4=mapped(direction(h4),t5);ad=mapped(adx,t5)
    # Day boundaries are explicitly WIB; previous completed local day only.
    dl=d.copy();dl.index=dl.index.tz_convert('Asia/Jakarta')
    daybars=dl.resample('1D',closed='left',label='right').agg({'high':'max','low':'min'}).dropna();daybars.index=daybars.index.tz_convert('UTC')
    prev=np.r_[np.nan,f.close.to_numpy()[:-1]];hi=f.high.to_numpy();lo=f.low.to_numpy();cl=f.close.to_numpy()
    local=pd.to_datetime(start,utc=True).tz_convert('Asia/Jakarta');mins=local.hour.to_numpy()*60+local.minute.to_numpy()
    dates=(start//MIN+420)//1440;phase=np.where(mins<840,0,np.where(mins<1140,1,2))
    valid=(local.year>=2019)&(local.dayofweek<5)&(mins>=420)&(mins<1435)&np.isfinite(ah)&(ah>0)
    arrays=[];counts=[];chart=[]
    for family in range(7):
      for scale in range(2):
        st=family*2+scale;parents=[]
        for s in [1,-1]:
          born=None;alive=np.ones(len(f),dtype=bool)
          if family in [0,1]:
            ema=h.close.ewm(span=20 if family==0 else 50,adjust=False,min_periods=50).mean()
            lev=mapped(ema-s*(0 if scale==0 else .25)*a,start)
          elif family==2:
            n=[12,24][scale];channel=h.high.shift(1).rolling(n).max() if s==1 else h.low.shift(1).rolling(n).min()
            crossed=(h.close>channel)&(h.close.shift(1)<=channel) if s==1 else (h.close<channel)&(h.close.shift(1)>=channel)
            level,at=state(channel,crossed);lev=mapped(level,start);born=mapped(at,start)
            alive=(start-born>=0)&(start-born<=6*60*MIN)
          elif family==3:
            roll=h.low.rolling([6,12][scale]).min() if s==1 else h.high.rolling([6,12][scale]).max()
            lev=mapped(roll,start)
          elif family==4:lev=mapped(daybars.low if s==1 else daybars.high,start)
          elif family==5:
            bottom=h.high.shift(2) if s==1 else h.high
            top=h.low if s==1 else h.low.shift(2)
            ok=(top-bottom>=.1*a)&((h.index.to_series().diff(2).dt.total_seconds())==7200)
            target=(top if s==1 else bottom) if scale==0 else (top+bottom)/2
            level,at=state(target,ok);lev=mapped(level,start);born=mapped(at,start)
            alive=(start-born>=0)&(start-born<=8*60*MIN)
          else:
            n=[6,12][scale];upper=h.high.rolling(n).max();lower=h.low.rolling(n).min()
            lev=mapped(upper if s==1 else lower,start);alive=mapped((upper-lower<=4*a).astype(int),start)==1
          if family==6:cross=(hi>=lev)&(prev<lev) if s==1 else (lo<=lev)&(prev>lev)
          else:cross=(lo<=lev)&(prev>lev) if s==1 else (hi>=lev)&(prev<lev)
          if family==4 and scale:cross &= (lev-lo>=.1*ah) if s==1 else (hi-lev>=.1*ah)
          ids=np.flatnonzero(cross&valid&alive&np.isfinite(lev))
          keys=born[ids] if born is not None else dates[ids]*3+phase[ids]
          _,first=np.unique(keys,return_index=True)
          for i in ids[np.sort(first)]:
            # Touch is consumed before trend/news/distance/session filters.
            for k in range(i,min(i+(1 if family==6 else 6),len(f))):
              if t5[k]!=t5[i]+(k-i)*5*MIN:break
              if s*(cl[k]-lev[i])<=0:continue
              j=int(np.searchsorted(t,t5[k]));touch=int(np.searchsorted(t,start[i]))
              if j>=len(d) or t[j]!=t5[k] or not np.isfinite(a_entry[k]) or a_entry[k]<=0:break
              trend=(1 if bh[k]==s else 0)|(2 if bh[k]==s and b4[k]==s else 0)|(4 if bh[k]==s and b4[k]==s and ad[k]>=20 else 0)
              parents.append((j,touch,st,s,float(a_entry[k]),float(lev[i]),trend));break
        arr=np.array(parents,dtype=ED);arr.sort(order=['entry','touch','s']);arrays.append(arr)
        counts.append({'style':st,'family':family,'scale':scale,'events':len(arr),'train':int((d.index.year[arr['entry']]<=2022).sum())})
        print('STYLE',st,'events',len(arr),flush=True)
    ev=np.concatenate(arrays);ev.sort(order=['style','entry','touch','s']);ev.tofile(OUT/'inputs/events.bin')
    # Reconstruct independently from source, rather than trust prior replay bars.
    bd=np.empty(len(d),dtype=BD);loc=d.index.tz_convert('Asia/Jakarta')
    for target,source in [('o','open'),('h','high'),('l','low'),('c','close')]:bd[target]=d[source].to_numpy()
    bd['t']=t//MIN;bd['day']=(t//MIN+420)//1440;bd['year']=loc.year;bd['minute']=loc.hour*60+loc.minute;bd['dow']=loc.dayofweek
    bd.tofile(OUT/'inputs/bars.bin')
    safe=np.ones(len(d),dtype=np.uint8)
    news=pd.read_csv(SCRATCH/'research_manual_r1/frozen-inputs/data/events_2016_2025.csv')
    for row in news.itertuples():
      if row.event not in ['CPI','PPI','NFP','FOMC']:continue
      ns=pd.Timestamp(row.timestamp_utc).value;width=(60 if row.event=='FOMC' else 30)*MIN
      safe[np.searchsorted(t,ns-width,'left'):np.searchsorted(t,ns+width,'right')]=0
    safe.tofile(OUT/'inputs/news.bin')
    # Each minute can access only a fully closed H1; a gap does not invent a close.
    mapped(h.close,t).astype('<f8').tofile(OUT/'inputs/h1_close.bin')
    meta={'bars':len(d),'events':len(ev),'styles':counts,'bar_dtype':BD.descr,'event_dtype':ED.descr,'provenance':provenance,'coverage':{str(y):int((loc.year==y).sum()) for y in range(2019,2026)},'input_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (OUT/'inputs').glob('*.bin')}}
    (OUT/'inputs/metadata.json').write_text(json.dumps(meta,indent=2));print('PREPARED',len(ev),flush=True)

if __name__=='__main__':main()
