"""20 operational reversal families, causal indicators and session failure patterns."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from .reversal_zones import closed_features
from .daily_reversal import COSTS
CONTRACT='RIZAN_XAU_REVERSAL_FAMILIES_V2_20M'
GRID={'side':[1,-1],'family':['H1_BB20','H1_BB40','H1_KELTNER20','H1_LINEAR48','H1_DONCHIAN24','M15_RSI7','M15_RSI14','M15_ROC16','M15_ATR_STRETCH12','M15_CLIMAX','ASIA_FALSE_BREAK','EUROPE_FALSE_BREAK','NY_OPENING_FADE','PREV_D1_FAILED_BREAK','D1_OPEN_STRETCH','M15_DOUBLE_SWEEP','M15_BREAKER','H1_FVG_FILL','H1_FAILED_BOS','M15_COMPRESSION_FADE'],
'entry':['NEXT_M1','RETEST50_TOUCH'],'stop_atr5':[.25,.5,.75,1.,1.5],'target_adr_fraction':[.15,.25,.35,.5,.75],'horizon_minutes':[60,120,240,360,480],
'strength':[0.,.5,1.,1.5,2.],'confirmation':['BASE','M5_DISPLACEMENT','M15_ALIGNED','M5_SWEEP','H1_ALIGNED'],'regime':['ANY','ALIGNED','OPPOSED','NEUTRAL'],
'session_phase':['ALL','FIRST_60','SECOND_60','MIDDLE_120','LAST_120'],'session_utc':[0,6,12,18]}
SHAPE=tuple(len(x) for x in GRID.values());LOCAL_SHAPE=(2,1)+SHAPE[2:];CONFIGURATIONS=math.prod(SHAPE)
MIN_RR=1.5;MIN_ADR_FRACTION=.15

def bars(m1,freq,min_count):
 a=m1.resample(freq,label='right',closed='left').agg({'open':'first','high':'max','low':'min','close':'last'})
 return a.loc[m1.close.resample(freq,label='right',closed='left').count()>=min_count].copy()

def atr(f,n):
 return pd.concat([f.high-f.low,(f.high-f.close.shift()).abs(),(f.low-f.close.shift()).abs()],axis=1).max(axis=1).rolling(n).mean()

def rsi(close,n):
 d=close.diff();up=d.clip(lower=0).ewm(alpha=1/n,adjust=False,min_periods=n).mean();dn=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
 out=100-100/(1+up/dn.replace(0,np.nan));return out.where(dn>0,np.where(up>0,100.,50.)).where(up.notna())

def align(f,known,columns,lag):
 keys=pd.DataFrame({'key':f.index-pd.Timedelta(minutes=lag)},index=f.index)
 return pd.merge_asof(keys.reset_index(),known[columns].reset_index().rename(columns={'timestamp':'key'}),on='key',direction='backward').set_index('timestamp')[columns]

def features(m1):
 f=closed_features(m1);f['atr5']=atr(f,14);m15=bars(m1,'15min',15);h1=bars(m1,'1h',45);d1=bars(m1,'1D',900)
 m15['atr15']=atr(m15,14);h1['atr1']=atr(h1,20)
 d1['adr20']=(d1.high-d1.low).rolling(20).mean();ema20=d1.close.ewm(span=20,adjust=False,min_periods=20).mean();ema50=d1.close.ewm(span=50,adjust=False,min_periods=50).mean()
 d1['d1_regime']=np.where((d1.close>ema50)&(ema20>ema20.shift(3)),1,np.where((d1.close<ema50)&(ema20<ema20.shift(3)),-1,0));d1.loc[ema50.isna(),'d1_regime']=np.nan
 d1['prior_d1_low']=d1.low;d1['prior_d1_high']=d1.high
 h1['h1_mean20']=h1.close.rolling(20).mean();h1['h1_mean40']=h1.close.rolling(40).mean()
 h1['h1_std20']=h1.close.rolling(20).std(ddof=0);h1['h1_std40']=h1.close.rolling(40).std(ddof=0);h1['h1_ema20']=h1.close.ewm(span=20,adjust=False,min_periods=20).mean()
 h1['h1_dc_low']=h1.low.rolling(24).min();h1['h1_dc_high']=h1.high.rolling(24).max()
 n=48;x=np.arange(n)-(n-1)/2;vx=(n*n-1)/12;mean=h1.close.rolling(n).mean();slope=h1.close.rolling(n).apply(lambda a:np.dot(a,x)/n/vx,raw=True)
 h1['h1_fit']=mean+slope*(n-1)/2;h1['h1_dev']=h1.close.rolling(n).std(ddof=0)
 h1['h1_bias']=np.sign(h1.close-h1.h1_ema20)
 for side in [1,-1]:
  label=str(side);h1['fvg_low_'+label]=np.nan;h1['fvg_high_'+label]=np.nan
  active=None;failed=None;sig=np.zeros(len(h1),bool)
  for i,row in enumerate(h1.itertuples()):
   if active is not None and side*(row.close-(active[0] if side==1 else active[1]))<0:active=None
   if i>=2:
    if side==1 and row.low>h1.high.iloc[i-2] and row.close>row.open:active=(h1.high.iloc[i-2],row.low)
    if side==-1 and row.high<h1.low.iloc[i-2] and row.close<row.open:active=(row.high,h1.low.iloc[i-2])
   if active is not None:h1.iloc[i,h1.columns.get_loc('fvg_low_'+label)]=active[0];h1.iloc[i,h1.columns.get_loc('fvg_high_'+label)]=active[1]
   if failed is not None:
    if i-failed[0]>2:failed=None
    elif side*(row.close-failed[1])>0 and side*(row.close-row.open)>0:sig[i]=True;failed=None
   if i>=12:
    level=h1.low.iloc[i-12:i].min() if side==1 else h1.high.iloc[i-12:i].max()
    if side*(row.close-level)<0:failed=(i,level)
  h1['h1_failed_'+label]=sig
 hc=[c for c in h1 if c.startswith(('h1_','fvg_'))]+['atr1'];f=pd.concat([f,align(f,h1,hc,5)],axis=1)
 f=pd.concat([f,align(f,d1,['adr20','d1_regime','prior_d1_low','prior_d1_high'],5)],axis=1)
 m15['rsi7']=rsi(m15.close,7);m15['rsi14']=rsi(m15.close,14);m15['mean12']=m15.close.rolling(12).mean();m15['roc16']=(m15.close-m15.close.shift(16))/m15.atr15
 m15['prev_rsi7']=m15.rsi7.shift();m15['prev_rsi14']=m15.rsi14.shift();m15['prev_roc16']=m15.roc16.shift()
 m15['p8low']=m15.low.shift().rolling(8).min();m15['p8high']=m15.high.shift().rolling(8).max();m15['prev_range_ratio']=(m15.high-m15.low).shift()/m15.atr15.shift()
 m15['prev_open']=m15.open.shift();m15['prev_close']=m15.close.shift();m15['prev_low']=m15.low.shift();m15['prev_high']=m15.high.shift();m15['prev_atr15']=m15.atr15.shift();m15['compress']=((m15.high-m15.low)/m15.atr15).shift().rolling(8).mean()<.65
 for side in [1,-1]:
  sweep=(m15.low<m15.p8low)&(m15.close>m15.p8low) if side==1 else (m15.high>m15.p8high)&(m15.close<m15.p8high)
  prior=sweep.shift().rolling(8).max().fillna(0)>0;m15['double_'+str(side)]=sweep&prior
  # Failed support/resistance break then close back through its known level within four candles.
  sig=np.zeros(len(m15),bool);seed=None
  for i,row in enumerate(m15.itertuples()):
   if seed is not None:
    if i-seed[0]>4:seed=None
    elif side*(row.close-seed[1])>0 and side*(row.close-row.open)>0:sig[i]=True;seed=None
   level=row.p8low if side==1 else row.p8high
   if np.isfinite(level) and side*(row.close-level)<0:seed=(i,level)
  m15['breaker_'+str(side)]=sig
 # Exact M15 closing events, known only when the M15 is complete.
 for col in m15.columns:f['m15_'+col]=m15[col].reindex(f.index)
 # Latest completed M15 for confirmation context, not a future forming candle.
 f=pd.concat([f,align(f,m15.rename(columns={'close':'m15_context_close','open':'m15_context_open'}),['m15_context_close','m15_context_open'],0)],axis=1)
 f['prior5low']=f.low.shift().rolling(12).min();f['prior5high']=f.high.shift().rolling(12).max()
 # Previously completed intraday session ranges; never yesterday's before current range completes.
 for name,start,end in [('asia',0,6),('europe',6,12),('nyopen',12,13)]:
  q=m1.loc[(m1.index.hour>=start)&(m1.index.hour<end)];b=q.resample('1D').agg({'low':'min','high':'max'});ct=q.close.resample('1D').count();b=b.loc[ct>=(45 if name=='nyopen' else 300)];b.index+=pd.Timedelta(hours=end);b['session_formed']=b.index.asi8/3.6e12
  mapped=align(f,b,['low','high','session_formed'],5);same=(pd.to_datetime(mapped.session_formed*3.6e12,utc=True).dt.normalize().to_numpy()==f.index.normalize().to_numpy())
  f[name+'_low']=mapped.low.where(same);f[name+'_high']=mapped.high.where(same)
 # UTC day open known at first available minute; prohibit absent midnight quote.
 opens=m1.open.loc[(m1.index.hour==0)&(m1.index.minute==0)].rename('day_open');f['day_open']=opens.reindex((f.index-pd.Timedelta(minutes=5)).normalize()).to_numpy()
 return f

def events(f,side,family):
 body=side*(f.close-f.open)>0;prev=f.close.shift();a=f.atr;level=pd.Series(np.nan,index=f.index);signal=pd.Series(False,index=f.index);strength=pd.Series(0.,index=f.index)
 def reentry(bound):return (side*(prev-bound)<=0)&(side*(f.close-bound)>0)&body
 if family.startswith('H1_') and family in ['H1_BB20','H1_BB40','H1_KELTNER20','H1_LINEAR48','H1_DONCHIAN24']:
  if family=='H1_BB20':level=f.h1_mean20-side*2*f.h1_std20
  elif family=='H1_BB40':level=f.h1_mean40-side*2*f.h1_std40
  elif family=='H1_KELTNER20':level=f.h1_ema20-side*1.5*f.atr1
  elif family=='H1_LINEAR48':level=f.h1_fit-side*1.5*f.h1_dev
  else:level=f.h1_dc_low if side==1 else f.h1_dc_high
  signal=reentry(level);strength=side*(level-prev)/a
 elif family in ['M15_RSI7','M15_RSI14']:
  n=7 if family.endswith('7') else 14;r=f['m15_rsi'+str(n)];p=f['m15_prev_rsi'+str(n)]
  signal=((p<=35)&(r>p)&(side*(f.m15_close-f.m15_open)>0)) if side==1 else ((p>=65)&(r<p)&(side*(f.m15_close-f.m15_open)>0))
  strength=((35-p)/10 if side==1 else (p-65)/10).clip(lower=0);level=f.m15_low if side==1 else f.m15_high
 elif family=='M15_ROC16':
  p=f.m15_prev_roc16;c=f.m15_roc16;signal=(side*p<-2)&(side*(c-p)>0)&(side*(f.m15_close-f.m15_open)>0);strength=(-side*p-2).clip(lower=0);level=f.m15_close
 elif family=='M15_ATR_STRETCH12':
  ext=side*(f.m15_mean12-f.m15_close)/a;signal=(ext>1)&(side*(f.m15_close-f.m15_open)>0);strength=(ext-1).clip(lower=0);level=f.m15_mean12
 elif family=='M15_CLIMAX':
  signal=(f.m15_prev_range_ratio>1.5)&(side*(f.m15_prev_close-f.m15_prev_open)<0)&(side*(f.m15_close-f.m15_open)>0)&(side*(f.m15_close-f.m15_prev_close)>0);strength=(f.m15_prev_range_ratio-1.5).clip(lower=0);level=f.m15_prev_close
 elif family in ['ASIA_FALSE_BREAK','EUROPE_FALSE_BREAK','NY_OPENING_FADE','PREV_D1_FAILED_BREAK']:
  name={'ASIA_FALSE_BREAK':'asia','EUROPE_FALSE_BREAK':'europe','NY_OPENING_FADE':'nyopen','PREV_D1_FAILED_BREAK':'prior_d1'}[family];level=f[name+('_low' if side==1 else '_high')]
  extreme=f.low if side==1 else f.high;signal=(side*(level-extreme)>0)&(side*(f.close-level)>0)&body;strength=(side*(level-extreme)/a).clip(lower=0)
 elif family=='D1_OPEN_STRETCH':
  level=f.day_open;distance=side*(level-f.close)/f.adr20;signal=(distance>.25)&body;strength=(distance/.25-1).clip(lower=0)
 elif family=='M15_DOUBLE_SWEEP':signal=f['m15_double_'+str(side)].fillna(False).astype(bool);level=f.m15_p8low if side==1 else f.m15_p8high;strength=side*(level-(f.m15_low if side==1 else f.m15_high))/a
 elif family=='M15_BREAKER':signal=f['m15_breaker_'+str(side)].fillna(False).astype(bool);level=f.m15_p8low if side==1 else f.m15_p8high;strength=(side*(f.m15_close-level)/a).clip(lower=0)
 elif family=='H1_FVG_FILL':
  low=f['fvg_low_'+str(side)];high=f['fvg_high_'+str(side)];level=high if side==1 else low;signal=(f.low<=high)&(f.high>=low)&(side*(f.close-level)>0)&body;strength=(side*(level-(f.low if side==1 else f.high))/a).clip(lower=0)
 elif family=='H1_FAILED_BOS':
  known=f['h1_failed_'+str(side)].fillna(False).astype(bool);signal=known&(~known.shift().fillna(False).astype(bool));level=f.h1_dc_low if side==1 else f.h1_dc_high;strength=(side*(f.close-level)/a).clip(lower=0)
 elif family=='M15_COMPRESSION_FADE':
  level=f.m15_p8low if side==1 else f.m15_p8high;extreme=f.m15_low if side==1 else f.m15_high
  signal=f.m15_compress.fillna(False).astype(bool)&(side*(level-extreme)>0)&(side*(f.m15_close-level)>0)&(side*(f.m15_close-f.m15_open)>0);strength=(side*(level-extreme)/a).clip(lower=0)
 else:raise ValueError('UNKNOWN_FAMILY')
 remaining=20*60+55-(f.index.hour*60+f.index.minute);mask=signal.fillna(False)&f.d1_regime.notna()&(f.adr20>0)&(f.atr5>0)&(remaining>=60)&level.notna()&strength.notna()
 e=f.loc[mask,['open','close','high','low','atr5','adr20','year','session']].copy();e['anchor']=level[mask];e['level']=f.low[mask] if side==1 else f.high[mask];e['retest']=(f.open[mask]+f.close[mask])/2;e['strength_bin']=np.clip(np.searchsorted(GRID['strength'],strength[mask],side='right')-1,0,4)
 e['regime_bin']=np.where(side*f.d1_regime[mask]>0,0,np.where(side*f.d1_regime[mask]<0,1,2));minute=f.index.hour*60+f.index.minute;e['phase_minute']=(minute%360)[mask]
 flags=[pd.Series(True,index=f.index),(side*(f.close-f.open)>=.25*f.atr5)&body,side*(f.m15_context_close-f.m15_context_open)>0,((f.low<f.prior5low)&(f.close>f.prior5low)&body) if side==1 else ((f.high>f.prior5high)&(f.close<f.prior5high)&body),side*f.h1_bias>0]
 for i,q in enumerate(flags):e['confirm_'+str(i)]=q[mask].fillna(False).astype(bool)
 return e

def config(idx):return {k:v[i] for (k,v),i in zip(GRID.items(),idx)}

def filter_events(e,c):
 rg=GRID['regime'].index(c['regime']);co=GRID['confirmation'].index(c['confirmation']);p=GRID['session_phase'].index(c['session_phase']);phase=e.phase_minute
 phaseok=True if p==0 else (phase<60 if p==1 else (phase>=60)&(phase<120) if p==2 else (phase>=120)&(phase<240) if p==3 else phase>=240)
 return (e.strength_bin>=GRID['strength'].index(c['strength']))&e['confirm_'+str(co)]&(e.session==c['session_utc']//6)&phaseok&((e.regime_bin==rg-1) if rg else True)
