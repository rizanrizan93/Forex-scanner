"""Causal walk-forward expected-net-R models; no probability/accuracy claims."""
import sys,pathlib,json,numpy as np,pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'research_r1'))
from run_r2 import enrich
from signals_r2 import prepare
OUT=ROOT/'r2_results'
PRICE=['trend_h1','distance_h1','m15_rsi','m15_adx','pre_move','pre_range','ny_move','opening_move','eur_bp','atr_pct','spread_atr','weekday']
MACRO=['macro_DGS2_delta_bp','macro_DGS10_delta_bp','macro_DFII10_delta_bp','macro_DFII10','post_news']
def build():
 f=enrich(prepare());f=f[(f.minute==485)&f.valid].copy();atr=f.h1_atr
 f['trend_h1']=(f.h1_ema50-f.h1_ema200)/atr;f['distance_h1']=(f.close-f.h1_ema50)/atr;f['pre_move']=(f.pre_close-f.pre_open)/atr;f['pre_range']=(f.pre_hi-f.pre_lo)/atr;f['ny_move']=(f.ny_close-f.ny_open)/atr;f['opening_move']=(f.close-f.open)/atr;f['eur_bp']=f.eur_ret1h*10000;f['atr_pct']=atr/f.close;f['spread_atr']=f.spread/atr;f['weekday']=f.index.tz_convert('Asia/Jakarta').dayofweek;f['post_news']=f.post_major_news.astype(int);f['signal_ms']=f.index.as_unit('ms').asi8
 f=f[(f.pre_n>=24)&(f.ny_n>=54)&(f.eur_age_ms<=600000)].dropna(subset=PRICE)
 labels=pd.read_csv(OUT/'ML_LABELS/trades.csv.gz');labels['net_r']=labels.net_profit/(labels.units_oz*((labels.entry-labels.sl).abs()+.26));labels['side_name']=np.where(labels.side==1,'long','short')
 y=labels.pivot(index='signal_ms',columns='side_name',values='net_r');known=labels.groupby('signal_ms').exit_ms.max().rename('target_available_ms')
 data=f.set_index('signal_ms').join(y).join(known).dropna(subset=['long','short']);data.to_csv(OUT/'ml_training_panel.csv.gz');predictions=[];audit=[];configs=[]
 for algorithm in ['RIDGE','BOOST']:
  for feature_set in ['PRICE','FULL']:
   cols=PRICE+(MACRO if feature_set=='FULL' else []);d=data.dropna(subset=cols).copy();key=algorithm+'_'+feature_set
   for test_year,train_end in [(2020,2020),(2021,2021),(2022,2022)]:
    cutoff=pd.Timestamp(f'{train_end}-01-01',tz='Asia/Jakarta').timestamp()*1000
    train=d[(d.year<train_end)&(d.target_available_ms<cutoff)]
    test=d[(d.year==test_year) if test_year<2022 else (d.year>=2022)]
    if len(train)<180 or not len(test):continue
    values={}
    for side in ['long','short']:
     model=make_pipeline(StandardScaler(),Ridge(alpha=100.)) if algorithm=='RIDGE' else HistGradientBoostingRegressor(max_iter=80,max_leaf_nodes=5,min_samples_leaf=40,l2_regularization=20,learning_rate=.04,random_state=125)
     model.fit(train[cols],train[side]);values[side]=model.predict(test[cols])
     info={'model':key,'side':side,'train_end_exclusive':train_end,'train_rows':len(train),'test_rows':len(test),'feature_names':cols,'max_training_target_available_ms':float(train.target_available_ms.max()),'model_available_before_ms':cutoff}
     if algorithm=='RIDGE':info.update(coefficients=model[-1].coef_.tolist(),intercept=float(model[-1].intercept_),scaler_mean=model[0].mean_.tolist(),scaler_scale=model[0].scale_.tolist())
     audit.append(info)
    chosen=np.where(values['long']>=values['short'],1,-1);expected=np.maximum(values['long'],values['short'])
    for ms,side,score,pl,ps in zip(test.index,chosen,expected,values['long'],values['short']):predictions.append({'model':key,'signal_ms':int(ms),'direction':int(side),'expected_net_r':float(score),'pred_long_r':float(pl),'pred_short_r':float(ps),'model_train_end_exclusive':train_end})
   for threshold in [.05,.10,.20]:configs.append({'family':'TIME_LONG','window':'EARLY','stop':1.25,'target':2.,'usd':0,'prediction_key':key,'threshold':threshold,'suffix':f'_ML{key}_T{threshold}'})
 pd.DataFrame(predictions).to_csv(OUT/'ml_predictions.csv.gz',index=False);(OUT/'ml_fit_audit.json').write_text(json.dumps(audit,indent=2));(OUT/'ml_configs.json').write_text(json.dumps(configs,indent=2));print('ML panel',len(data),'predictions',len(predictions),'models',len(configs))
if __name__=='__main__':build()
