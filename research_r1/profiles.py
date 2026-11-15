"""Ex-post session descriptions; never a feature generator for replay."""
import pathlib,json,pandas as pd,numpy as np
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'results';OUT.mkdir(exist_ok=True)
b=pd.read_parquet(ROOT/'derived/xau_m5.parquet');w=b.index.tz_convert('Asia/Jakarta');b['date']=w.strftime('%Y-%m-%d');b['minute']=w.hour*60+w.minute;b['year']=w.year;b['dow']=w.dayofweek;b['month']=w.month
sessions={'MACRO_READ':(255,480),'ASIA_EARLY':(480,630),'ASIA_LATE':(630,780),'ASIA_FULL':(480,780),'LONDON':(840,1140),'NY_COMPARATOR':(1140,1440)}
records=[];excluded=[]
for label,(start,end) in sessions.items():
 for day,f in b[(b.minute>=start)&(b.minute<end)].groupby('date'):
  f=f[f.close.notna()];expected=(end-start)//5
  if len(f)<expected*(.5 if label=='MACRO_READ' else .9) or not len(f) or f.dow.iloc[0]>=5:
   excluded.append({'session':label,'date':day,'bars':len(f),'expected':expected});continue
  o=float(f.open.iloc[0]);c=float(f.close.iloc[-1]);hi=float(f.high.max());lo=float(f.low.min());ret=c-o;ran=hi-lo
  records.append({'session':label,'date':day,'year':int(f.year.iloc[0]),'month':int(f.month.iloc[0]),'dow':int(f.dow.iloc[0]),'open':o,'close':c,'high':hi,'low':lo,'range_usd':ran,'directional_return_usd':ret,'return_pct':ret/o*100,'spread_quote_weighted':float(np.average(f.spread,weights=f.ticks)),'realized_vol_pct':float(np.sqrt(np.sum(np.diff(np.log(f.close))**2))*100),'trend':abs(ret)/ran>=.5 if ran else False,'bars':len(f),'max_gap_ms':float(f.max_gap_ms.max())})
d=pd.DataFrame(records);d.to_csv(OUT/'session_daily_stats.csv',index=False);pd.DataFrame(excluded).to_csv(OUT/'session_exclusions.csv',index=False)
def summary(g):
 return pd.Series({'days':len(g),'mean_range_usd':g.range_usd.mean(),'mean_return_usd':g.directional_return_usd.mean(),'median_return_usd':g.directional_return_usd.median(),'return_p05':g.directional_return_usd.quantile(.05),'return_p95':g.directional_return_usd.quantile(.95),'positive_return_frequency':(g.directional_return_usd>0).mean(),'mean_spread_usd':g.spread_quote_weighted.mean(),'mean_realized_vol_pct':g.realized_vol_pct.mean(),'trend_frequency':g.trend.mean()})
for dims,name in [(['session'],'session_summary'),(['session','year'],'session_by_year'),(['session','dow'],'session_by_weekday'),(['session','month'],'session_by_month')]:
 d.groupby(dims).apply(summary,include_groups=False).to_csv(OUT/(name+'.csv'))
h=[]
for hour in range(24):
 f=b[(b.minute>=hour*60)&(b.minute<(hour+1)*60)]
 for day,g in f.groupby('date'):
  g=g[g.close.notna()]
  if len(g)<11 or g.dow.iloc[0]>=5:continue
  spread=float(np.average(g.spread,weights=g.ticks));ret=float(g.close.iloc[-1]-g.open.iloc[0])
  h.append({'hour_wib':hour,'date':day,'year':int(g.year.iloc[0]),'range_usd':float(g.high.max()-g.low.min()),'return_usd':ret,'spread_usd':spread,'long_net_1oz':ret-spread-.2-.06,'short_net_1oz':-ret-spread-.2-.06})
h=pd.DataFrame(h);h.to_csv(OUT/'hourly_daily_stats.csv',index=False);h.groupby('hour_wib').agg(days=('date','size'),mean_range=('range_usd','mean'),mean_return=('return_usd','mean'),mean_spread=('spread_usd','mean'),long_net_1oz=('long_net_1oz','mean'),short_net_1oz=('short_net_1oz','mean')).to_csv(OUT/'hourly_summary.csv')
# Nominal and real yields vs gold at the 15:30 New York quote anchor.
# Retrospective correlation only: actual historical publication/vintage unavailable.
macro=pd.read_csv(ROOT/'audit/treasury_daily_descriptive.csv',parse_dates=['date']);macro['quote_at']=pd.to_datetime([pd.Timestamp(x.date()).tz_localize('America/New_York')+pd.Timedelta(hours=15,minutes=30) for x in macro.date],utc=True)
gold=pd.DataFrame({'bar_available_at':b.index+pd.Timedelta(minutes=5),'gold':b.close.to_numpy()}).dropna().sort_values('bar_available_at')
merged=pd.merge_asof(macro.sort_values('quote_at'),gold,left_on='quote_at',right_on='bar_available_at',direction='backward',tolerance=pd.Timedelta(minutes=5))
for col in ['US2Y','US10Y','REAL10Y','BE10Y']:merged[col+'_change_bp']=merged[col].diff()*100
merged['gold_return_pct']=merged.gold.pct_change(fill_method=None)*100
merged['year']=merged.date.dt.year;merged.to_csv(OUT/'daily_macro_gold_descriptive.csv',index=False)
stats=[]
for label,g in [('ALL',merged)]+[(str(y),g) for y,g in merged.groupby('year')]:
 for col in ['US2Y','US10Y','REAL10Y','BE10Y']:
  x=g[[col+'_change_bp','gold_return_pct']].dropna();up=x[x[col+'_change_bp']>0]
  stats.append({'period':label,'factor':col,'n':len(x),'pearson_correlation':x.corr().iloc[0,1] if len(x)>2 else None,'factor_up_count':len(up),'gold_up_given_factor_up':float((up.gold_return_pct>0).mean()) if len(up) else None})
pd.DataFrame(stats).to_csv(OUT/'macro_gold_correlations_descriptive.csv',index=False)
print(d.groupby('session').apply(summary,include_groups=False).to_string())
