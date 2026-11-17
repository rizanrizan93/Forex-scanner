"""Causal manual-trading indicator primitives. No order/broker operations."""
from __future__ import annotations
from datetime import datetime,timezone
import numpy as np
import pandas as pd

FAMILIES=['RSI2_TREND_PULLBACK','BOLLINGER_REENTRY','KELTNER_RANGE_FADE','KIJUN_TREND_PULLBACK','SQUEEZE_BREAKOUT','SESSION_MEAN_FADE','CHANDELIER_PULLBACK','ADX_DI_BREAKOUT']


def bars(d,minutes):
    return d.resample(f'{minutes}min',label='right',closed='left').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()


def atr(d,n=14):
    prev=d.close.shift(1)
    tr=pd.concat([d.high-d.low,(d.high-prev).abs(),(d.low-prev).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False,min_periods=n).mean()


def rsi(close,n=2):
    delta=close.diff();up=delta.clip(lower=0).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    down=(-delta.clip(upper=0)).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    result=100-100/(1+up/down)
    return result.mask((up==0)&(down==0),50)


def adx(d,n=14):
    u=d.high.diff();v=-d.low.diff()
    positive=u.where((u>v)&(u>0),0);negative=v.where((v>u)&(v>0),0)
    a=atr(d,n)
    plus=100*positive.ewm(alpha=1/n,adjust=False,min_periods=n).mean()/a
    minus=100*negative.ewm(alpha=1/n,adjust=False,min_periods=n).mean()/a
    dx=(100*(plus-minus).abs()/(plus+minus)).mask((plus+minus)==0,0)
    return dx.ewm(alpha=1/n,adjust=False,min_periods=n).mean(),plus,minus


def map_values(series,t):
    idx=np.searchsorted(series.index.asi8,t,side='right')-1
    values=series.to_numpy()[np.maximum(idx,0)].astype(float);values[idx<0]=np.nan
    return values


def context(d):
    m5=bars(d,5);m15=bars(d,15);h1=bars(d,60)
    a5,a15=atr(m5),atr(m15)
    ah,ph,mh=adx(h1);am,pm,mm=adx(m15)
    eh=h1.close.ewm(span=50,adjust=False,min_periods=50).mean()
    em=m15.close.ewm(span=20,adjust=False,min_periods=20).mean()
    width=m5.close.rolling(20).std(ddof=0)*4/m5.close.rolling(20).mean()
    return {'m5':m5,'m15':m15,'h1':h1,'a5':a5,'a15':a15,'h1_adx':ah,'m15_adx':am,
            'm15_plus':pm,'m15_minus':mm,'h1_side':np.sign(h1.close-eh).fillna(0),
            'ema20':em,'rsi2':rsi(m5.close),'squeeze_width':width}


def levels(family,scale,d,ctx):
    m5,m15,a15=ctx['m5'],ctx['m15'],ctx['a15'];valid=None
    if family==0:
        center=ctx['ema20'];upper=center+.5*a15;lower=center-.5*a15
    elif family==1:
        center=m15.close.rolling(20).mean();width=[1.5,2,2.5,3][scale]*m15.close.rolling(20).std(ddof=0)
        upper=center+width;lower=center-width
    elif family==2:
        center=ctx['ema20'];width=[1,1.5,2,2.5][scale]*a15;upper=center+width;lower=center-width
    elif family==3:
        center=(m15.high.rolling(26).max()+m15.low.rolling(26).min())/2
        width=[0,.25,.5,.75][scale]*a15;upper=center+width;lower=center-width
    elif family==4:
        upper=m5.high.rolling(20).max();lower=m5.low.rolling(20).min()
        width=ctx['squeeze_width'];q=width.rolling(5760,min_periods=1000).quantile([.1,.2,.3,.4][scale]).shift(1)
        recent=(width<=q).rolling(3).max().fillna(0)
        valid=map_values(recent,d.index.asi8)>0
    elif family==5:
        local=d.index.tz_convert('Asia/Jakarta');minute=local.hour*60+local.minute
        phase=np.where(minute<420,3,np.where(minute<840,0,np.where(minute<1140,1,2)))
        days=(d.index.asi8//60_000_000_000+420)//1440;key=days*4+phase
        counts=d.close.groupby(key).cumcount()+1
        mean=d.close.groupby(key).cumsum()/counts
        mean.index=mean.index+pd.Timedelta(minutes=1) # M1 close available after its close, never at its open
        width=map_values(a15,mean.index.asi8)*[1,1.5,2,2.5][scale]
        upper=mean+width;lower=mean-width
    elif family==6:
        k=[2,2.5,3,3.5][scale]
        lower=m15.high.rolling(22).max()-k*a15
        upper=m15.low.rolling(22).min()+k*a15
    elif family==7:
        upper=m5.high.rolling(3).max();lower=m5.low.rolling(3).min()
    else:raise ValueError('Unknown indicator family')
    return upper,lower,valid


def regime_mask(family,scale,direction,d,ctx):
    t=d.index.asi8;ah=map_values(ctx['h1_adx'],t)
    side=map_values(ctx['h1_side'],t)
    if family in [0,3,6]:mask=(ah>=20)&(side==direction)
    elif family==1:mask=ah<25
    elif family in [2,5]:mask=ah<20
    else:mask=np.ones(len(d),dtype=bool)
    if family==0:
        rr=map_values(ctx['rsi2'],t);threshold=[5,10,15,20][scale]
        mask&=rr<=threshold if direction==1 else rr>=100-threshold
    if family==7:
        am=ctx['m15_adx'];rising=map_values((am>am.shift(1)).astype(float),t)>0
        amv=map_values(am,t);di=map_values(ctx['m15_plus']-ctx['m15_minus'],t)
        mask&=(amv>=[15,20,25,30][scale])&rising&(direction*di>0)
    return mask


