"""Isolated bid/ask tick execution. No broker, websocket, or trading imports."""
from numba import njit
import numpy as np,pandas as pd,pathlib,json
from build_bars import load_ticks
from signals import features,generate,SESSIONS,SETUPS
ROOT=pathlib.Path(__file__).resolve().parents[1]
@njit(cache=True)
def simulate(ts,bids,asks,sig,balance,peak,maxdd,spread_mult,slip,commission,compound=False,start_equity=10000.,holding_minutes=120):
 trades=np.zeros((len(sig),19));n=0;last_exit=-1;day=-1;count=0;rejects=np.zeros(5,np.int64)
 for k in range(len(sig)):
  st,expiry,end,side,islimit,limit,dist,target=sig[k]
  thisday=int((st+7*3600000)//86400000)
  if thisday!=day:day=thisday;count=0
  if (last_exit>=0 and st<last_exit+15*60000) or count>=3:rejects[0]+=1;continue
  i=np.searchsorted(ts,st,side='left')
  if i>=len(ts) or ts[i]-st>60000:rejects[1]+=1;continue
  entry=0.;fill=-1
  while i<len(ts) and ts[i]<min(expiry,end-15*60000):
   mid=(bids[i]+asks[i])/2;half=(asks[i]-bids[i])*spread_mult/2
   q=mid+side*half
   if not islimit or (side==1 and q<=limit) or (side==-1 and q>=limit):
    entry=limit if islimit else q+side*slip;fill=i;break
   i+=1
  if fill<0:rejects[2]+=1;continue
  # Commission is USD per lot round turn. One lot = 100 troy oz; step=0.01 lot=1 oz.
  risk=(balance if compound else start_equity)*.005
  units=np.floor(risk/(dist+2*slip+commission/100))
  margin_units=np.floor(balance*.20*200/entry)
  units=min(units,margin_units)
  if units<1 or balance<=0:rejects[3]+=1;continue
  stop=entry-side*dist;tp=entry+side*dist*target
  deadline=min(end,ts[fill]+holding_minutes*60000)
  exitprice=0.;reason=0;ex=fill;mae=0.;mfe=0.;intra_peak=balance;intra_low=balance;maxgap=0.;localdd=0.
  # Mark every tick in original order, including simultaneous timestamps.
  for j in range(fill,len(ts)):
   mid=(bids[j]+asks[j])/2;half=(asks[j]-bids[j])*spread_mult/2
   liquidation=mid-side*half
   if j>fill:maxgap=max(maxgap,ts[j]-ts[j-1])
   if side*(liquidation-stop)<=0:exitprice=liquidation-side*slip;reason=1
   elif side*(liquidation-tp)>=0:exitprice=tp-side*slip;reason=2
   elif ts[j]>=deadline:exitprice=liquidation-side*slip;reason=3
   elif j==len(ts)-1:exitprice=liquidation-side*slip;reason=4
   u=side*((exitprice if reason else liquidation)-entry)*units
   equity=balance-commission*units/(100 if reason else 200)+u
   peak=max(peak,equity);intra_peak=max(intra_peak,equity);intra_low=min(intra_low,equity)
   maxdd=max(maxdd,(peak-equity)/peak);localdd=max(localdd,(intra_peak-equity)/intra_peak)
   mae=min(mae,u);mfe=max(mfe,u)
   if reason:
    ex=j;break
  pnl=side*(exitprice-entry)*units-commission*units/100
  balance+=pnl;peak=max(peak,balance);maxdd=max(maxdd,(peak-balance)/peak)
  trades[n]=np.array([st,ts[fill],ts[ex],side,entry,exitprice,stop,tp,units,pnl,balance,mae,mfe,maxdd,reason,maxgap,intra_peak,intra_low,localdd])
  n+=1;count+=1;last_exit=ts[ex]
 return trades[:n],balance,peak,maxdd,rejects

COLS=['signal_ms','entry_ms','exit_ms','side','entry','exit','sl','tp','units_oz','net_profit','balance','mae_usd','mfe_usd','running_floating_dd','exit_reason','max_gap_ms','intra_peak_equity','intra_low_equity','local_floating_dd']
def run(cost='BASE',configs=None,compound=False,initial=10000.,outname=None,mode='CONTINUOUS',stop_scale=1.,holding_minutes=120):
 costs={'BASE':(1.,.10,6.),'STRESS15':(1.5,.25,6.),'STRESS20':(2.,.50,8.),'ZERO_DIAGNOSTIC':(0.,0.,0.)}
 spread,slip,commission=costs[cost]
 bars=features(pd.read_parquet(ROOT/'derived/xau_m5.parquet'))
 if configs is None:configs=[(s,setup,r) for s in SESSIONS for setup in SETUPS for r in [1.5,2.,3.]]
 states={};signals={};logs={};rejects={}
 quarantines=[]
 for session,setup,r in configs:
  key=f'{setup}_{session}_R{r}';signals[key]=generate(bars,session,setup,r)
  signals[key]['stop_distance']*=stop_scale
  start,end=SESSIONS[session];frame=bars[(bars.minute>=start)&(bars.minute<end)]
  coverage=frame.groupby('date').agg(valid_bars=('close','count'),max_gap=('max_gap_ms','max'),first=('first_tick','min'),last=('last_tick','max'))
  midnight=(pd.to_datetime(coverage.index).tz_localize('Asia/Jakarta').tz_convert('UTC').as_unit('ms').asi8)
  end_ms=midnight+end*60000
  first_after=bars['first_tick'].reindex(pd.to_datetime(end_ms,unit='ms',utc=True)).to_numpy()
  boundary=(coverage['first'].to_numpy()<=midnight+start*60000+60000)&(coverage['last'].to_numpy()>=end_ms-60000)&np.isfinite(first_after)&(first_after<=end_ms+60000)
  allowed=coverage[(coverage.valid_bars>=.95*(end-start)/5)&(coverage.max_gap<=300000)&boundary].index
  signals[key]=signals[key][signals[key].date.isin(allowed)]
  if r==configs[0][2] or setup=='MOMENTUM':
   for day,row in coverage[~coverage.index.isin(allowed)].iterrows():quarantines.append({'session':session,'date':day,'valid_bars':int(row.valid_bars),'max_gap_ms':float(row.max_gap)})
  states[key]=(initial,initial,0.);logs[key]=[];rejects[key]=np.zeros(5,np.int64)
 for file in sorted((ROOT/'data').glob('XAUUSD_*.parquet')):
  year=int(file.name[7:11]);month=int(file.name[12:14])
  if month==1 and ((mode=='PERIODS' and year in [2022,2024]) or (mode=='ANNUAL' and year>2019)):
   states={key:(initial,initial,0.) for key in states}
  ts,bid,ask=load_ticks(file);good=(ask>=bid)&(bid>0)&np.isfinite(bid)&np.isfinite(ask);ts,bid,ask=ts[good],bid[good],ask[good]
  for key,s in signals.items():
   q=s[(s.signal_ms>=ts[0])&(s.signal_ms<=ts[-1])]
   a=q[['signal_ms','expiry_ms','session_end_ms','direction','is_limit','limit','stop_distance','target_r']].to_numpy(dtype=np.float64)
   trades,balance,peak,dd,rejected=simulate(ts,bid,ask,a,*states[key],spread,slip,commission,compound,initial,holding_minutes)
   states[key]=(balance,peak,dd);rejects[key]+=rejected
   if len(trades):logs[key].append(pd.DataFrame(trades,columns=COLS))
  print(cost,file.name,flush=True)
 out=ROOT/'results'/(outname or (cost+('_COMPOUND' if compound else '')+('_100' if initial==100 else '')+('' if mode=='CONTINUOUS' else '_'+mode)));out.mkdir(parents=True,exist_ok=True)
 alltrades=[]
 for key,parts in logs.items():
  t=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame(columns=COLS)
  t['candidate']=key;t['cost']=cost;t['compound']=compound
  alltrades.append(t)
 pd.concat(alltrades,ignore_index=True).to_csv(out/'trades.csv.gz',index=False)
 pd.DataFrame(quarantines).drop_duplicates().to_csv(out/'data_quarantine.csv',index=False)
 (out/'states.json').write_text(json.dumps({key:{'balance':s[0],'peak':s[1],'floating_dd':s[2],'rejections':rejects[key].tolist()} for key,s in states.items()},indent=2))
 return out
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--cost',default='BASE');p.add_argument('--selected',action='store_true');p.add_argument('--compound',action='store_true');p.add_argument('--initial',type=float,default=10000.);p.add_argument('--mode',default='CONTINUOUS',choices=['CONTINUOUS','PERIODS','ANNUAL']);args=p.parse_args()
 configs=None
 if args.selected:configs=[tuple(x) for x in json.loads((ROOT/'results/selected_configs.json').read_text())]
 run(args.cost,configs,args.compound,args.initial,mode=args.mode)
