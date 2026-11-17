"""Entry-time-only features. No target/outcome column may enter X."""
from pathlib import Path
import sys,json,hashlib
import numpy as np
import pandas as pd
from . import base as fp
from . import indicator as ip

def build_frames(d,eu,events):
 d=d.copy();eu=eu.copy();d.index=pd.to_datetime(d.index,utc=True);eu.index=pd.to_datetime(eu.index,utc=True)
 cutoff=None
 assert d.index.is_monotonic_increasing and not d.index.has_duplicates
 ts=pd.to_datetime(events.t,unit='m',utc=True);keep=np.ones(len(events),bool) if cutoff is None else np.asarray(ts<=cutoff);ev=events.loc[keep].reset_index(drop=True);ts=pd.to_datetime(ev.t,unit='m',utc=True)
 ids=np.searchsorted(d.index.asi8,ts.astype('int64').to_numpy());assert np.array_equal(d.index.asi8[ids],ts.astype('int64').to_numpy())
 side=ev.side.to_numpy(float);a=ev.atr.to_numpy(float);reference=d.open.to_numpy()[ids];X={}
 def sample(s):return s.to_numpy(dtype=float)[ids]
 def mapped(s):return fp.mapped(s,ts.astype('int64').to_numpy())
 def put(name,value):X[name]=np.asarray(value,dtype=np.float32)
 last=d.close.shift(1);prevopen=d.open.shift(1);prevh=d.high.shift(1);prevl=d.low.shift(1);rng=(prevh-prevl).replace(0,np.nan);atr1=ip.atr(d).shift(1)
 put('style',ev['style']);put('side_code',(side+1)/2);put('trigger5',(ev['style']>=40).astype(int));put('weekday',ev.dow)
 put('hour_sin',np.sin(ev.minute.to_numpy()*2*np.pi/1440));put('hour_cos',np.cos(ev.minute.to_numpy()*2*np.pi/1440))
 put('setup_age_minutes',ev.entry_i-ev.touch if 'touch' in ev else np.zeros(len(ev)))
 put('signed_setup_distance_atr',side*(reference-ev.level.to_numpy())/a)
 put('spread_atr',sample(d.spread.shift(1).clip(lower=.3))/a)
 put('opening_gap_atr',side*(reference-sample(last))/a)
 put('last_body_atr',side*sample(last-prevopen)/a)
 put('last_range_atr',sample(prevh-prevl)/a)
 put('upper_wick_atr',sample(prevh-pd.concat([last,prevopen],axis=1).max(axis=1))/a)
 put('lower_wick_atr',sample(pd.concat([last,prevopen],axis=1).min(axis=1)-prevl)/a)
 pos=sample((last-prevl)/rng);put('last_close_directional_position',np.where(side==1,pos,1-pos))
 put('atr1_ratio',sample(atr1)/a);put('rsi14_m1',side*(sample(ip.rsi(d.close,14).shift(1))-50)/50)
 for n in [1,3,5,15,30,60,120,240]:
  put(f'return_{n}_atr',side*sample(last-last.shift(n))/a)
 for n in [5,15,30,60,240]:
  hi=d.high.rolling(n,min_periods=n).max().shift(1);lo=d.low.rolling(n,min_periods=n).min().shift(1)
  put(f'range_{n}_atr',sample(hi-lo)/a);put(f'distance_high_{n}_atr',sample(hi-last)/a);put(f'distance_low_{n}_atr',sample(last-lo)/a)
  positive=(d.close.diff()>0).astype(float).rolling(n).mean().shift(1);p=sample(positive);put(f'directional_positive_fraction_{n}',np.where(side==1,p,1-p))
 for minute in [5,15,60,240]:
  z=fp.bars(d,minute);ema20=z.close.ewm(span=20,adjust=False,min_periods=20).mean();ema50=z.close.ewm(span=50,adjust=False,min_periods=50).mean()
  put(f'atr_{minute}_ratio',mapped(ip.atr(z))/a);put(f'ema20_deviation_{minute}',side*mapped(z.close-ema20)/a);put(f'ema50_deviation_{minute}',side*mapped(z.close-ema50)/a);put(f'ema20_slope3_{minute}',side*mapped(ema20-ema20.shift(3))/a)
  if minute in [5,15,60]:
   ax,plus,minus=ip.adx(z);put(f'adx_{minute}',mapped(ax));put(f'directional_di_{minute}',side*mapped(plus-minus));put(f'rsi14_{minute}',side*(mapped(ip.rsi(z.close,14))-50)/50)
 local=d.copy();local.index=local.index.tz_convert('Asia/Jakarta');day=local.resample('1D',label='right',closed='left').agg({'high':'max','low':'min','close':'last'}).dropna();day.index=day.index.tz_convert('UTC')
 put('previous_day_high_distance_atr',(mapped(day.high)-reference)/a);put('previous_day_low_distance_atr',(reference-mapped(day.low))/a)
 for bit in range(6):put(f'context_bit_{bit}',((ev.trend.to_numpy()>>bit)&1).astype(float))
 # A EUR close is known only at its minute's END, not its OPEN.
 available=eu.copy();available.index=available.index+pd.Timedelta(minutes=1)
 et=fp.mapped(pd.Series(available.index.asi8,index=available.index),ts.astype('int64').to_numpy());age=(ts.astype('int64').to_numpy()-et)/60_000_000_000;valid=(age>=0)&(age<=5)
 put('eur_age_minutes',np.minimum(age,1440));put('eur_fresh',valid.astype(int))
 for n in [1,3,5,15,30,60]:
  r=fp.mapped(available.close.pct_change(n,fill_method=None),ts.astype('int64').to_numpy());r[~valid]=np.nan;put(f'eur_return_{n}_bp',side*r*10000)
 x=pd.DataFrame(X).replace([np.inf,-np.inf],np.nan)
 assert not any('outcome' in c or 'primary_out' in c or 'reversal' in c or 'mfe' in c or 'mae' in c for c in x)
 return x,ev
