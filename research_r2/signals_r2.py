"""Causal M15/H1 indicators, price structure and one-currency USD proxy."""
import pathlib,numpy as np,pandas as pd
ROOT=pathlib.Path(__file__).resolve().parents[1]
WINDOWS={'EARLY':(480,630),'LATE':(630,750),'FULL':(480,750)}
FAMILIES=['RSI_FADE','BB_RANGE','TREND_PULLBACK','DONCHIAN','NY_SWEEP','OPEN_FADE','OPEN_BREAK','PRE_CONTINUE','PRE_REVERSE','RANGE_MEAN','HTF_FVG','TIME_LONG','TIME_SHORT']
def indicator(d):
 d=d.copy();close=d.close;prev=close.shift();tr=pd.concat([d.high-d.low,(d.high-prev).abs(),(d.low-prev).abs()],axis=1).max(axis=1)
 d['atr']=tr.ewm(alpha=1/14,adjust=False,min_periods=28).mean()
 delta=close.diff();u=delta.clip(lower=0).ewm(alpha=1/14,adjust=False,min_periods=28).mean();v=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False,min_periods=28).mean()
 d['rsi']=100-100/(1+u/v.replace(0,np.nan))
 for n in [20,50,200]:d[f'ema{n}']=close.ewm(span=n,adjust=False,min_periods=n).mean()
 plus=d.high.diff();minus=-d.low.diff();p=plus.where((plus>minus)&(plus>0),0);m=minus.where((minus>plus)&(minus>0),0)
 p=p.ewm(alpha=1/14,adjust=False,min_periods=28).mean();m=m.ewm(alpha=1/14,adjust=False,min_periods=28).mean();dx=100*(p-m).abs()/(p+m).replace(0,np.nan);d['adx']=dx.ewm(alpha=1/14,adjust=False,min_periods=28).mean()
 d['mean']=close.rolling(20,min_periods=20).mean();d['sd']=close.rolling(20,min_periods=20).std(ddof=0)
 d['don_hi']=d.high.shift().rolling(20).max();d['don_lo']=d.low.shift().rolling(20).min();return d
def aggregate(b,rule,n):
 d=b.resample(rule,closed='left',label='right').agg(open=('open','first'),high=('high','max'),low=('low','min'),close=('close','last'),n=('close','count'))
 d=d[d.n==n].drop(columns='n');return indicator(d)
def prepare(x=None,e=None):
 b=(pd.read_parquet(ROOT/'derived/xau_m5.parquet') if x is None else x).copy();end=b.index+pd.Timedelta(minutes=5)
 out=b.copy();out.index=end
 for prefix,rule,n in [('m15','15min',3),('h1','1h',12)]:
  a=aggregate(b,rule,n);a['age_source_ms']=a.index.as_unit('ms').asi8
  if prefix=='h1':a['atr_p95']=a.atr.shift().rolling(200,min_periods=100).quantile(.95)
  joined=a.reindex(end,method='ffill');joined.index=end
  cols=['atr','rsi','ema20','ema50','ema200','adx','mean','sd','don_hi','don_lo','close','age_source_ms']
  for c in cols:out[prefix+'_'+c]=joined[c]
  if prefix=='h1':out['h1_atr_p95']=joined.atr_p95
  out[prefix+'_age_ms']=end.as_unit('ms').asi8-out[prefix+'_age_source_ms']
 for n in [3,6,12]:out[f'hi{n}']=b.high.shift().rolling(n).max().to_numpy();out[f'lo{n}']=b.low.shift().rolling(n).min().to_numpy()
 out['prev_close']=b.close.shift().to_numpy();out['prev_high']=b.high.shift().to_numpy();out['prev_low']=b.low.shift().to_numpy()
 out['fvg_up']=b.low.to_numpy()>b.high.shift(2).to_numpy()+.02*out.h1_atr;out['fvg_dn']=b.high.to_numpy()<b.low.shift(2).to_numpy()-.02*out.h1_atr
 out['up_limit']=(b.low.to_numpy()+b.high.shift(2).to_numpy())/2;out['dn_limit']=(b.high.to_numpy()+b.low.shift(2).to_numpy())/2
 local=end.tz_convert('Asia/Jakarta');out['date']=local.strftime('%Y-%m-%d');out['minute']=local.hour*60+local.minute;out['year']=local.year
 good=b.close.notna()&(b.max_gap_ms<=60000)&(b.ticks>0)
 out['valid']=good.rolling(12,min_periods=12).min().fillna(0).astype(bool).to_numpy()&(out.h1_age_ms<=7200000)&(out.m15_age_ms<=1200000)&out.h1_ema200.notna()
 # Aggregate windows only become usable strictly after their final boundary.
 raw=b.copy();l=b.index.tz_convert('Asia/Jakarta');raw['date']=l.strftime('%Y-%m-%d');raw['minute']=l.hour*60+l.minute
 opening=raw[(raw.minute>=480)&(raw.minute<510)].groupby('date').agg(or_hi=('high','max'),or_lo=('low','min'),or_open=('open','first'),or_close=('close','last'),or_n=('close','count'))
 pre=raw[(raw.minute>=255)&(raw.minute<480)].groupby('date').agg(pre_hi=('high','max'),pre_lo=('low','min'),pre_open=('open','first'),pre_close=('close','last'),pre_n=('close','count'))
 out=out.join(opening,on='date').join(pre,on='date')
 ny=raw[(raw.minute>=1140)&raw.close.notna()].groupby('date').agg(ny_hi=('high','max'),ny_lo=('low','min'),ny_open=('open','first'),ny_close=('close','last'),ny_n=('close','count'))
 mapping={}
 for day in sorted(out.date.unique()):
  prior=ny[ny.index<day];mapping[day]=prior.iloc[-1].to_dict() if len(prior) and (pd.Timestamp(day)-pd.Timestamp(prior.index[-1])).days<=4 else {}
 for c in ['ny_hi','ny_lo','ny_open','ny_close','ny_n']:out[c]=out.date.map({d:v.get(c,np.nan) for d,v in mapping.items()})
 if e is None and (ROOT/'derived/eur_m5.parquet').exists():e=pd.read_parquet(ROOT/'derived/eur_m5.parquet')
 if e is not None:
  e=e.copy();e.index=e.index+pd.Timedelta(minutes=5);e['eur_ret1h']=e.eur/e.eur.shift(12)-1
  joined=e[['eur_ret1h','quote_ms']].reindex(end,method='ffill');out['eur_ret1h']=joined.eur_ret1h.to_numpy();out['eur_age_ms']=end.as_unit('ms').asi8-joined.quote_ms.to_numpy()
 else:out['eur_ret1h']=np.nan;out['eur_age_ms']=np.nan
 return out
def make_id(c):return f"{c['family']}_{c['window']}_SL{c['stop']}_TP{c['target']}_USD{c['usd']}"
def candidates():return [{'family':f,'window':w,'stop':s,'target':r,'usd':u} for f in FAMILIES for w in WINDOWS for s in [.75,1.25] for r in [1.,2.] for u in [0,1]]
def signals(f,c):
 if c['family']=='R1_FVG_REF':
  from signals import features as old_features,generate as old_generate
  old=old_features(pd.read_parquet(ROOT/'derived/xau_m5.parquet'));s=old_generate(old,'ASIA_FULL','TREND_FVG',3.);s['stop_distance']*=7/3;s['id']=make_id(c);return s
 family=c['family'];trendup=(f.h1_close>f.h1_ema200)&(f.h1_ema50>f.h1_ema200);trenddn=(f.h1_close<f.h1_ema200)&(f.h1_ema50<f.h1_ema200)
 up=f.close>f.prev_high;dn=f.close<f.prev_low;body=f.close-f.open
 if family=='RSI_FADE':buy=(f.m15_rsi<35)&up;sell=(f.m15_rsi>65)&dn
 elif family=='BB_RANGE':buy=(f.low<f.m15_mean-2*f.m15_sd)&(f.close>f.m15_mean-2*f.m15_sd)&(f.m15_adx<25)&up;sell=(f.high>f.m15_mean+2*f.m15_sd)&(f.close<f.m15_mean+2*f.m15_sd)&(f.m15_adx<25)&dn
 elif family=='TREND_PULLBACK':buy=trendup&(f.low<=f.m15_ema20)&(f.close>f.m15_ema20)&up;sell=trenddn&(f.high>=f.m15_ema20)&(f.close<f.m15_ema20)&dn
 elif family=='DONCHIAN':buy=trendup&(f.close>f.m15_don_hi+.05*f.h1_atr)&(f.m15_adx>=20)&(body>.1*f.h1_atr);sell=trenddn&(f.close<f.m15_don_lo-.05*f.h1_atr)&(f.m15_adx>=20)&(body<-.1*f.h1_atr)
 elif family=='NY_SWEEP':buy=(f.ny_n>=54)&(f.low<f.ny_lo-.05*f.h1_atr)&(f.close>f.ny_lo)&(body>0);sell=(f.ny_n>=54)&(f.high>f.ny_hi+.05*f.h1_atr)&(f.close<f.ny_hi)&(body<0)
 elif family=='OPEN_FADE':
  ready=(f.minute>=510)&(f.or_n==6);move=f.or_close-f.or_open
  buy=ready&(move<-.3*f.h1_atr)&(f.close>f.hi3);sell=ready&(move>.3*f.h1_atr)&(f.close<f.lo3)
 elif family=='OPEN_BREAK':buy=(f.minute>=510)&(f.or_n==6)&trendup&(f.close>f.or_hi+.05*f.h1_atr)&(body>.1*f.h1_atr);sell=(f.minute>=510)&(f.or_n==6)&trenddn&(f.close<f.or_lo-.05*f.h1_atr)&(body<-.1*f.h1_atr)
 elif family=='PRE_CONTINUE':
  move=f.pre_close-f.pre_open;buy=(f.pre_n>=24)&(move>.3*f.h1_atr)&trendup&(f.close>f.hi6);sell=(f.pre_n>=24)&(move<-.3*f.h1_atr)&trenddn&(f.close<f.lo6)
 elif family=='PRE_REVERSE':
  move=f.pre_close-f.pre_open;ran=f.pre_hi-f.pre_lo;buy=(f.pre_n>=24)&(move<-.6*ran)&(ran>f.h1_atr)&(f.low<f.pre_lo)&(f.close>f.pre_lo)&up;sell=(f.pre_n>=24)&(move>.6*ran)&(ran>f.h1_atr)&(f.high>f.pre_hi)&(f.close<f.pre_hi)&dn
 elif family=='RANGE_MEAN':buy=(f.close<f.m15_mean-1.5*f.m15_atr)&(f.m15_rsi<35)&(f.m15_adx<20)&up;sell=(f.close>f.m15_mean+1.5*f.m15_atr)&(f.m15_rsi>65)&(f.m15_adx<20)&dn
 elif family=='HTF_FVG':buy=trendup&f.fvg_up&(body>.15*f.h1_atr);sell=trenddn&f.fvg_dn&(body<-.15*f.h1_atr)
 elif family=='TIME_LONG':buy=f.minute==WINDOWS[c['window']][0]+5;sell=pd.Series(False,index=f.index)
 elif family=='TIME_SHORT':buy=pd.Series(False,index=f.index);sell=f.minute==WINDOWS[c['window']][0]+5
 else:raise ValueError(family)
 if c['usd']:
  fresh=(f.eur_age_ms>=0)&(f.eur_age_ms<=600000);buy=buy&fresh&(f.eur_ret1h>=.00015);sell=sell&fresh&(f.eur_ret1h<=-.00015)
 start,end=WINDOWS[c['window']];mask=f.valid&(f.minute>=start)&(f.minute<end)&(buy|sell)&(f.h1_atr>0)
 s=f[mask].copy();s['direction']=np.where(buy[mask],1,-1);s['signal_ms']=s.index.as_unit('ms').asi8;s['expiry_ms']=s.signal_ms+15*60000
 midnight=pd.to_datetime(s.date).dt.tz_localize('Asia/Jakarta').dt.tz_convert('UTC');s['session_end_ms']=(midnight+pd.Timedelta(hours=13)).astype('int64')//1000000
 s['is_limit']=int(family=='HTF_FVG');s['limit']=np.where(s.direction==1,s.up_limit,s.dn_limit);s['stop_distance']=c['stop']*s.h1_atr
 if family in ['HTF_FVG','NY_SWEEP']:
  anchor=s['limit'] if family=='HTF_FVG' else s.close;extreme=np.where(s.direction==1,s.low,s.high);s['stop_distance']=np.maximum(s.stop_distance,np.abs(anchor-extreme)+.05*s.h1_atr)
 s['target_r']=c['target'];s['id']=make_id(c)
 return s[['signal_ms','expiry_ms','session_end_ms','direction','is_limit','limit','stop_distance','target_r','date','id']]
