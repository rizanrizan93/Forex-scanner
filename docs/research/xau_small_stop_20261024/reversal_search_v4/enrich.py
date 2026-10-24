from pathlib import Path
import pandas as pd,numpy as np,json
P=Path('reversal_search_v4')
d=pd.read_csv('datasets/data_audit/XAUUSD_m1.csv',usecols=['timestamp','open','high','low','close']);d.timestamp=pd.to_datetime(d.timestamp,utc=True);d=d.set_index('timestamp')
def bars(freq,minimum,span=20):
 b=d.resample(freq,label='right',closed='left').agg({'open':'first','high':'max','low':'min','close':'last'});b=b[d.close.resample(freq,label='right',closed='left').count()>=minimum].copy();tr=pd.concat([b.high-b.low,(b.high-b.close.shift()).abs(),(b.low-b.close.shift()).abs()],axis=1).max(axis=1);b['atr']=tr.rolling(14).mean();b['ema']=b.close.ewm(span=span,adjust=False).mean();b['slope']=(b.ema-b.ema.shift(3))/b.atr;b['eff']=(b.close-b.close.shift(10)).abs()/b.close.diff().abs().rolling(10).sum();b['vol']=b.atr/b.atr.rolling(30).median();b['dist']=(b.close-b.ema)/b.atr;b['stamp']=b.index.astype('int64')//10**9;return b.iloc[span:]
z=pd.read_csv(P/'zones.csv');f=z[['zone_id','created_s','side','h1','h4','eff','strength','dist','compression']].sort_values('created_s')
for prefix,b in [('d',bars('1D',1152)),('h',bars('4h',192)),('w',bars('W-MON',4608)),('m',bars('MS',17280,12))]:
 right=b[['stamp','close','ema','slope','eff','vol','dist','atr']].reset_index(drop=True);right=right.rename(columns={c:prefix+'_'+c for c in right.columns});f=pd.merge_asof(f,right,left_on='created_s',right_on=prefix+'_stamp')
f=f.sort_values('zone_id');side=f.side;a=f.h1.astype(bool)&f.h4.astype(bool);dt=side*(f.d_close-f.d_ema)>0;wt=side*(f.w_close-f.w_ema)>0;mt=side*(f.m_close-f.m_ema)>0;ds=side*f.d_slope
filters=[np.ones(len(f),bool),a,a&dt,a&(ds>=.05),a&(f.h_eff>=.2)&(ds>=.05),a&dt&wt&mt,a&(f.eff>=.25),wt,wt&dt&f.h1.astype(bool),mt&dt&f.h1.astype(bool),a&(f.h_eff<.2),f.h1.astype(bool)&(side*f.d_dist<=-1),a&(f.h_vol>=1.2),a&(f.strength>=1.2),dt&(ds>=.05)&(f.strength>=1),a&dt&(f.compression<=1),a,a&dt,f.h4.astype(bool)]
mask=np.zeros(len(f),np.uint32)
for i,v in enumerate(filters):mask[np.asarray(v,dtype=bool)]|=np.uint32(1<<i)
mask.astype('<u4').tofile(P/'masks.bin');f.d_atr.to_numpy('<f8').tofile(P/'daily_atr.bin');f.to_csv(P/'features.csv',index=False)
names=['ANY','H1_H4','H1_H4_D20','H1_H4_D_SLOPE','H1_H4_H4ER_D_SLOPE','H1_H4_D_W_M','H1_H4_H1ER','W_TREND','W_D_H1','M_D_H1','H1_H4_RANGE','H1_FLIP_D_EXTREME','H1_H4_VOL_EXPAND','H1_H4_STRONG','D_SLOPE_STRONG','H1_H4_D_COMPRESSED','H1_H4_DATR_GE_TARGET','H1_H4_D_DATR_GE_HALF_TARGET','H4_DATR_GE_HALF_TARGET']
(P/'profiles.json').write_text(json.dumps(dict(enumerate(names)),indent=2));print('features',len(f))
