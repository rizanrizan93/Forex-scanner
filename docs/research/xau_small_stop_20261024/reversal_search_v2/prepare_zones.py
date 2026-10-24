from pathlib import Path
import pandas as pd,numpy as np,json,hashlib
P=Path('reversal_search_v2');P.mkdir(exist_ok=True)
source=Path('datasets/data_audit/XAUUSD_m1.csv')
d=pd.read_csv(source,usecols=['timestamp','open','high','low','close','spread']);d.timestamp=pd.to_datetime(d.timestamp,utc=True)
d=d.sort_values('timestamp').reset_index(drop=True);assert d.timestamp.is_unique
t=d.timestamp.astype('int64').to_numpy()//10**9;n=len(d)
valid=np.ones(n,bool);valid[:24000]=False
gaps=np.flatnonzero(np.diff(t)>72*3600)+1
for i in gaps:valid[max(0,i-1440):min(n,i+24000)]=False
with open(P/'prices.bin','wb') as f:
 np.array([n],dtype='<i8').tofile(f);t.astype('<i8').tofile(f)
 for name in ['open','high','low','close','spread']:d[name].to_numpy('<f8').tofile(f)
 valid.astype('u1').tofile(f)
def bars(minutes):
 freq=f'{minutes}min';b=d.set_index('timestamp').resample(freq,label='right',closed='left').agg({'open':'first','high':'max','low':'min','close':'last'})
 counts=d.set_index('timestamp').close.resample(freq,label='right',closed='left').count();b=b[counts>=minutes*.8].copy()
 tr=pd.concat([b.high-b.low,(b.high-b.close.shift()).abs(),(b.low-b.close.shift()).abs()],axis=1).max(axis=1)
 b['atr']=tr.rolling(14).mean();b['e20']=b.close.ewm(span=20,adjust=False).mean();b['e50']=b.close.ewm(span=50,adjust=False).mean()
 b['slope']=(b.e20-b.e20.shift(3))/b.atr;b['eff']=(b.close-b.close.shift(10)).abs()/b.close.diff().abs().rolling(10).sum()
 b['stamp']=b.index.astype('int64')//10**9
 return b
b15,b60,b240=bars(15),bars(60),bars(240)
# Context only available from fully closed H1/H4; merge_asof never sees next bar.
context=pd.merge_asof(b60[['stamp','close','e20','slope','eff','atr']].reset_index(drop=True),b240[['stamp','close','e20','slope']].reset_index(drop=True),on='stamp',suffixes=('_h1','_h4'))
ct=context.stamp.to_numpy();contexts=context.to_dict('records')
zones=[];last={};families={}
def add(fam,stamp,side,lo,hi,a,strength,compression):
 if not np.isfinite([lo,hi,a,strength,compression]).all() or hi-lo<=.015*a or hi-lo>3*a or a<=0:return
 j=np.searchsorted(t,stamp);ci=np.searchsorted(ct,stamp,side='right')-1
 if ci<0 or j>=n or not valid[j] or t[j]-stamp>60:return
 ctx=contexts[ci]
 if not np.isfinite(list(ctx.values())).all():return
 # Restrict redundant registrations of an essentially identical price zone.
 key=(fam,side);center=(lo+hi)/2
 if key in last and stamp-last[key][0]<4*3600 and abs(center-last[key][1])<.25*a:return
 last[key]=(stamp,center)
 ah1=side*(ctx['close_h1']-ctx['e20_h1'])>0;ah4=side*(ctx['close_h4']-ctx['e20_h4'])>0
 if fam not in families:families[fam]=len(families)
 zones.append([len(zones),families[fam],int(j),int(stamp),side,lo,hi,a,int(ah1),int(ah4),side*ctx['slope_h1'],ctx['eff'],abs(ctx['close_h1']-ctx['e20_h1'])/ctx['atr'],strength,compression])
for minutes,b in [(15,b15),(60,b60),(240,b240)]:
 a=b.atr.to_numpy();op=b.open.to_numpy();hi=b.high.to_numpy();lo=b.low.to_numpy();cl=b.close.to_numpy();ts=b.stamp.to_numpy();e20=b.e20.to_numpy();e50=b.e50.to_numpy()
 roll={k:(b.high.shift().rolling(k).max().to_numpy(),b.low.shift().rolling(k).min().to_numpy()) for k in [8,12,24,48]}
 for i in range(60,len(b)):
  if ts[i]-ts[i-1]!=minutes*60:continue
  atr=a[i];body=abs(cl[i]-op[i]);side=1 if cl[i]>op[i] else -1;strength=body/atr
  compress=(roll[8][0][i]-roll[8][1][i])/(a[i-1]*np.sqrt(8))
  tf=f'M{minutes}' if minutes==15 else f'H{minutes//60}'
  if minutes==60:
   for span,ema in [(20,e20[i]),(50,e50[i])]:
    if abs(cl[i]-ema)>=.6*atr:
     add(f'EMA{span}_H1',ts[i],1 if cl[i]>ema else -1,ema-.15*atr,ema+.15*atr,atr,abs(cl[i]-ema)/atr,compress)
   for k in [1.,1.5,2.]:
    # Pullbacks into a volatility band, placed from outside the band only.
    for dd in [-1,1]:
     center=e20[i]-dd*k*atr
     if dd*(cl[i]-center)>.25*atr:add(f'RESIDUAL_{k:g}_H1',ts[i],dd,center-.15*atr,center+.15*atr,atr,strength,compress)
  # Pullback into the already closed impulse body: 38%-62% retracement pocket.
  if strength>=.65:
   base=min(cl[i],op[i]);top=max(cl[i],op[i])
   add('IMPULSE_'+tf,ts[i],side,base+.382*(top-base),base+.618*(top-base),atr,strength,compress)
  # Breakout/retest after acceptance beyond a pre-existing range edge.
  for k in [12,24]:
   ph,pl=roll[k][0][i],roll[k][1][i]
   if cl[i]>ph+.1*atr and cl[i-1]<=roll[k][0][i-1]:
    add(f'BREAK{k}_'+tf,ts[i],1,ph-.1*atr,ph+.1*atr,atr,(cl[i]-ph)/atr,compress)
   if cl[i]<pl-.1*atr and cl[i-1]>=roll[k][1][i-1]:
    add(f'BREAK{k}_'+tf,ts[i],-1,pl-.1*atr,pl+.1*atr,atr,(pl-cl[i])/atr,compress)
  # Liquidity sweep and closed reclaim; retrace order exists only after response.
  ph,pl=roll[24][0][i],roll[24][1][i]
  if hi[i]>ph+.05*atr and cl[i]<ph and side==-1 and strength>=.3:
   add('SWEEP_'+tf,ts[i],-1,max(op[i],cl[i]),hi[i],atr,strength,compress)
   add('RECLAIM_POCKET_'+tf,ts[i],-1,cl[i]+.25*(hi[i]-cl[i]),cl[i]+.55*(hi[i]-cl[i]),atr,strength,compress)
  if lo[i]<pl-.05*atr and cl[i]>pl and side==1 and strength>=.3:
   add('SWEEP_'+tf,ts[i],1,lo[i],min(op[i],cl[i]),atr,strength,compress)
   add('RECLAIM_POCKET_'+tf,ts[i],1,cl[i]-.55*(cl[i]-lo[i]),cl[i]-.25*(cl[i]-lo[i]),atr,strength,compress)
  # Displacement from a compact base.
  if hi[i-1]-lo[i-1]<=.9*a[i-1] and strength>=.8:
   if side==1 and cl[i]>hi[i-1]:add('BASE_'+tf,ts[i],1,lo[i-1],max(op[i-1],cl[i-1]),atr,strength,compress)
   if side==-1 and cl[i]<lo[i-1]:add('BASE_'+tf,ts[i],-1,min(op[i-1],cl[i-1]),hi[i-1],atr,strength,compress)
  if ts[i]-ts[i-2]==2*minutes*60:
   if lo[i]>hi[i-2] and cl[i-1]>op[i-1]:add('FVG_'+tf,ts[i],1,hi[i-2],lo[i],atr,abs(cl[i-1]-op[i-1])/a[i-1],compress)
   if hi[i]<lo[i-2] and cl[i-1]<op[i-1]:add('FVG_'+tf,ts[i],-1,hi[i],lo[i-2],atr,abs(cl[i-1]-op[i-1])/a[i-1],compress)
 print('prepared',tf,'zones',len(zones),flush=True)
columns=['zone_id','family','created_i','created_s','side','lo','hi','atr','h1','h4','slope','eff','dist','strength','compression']
pd.DataFrame(zones,columns=columns).to_csv(P/'zones.csv',index=False)
(P/'families.json').write_text(json.dumps(families,indent=2))
protocol=dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),n=n,first=str(d.timestamp.iloc[0]),last=str(d.timestamp.iloc[-1]),family_count=len(families),zone_count=len(zones),primary_gates=dict(train_n=100,train_pf=1.3,validation_n=30,validation_pf=1.1,review_n=40,review_pf=1.2,all_cost2_pf=1.0,min_rr=1.0,accuracy_target=.55),periods={'train':'2019-2022','validation':'2023','review':'2024-2025','diagnostic':'2026 Q1'},warning='Exploratory: all periods previously observed by related research; cannot certify novelty or independent validation.',features='Price-derived only; no point-in-time macro or true order book; no volume claim.')
(P/'base_preparation_manifest.json').write_text(json.dumps(protocol,indent=2))
print(protocol,flush=True)
