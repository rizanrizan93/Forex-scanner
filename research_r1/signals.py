"""Deterministic hypotheses. A row is available only at bar open + 5 minutes."""
import pandas as pd,numpy as np
SESSIONS={'ASIA_EARLY':(480,630),'ASIA_LATE':(630,780),'ASIA_FULL':(480,780),'LONDON':(840,1140),'NY_COMPARATOR':(1140,1440)}
SETUPS=['MOMENTUM','SWEEP_MSS_FVG','OPENING_BREAKOUT','NY_CONTINUATION','TREND_FVG']
def features(b):
 b=b.copy();prev=b.close.shift()
 tr=pd.concat([b.high-b.low,(b.high-prev).abs(),(b.low-prev).abs()],axis=1).max(axis=1)
 b['atr']=tr.ewm(alpha=1/14,adjust=False,min_periods=50).mean()
 b['ema20']=b.close.ewm(span=20,adjust=False,min_periods=80).mean();b['ema80']=b.close.ewm(span=80,adjust=False,min_periods=80).mean()
 for n in [6,12,24]:
  b[f'h{n}']=b.high.shift().rolling(n,min_periods=n).max();b[f'l{n}']=b.low.shift().rolling(n,min_periods=n).min()
 b['swing_high']=b.high.shift(2).where(b.high.shift(2)>=b.high.rolling(5).max()).ffill()
 b['swing_low']=b.low.shift(2).where(b.low.shift(2)<=b.low.rolling(5).min()).ffill()
 b['up_sweep']=(b.high>b.h24+.05*b.atr)&(b.close<b.h24)
 b['down_sweep']=(b.low<b.l24-.05*b.atr)&(b.close>b.l24)
 b['up_sweep_recent']=b.up_sweep.rolling(6).max();b['down_sweep_recent']=b.down_sweep.rolling(6).max()
 b['fvg_up']=b.low>b.high.shift(2)+.05*b.atr;b['fvg_dn']=b.high<b.low.shift(2)-.05*b.atr
 b['up_limit']=(b.low+b.high.shift(2))/2;b['dn_limit']=(b.high+b.low.shift(2))/2
 b['body']=b.close-b.open
 b['displacement_up']=(b.body>.8*b.atr)&((b.high-b.low)>1.2*b.atr)
 b['displacement_dn']=(b.body<-.8*b.atr)&((b.high-b.low)>1.2*b.atr)
 local=b.index.tz_convert('Asia/Jakarta');b['date']=local.strftime('%Y-%m-%d');b['minute']=local.hour*60+local.minute
 # Previous NY means most recent fully completed 19:00–00:00 WIB session, including Friday on Monday.
 ny=b[(b.minute>=1140)&b.close.notna()].groupby('date').agg(ny_open=('open','first'),ny_close=('close','last'),ny_high=('high','max'),ny_low=('low','min'),ny_n=('close','count'))
 ny['ny_dir']=np.where((ny.ny_close-ny.ny_open).abs()>.3*(ny.ny_high-ny.ny_low),np.sign(ny.ny_close-ny.ny_open),0)
 # Strict date comparison, no same-day NY input.
 dates=sorted(b.date.unique());dirs={}
 for day in dates:
  prior=ny.loc[ny.index<day]
  dirs[day]=int(prior.iloc[-1].ny_dir) if len(prior) and prior.iloc[-1].ny_n>=54 else 0
 b['ny_dir']=b.date.map(dirs)
 # No signals in a bar with a feed break, or until 24 valid preceding M5 bars exist.
 valid=b.close.notna()&(b.ticks>0)&(b.max_gap_ms<=60000)
 b['valid']=valid&valid.shift().rolling(24,min_periods=24).min().fillna(0).astype(bool)
 return b
def generate(b,session,setup,target):
 start,end=SESSIONS[session];frame=b[(b.minute>=start)&(b.minute<end)]
 # Opening range is the first six *completed* M5 bars of this specific session.
 opening=frame[frame.minute<start+30].groupby('date').agg(or_hi=('high','max'),or_lo=('low','min'),or_n=('close','count'))
 f=b.join(opening,on='date');up=f.ema20>f.ema80;dn=f.ema20<f.ema80
 if setup=='MOMENTUM':
  buy=up&(f.close>f.h12+.05*f.atr)&(f.body>.3*f.atr);sell=dn&(f.close<f.l12-.05*f.atr)&(f.body<-.3*f.atr)
 elif setup=='SWEEP_MSS_FVG':
  buy=(f.down_sweep_recent==1)&f.fvg_up&(f.close>f.h6)&(f.body>.5*f.atr)
  sell=(f.up_sweep_recent==1)&f.fvg_dn&(f.close<f.l6)&(f.body<-.5*f.atr)
 elif setup=='OPENING_BREAKOUT':
  buy=(f.minute>=start+30)&(f.or_n==6)&(f.close>f.or_hi+.05*f.atr)&(f.body>.5*f.atr)
  sell=(f.minute>=start+30)&(f.or_n==6)&(f.close<f.or_lo-.05*f.atr)&(f.body<-.5*f.atr)
 elif setup=='NY_CONTINUATION':
  buy=(f.ny_dir==1)&up&(f.close>f.h6)&(f.body>.3*f.atr)
  sell=(f.ny_dir==-1)&dn&(f.close<f.l6)&(f.body<-.3*f.atr)
 elif setup=='TREND_FVG':
  buy=up&f.fvg_up&f.displacement_up;sell=dn&f.fvg_dn&f.displacement_dn
 else:raise ValueError(setup)
 mask=f.valid&(f.minute+5>=start)&(f.minute+5<end-15)&(buy|sell)&(f.atr>0)
 s=f[mask].copy();s['direction']=np.where(buy[mask],1,-1)
 s['signal_ms']=(s.index+pd.Timedelta(minutes=5)).as_unit('ms').asi8
 s['expiry_ms']=s.signal_ms+15*60000
 midnight=pd.to_datetime(s.date).dt.tz_localize('Asia/Jakarta').dt.tz_convert('UTC')
 s['session_end_ms']=(midnight+pd.to_timedelta(end,unit='min')).astype('int64')//1000000
 s['is_limit']=int(setup in ['SWEEP_MSS_FVG','TREND_FVG'])
 s['limit']=np.where(s.direction==1,s.up_limit,s.dn_limit)
 s['stop_distance']=1.5*s.atr
 # Sweep SL uses the more conservative of 1.5 ATR or the swept six-bar extreme.
 if setup=='SWEEP_MSS_FVG':
  ref=np.where(s.direction==1,s.low.rolling(1).min(),s.high.rolling(1).max())
  extreme=np.where(s.direction==1,f.low.rolling(6).min()[mask],f.high.rolling(6).max()[mask])
  s['stop_distance']=np.maximum(s.stop_distance,abs(s['limit']-extreme)+.1*s.atr)
 s['target_r']=target;s['id']=setup+'_'+session+'_R'+str(target)
 return s[['signal_ms','expiry_ms','session_end_ms','direction','is_limit','limit','stop_distance','target_r','date','id']]
