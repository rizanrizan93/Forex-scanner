"""Separate R2 offline account experiments using the audited R1 tick engine."""
import sys,pathlib,json,numpy as np,pandas as pd
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'research_r1'))
from replay import simulate,COLS
from build_bars import load_ticks
from signals_r2 import prepare,signals,candidates,make_id
OUT=ROOT/'r2_results';OUT.mkdir(exist_ok=True)
COSTS={'BASE':(1.,.10,6.),'STRESS15':(1.5,.25,6.),'STRESS20':(2.,.50,8.)}
def allowed_days():
 b=pd.read_parquet(ROOT/'derived/xau_m5.parquet');w=b.index.tz_convert('Asia/Jakarta');f=b[(w.hour>=8)&(w.hour<13)].copy();f['date']=f.index.tz_convert('Asia/Jakarta').strftime('%Y-%m-%d')
 q=f.groupby('date').agg(n=('close','count'),gap=('max_gap_ms','max'),first=('first_tick','min'),last=('last_tick','max'))
 mid=pd.to_datetime(q.index).tz_localize('Asia/Jakarta').tz_convert('UTC').as_unit('ms').asi8;end=mid+780*60000;after=b.first_tick.reindex(pd.to_datetime(end,unit='ms',utc=True)).to_numpy()
 ok=(q.n>=57)&(q.gap<=300000)&(q['first']<=mid+480*60000+60000)&(q['last']>=end-60000)&np.isfinite(after)&(after<=end+60000)
 q.assign(allowed=ok).to_csv(OUT/'data_quarantine.csv');return set(q[ok].index)
def enrich(f):
 f=f.copy()
 if (ROOT/'r2_audit/alfred_weekly_pit.csv').exists():
  a=pd.read_csv(ROOT/'r2_audit/alfred_weekly_pit.csv');a['available_at']=pd.to_datetime(a.available_at,utc=True);a=a.sort_values('available_at')
  d=pd.DataFrame({'decision_at':f.index});j=pd.merge_asof(d,a,left_on='decision_at',right_on='available_at',direction='backward',tolerance=pd.Timedelta(days=8))
  votes=np.sign(j[['DGS2_delta_bp','DGS10_delta_bp','DFII10_delta_bp']]).sum(axis=1,min_count=3)
  fresh=np.ones(len(j),dtype=bool)
  for series in ['DGS2','DGS10','DFII10']:
   observed=pd.to_datetime(j[series+'_observation_date'],utc=True);fresh&=((j.decision_at-observed)<=pd.Timedelta(days=10)).fillna(False).to_numpy()
  votes=votes.where(fresh)
  # Inverse-yield directional hypothesis, not an asserted causal law.
  f['macro_side']=-np.sign(votes.to_numpy());f['macro_available_at']=j.available_at.to_numpy()
  for col in ['DGS2','DGS10','DFII10','DGS2_delta_bp','DGS10_delta_bp','DFII10_delta_bp']:f['macro_'+col]=j[col].to_numpy()
  for col in ['DGS2','DGS10','DFII10','DGS2_delta_bp','DGS10_delta_bp','DFII10_delta_bp']:f.loc[~fresh,'macro_'+col]=np.nan
 else:f['macro_side']=np.nan
 if (ROOT/'r2_audit/bls_release_calendar.csv').exists():
  a=pd.read_csv(ROOT/'r2_audit/bls_release_calendar.csv')
  if (ROOT/'r2_audit/fomc_releases.csv').exists():
   fed=pd.read_csv(ROOT/'r2_audit/fomc_releases.csv');a=pd.concat([a,fed],ignore_index=True)
  a['known_at']=pd.to_datetime(a.available_after_buffer,utc=True);a=a.sort_values('known_at')
  j=pd.merge_asof(pd.DataFrame({'decision_at':f.index}),a,left_on='decision_at',right_on='known_at',direction='backward',tolerance=pd.Timedelta(hours=24))
  f['post_major_news']=j.known_at.notna().to_numpy();f['last_news_type']=j.series.to_numpy()
 else:f['post_major_news']=False
 return f
def run(configs=None,cost='BASE',mode='PERIODS',outname='GRID',compound=False,initial=10000.):
 f=enrich(prepare());configs=candidates() if configs is None else configs;allowed=allowed_days();arrays={};states={};parts={};rej={}
 predictions=pd.read_csv(OUT/'ml_predictions.csv.gz') if any(c.get('prediction_key') for c in configs) else None
 for i,c in enumerate(configs):
  key=make_id(c)+c.get('suffix','');s=signals(f,c);s=s[s.date.isin(allowed)]
  if c.get('prediction_key'):
   pp=predictions[predictions.model==c['prediction_key']].set_index('signal_ms');s=s.join(pp[['direction','expected_net_r']].rename(columns={'direction':'model_direction'}),on='signal_ms');s=s[s.expected_net_r>c['threshold']].copy();s['direction']=s.model_direction
  if c.get('macro'):
   side=f.macro_side.reindex(pd.to_datetime(s.signal_ms,unit='ms',utc=True)).to_numpy();s=s[(side==s.direction.to_numpy())]
  if c.get('news') in ['AFTER','QUIET']:
   post=f.post_major_news.reindex(pd.to_datetime(s.signal_ms,unit='ms',utc=True)).to_numpy();s=s[post if c['news']=='AFTER' else ~post]
  if c.get('vol_veto'):
   v=f.reindex(pd.to_datetime(s.signal_ms,unit='ms',utc=True));quiet=(v.h1_atr<=v.h1_atr_p95)&((v.pre_hi-v.pre_lo)<=2.5*v.h1_atr);s=s[quiet.to_numpy()]
  arrays[key]=s[['signal_ms','expiry_ms','session_end_ms','direction','is_limit','limit','stop_distance','target_r']].to_numpy(dtype=float);states[key]=(initial,initial,0.);parts[key]=[];rej[key]=np.zeros(5,np.int64)
  if i%25==0:print('SIGNALS',i,len(configs),flush=True)
 for p in sorted((ROOT/'data').glob('XAUUSD_*.parquet')):
  year=int(p.name[7:11]);month=int(p.name[12:14])
  if month==1 and ((mode=='PERIODS' and year in [2022,2024]) or (mode=='ANNUAL' and year>2019)):states={k:(initial,initial,0.) for k in states}
  ts,bid,ask=load_ticks(p)
  for key,a in arrays.items():
   lo=np.searchsorted(a[:,0],ts[0],side='left');hi=np.searchsorted(a[:,0],ts[-1],side='right');s=a[lo:hi]
   t,balance,peak,dd,r=simulate(ts,bid,ask,s,*states[key],*COSTS[cost],compound,initial,300)
   states[key]=(balance,peak,dd);rej[key]+=r
   if len(t):parts[key].append(pd.DataFrame(t,columns=COLS))
  print(outname,cost,p.name,flush=True)
 dest=OUT/outname;dest.mkdir(exist_ok=True);out=[]
 for key,pp in parts.items():
  t=pd.concat(pp,ignore_index=True) if pp else pd.DataFrame(columns=COLS);t['candidate']=key;t['cost']=cost;t['compound']=compound;out.append(t)
 pd.concat(out,ignore_index=True).to_csv(dest/'trades.csv.gz',index=False)
 (dest/'configs.json').write_text(json.dumps(configs,indent=2));(dest/'states.json').write_text(json.dumps({k:{'ending':s[0],'peak':s[1],'floating_dd':s[2],'rejections':rej[k].tolist()} for k,s in states.items()},indent=2))
 return dest
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--configs');p.add_argument('--cost',default='BASE');p.add_argument('--mode',default='PERIODS');p.add_argument('--name',default='GRID');p.add_argument('--compound',action='store_true');a=p.parse_args()
 run(json.loads(pathlib.Path(a.configs).read_text()) if a.configs else None,a.cost,a.mode,a.name,a.compound)
