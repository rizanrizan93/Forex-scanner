"""Pure market-data evaluation of the frozen rule670. Never sends orders."""
from __future__ import annotations
from datetime import UTC,datetime
from pathlib import Path
import base64,hashlib,io,json
import numpy as np
import pandas as pd
from . import setups
from .features import build_frames

ARTIFACTS=Path(__file__).with_name('artifacts')
CONTRACT='RIZAN_ENTRY_DIRECTION_R2_V1'

def manifest():return json.loads((ARTIFACTS/'manifest.json').read_text())

def load_model():
 import joblib
 m=manifest()
 decoded={}
 for name,digest in m['files'].items():
  raw=base64.b64decode((ARTIFACTS/(name+'.b64')).read_bytes(),validate=True)
  if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('R2_MODEL_HASH_MISMATCH')
  decoded[name]=raw
 bundles={n:joblib.load(io.BytesIO(decoded[n+'.joblib'])) for n in ['ensemble','hgb_l15_r10','extra_leaf150','imputer']}
 bundles['extra_leaf150']['model'].n_jobs=1
 return bundles

def score(x,bundles):
 from scipy.special import logit
 names=manifest()['features']
 if list(x)!=names:raise ValueError('R2_FEATURE_SCHEMA_MISMATCH')
 a=bundles['imputer'].transform(x);raw=np.mean([bundles[n]['model'].predict_proba(a)[:,1] for n in ['hgb_l15_r10','extra_leaf150']],axis=0)
 return bundles['ensemble']['calibrators'][-1].predict_proba(logit(np.clip(raw,1e-6,1-1e-6)).reshape(-1,1))[:,1]

def stamp(value):
 t=pd.Timestamp(value)
 if t.tzinfo is None:raise ValueError('R2_TIMESTAMP_WITHOUT_TIMEZONE')
 return t.tz_convert('UTC')

def evaluate(xau,eur,quote,*,now,memory=None,bundles=None):
 now=stamp(now);minute=now.floor('min');local=now.tz_convert('Asia/Jakarta');memory=dict(memory or {});day=str(local.date())
 if memory.get('day')!=day:memory.update(day=day,count=0,last_selected_at=None)
 memory.setdefault('observed_since',now.isoformat());memory.setdefault('count',0)
 out={'contract':CONTRACT,'as_of':now.isoformat(),'model_id':'R2_RULE_670','status':'WAIT_DATA','direction':'WAIT','policy':'SELL_ONLY','execution_authority':False,'execution_influence':False,'observed_since':memory['observed_since'],'history':{'XAUUSD':len(xau),'EURUSD':len(eur)},'checks':[],'candidate':None,'signal':memory.get('last_signal'),'quote':quote,'memory':memory}
 def check(key,label,passed,value):out['checks'].append({'key':key,'label':label,'pass':bool(passed),'value':str(value)})
 closed=xau[xau.index+pd.Timedelta(minutes=1)<=now];ec=eur[eur.index+pd.Timedelta(minutes=1)<=now]
 history_ok=len(closed)>=60000 and len(ec)>=300
 check('history','Riwayat XAU dan EUR tersedia',history_ok,f'{len(closed):,} / {len(ec):,} candle M1')
 if not history_ok:out['status']='WARMUP';out['reason']='Mengumpulkan riwayat model';return out
 fresh= -5<=(now-(closed.index[-1]+pd.Timedelta(minutes=1))).total_seconds()<=90 and -5<=(now-(ec.index[-1]+pd.Timedelta(minutes=1))).total_seconds()<=120
 out['last_closed_m1']= (closed.index[-1]+pd.Timedelta(minutes=1)).isoformat();out['eur_last_closed_m1']=(ec.index[-1]+pd.Timedelta(minutes=1)).isoformat()
 check('candles','Candle XAU/EUR terbaru',fresh,out['last_closed_m1'])
 try:
  bid,ask=float(quote['bid']),float(quote['ask']);qt=stamp(quote['at']);quote_ok=0<bid<=ask and -5<=(now-qt).total_seconds()<=30
 except (KeyError,TypeError,ValueError):bid=ask=None;quote_ok=False
 check('quote','Harga bid/ask terbaru',quote_ok,quote.get('at','—'))
 session=local.dayofweek<5 and 420<=local.hour*60+local.minute<1435
 check('session','Sesi model aktif',session,'Senin–Jumat 07.00–23.55 WIB')
 bar_ok=minute in xau.index
 check('open','Open M1 pemicu tersedia',bar_ok,minute.isoformat())
 prev=minute-pd.Timedelta(minutes=1);spread_ok=prev in xau.index and np.isfinite(xau.loc[prev,'spread']) and xau.loc[prev,'spread']>0
 check('spread_history','Spread menit sebelumnya teramati',spread_ok,prev.isoformat())
 if not fresh or not quote_ok:out['reason']='Sumber harga belum segar';return out
 if not session:out.update(status='WAIT_SESSION',reason='Menunggu sesi model');return out
 if not bar_ok or not spread_ok:out.update(status='WARMUP',reason='Menunggu open dan spread M1 yang lengkap');return out
 # Cache each minute's causal features/scores; later quotes never repaint them.
 if memory.get('last_scored_minute')!=minute.isoformat():
  d=xau[xau.index<=minute].copy();last=len(d)-1;ev=setups.generate(d);ev=ev[(ev['entry']==last)&(ev['s']==-1)]
  candidates=[]
  if len(ev):
   events=pd.DataFrame.from_records(ev);events['event_i']=np.arange(len(events));events=events.rename(columns={'entry':'entry_i','s':'side'});events['t']=d.index.asi8[events.entry_i]//60_000_000_000;events['year']=local.year;events['minute']=local.hour*60+local.minute;events['dow']=local.dayofweek;events['day']=(events.t+420)//1440
   x,events=build_frames(d,ec,events);scores=score(x,bundles or load_model())
   for row,p in zip(events.to_dict('records'),scores):
    ref=float(d.open.iloc[row['entry_i']]);a=float(row['atr']);level=float(row['level'])
    if abs((ref-.05)-level)<=a and max(.30,d.spread.iloc[-2])<=.25*a:
     candidates.append({'side':'SELL','style':int(row['style']),'score':float(p),'threshold':manifest()['rule']['threshold'],'signal_at':minute.isoformat(),'valid_until':(minute+pd.Timedelta(minutes=1)).isoformat(),'reference':ref,'level':level,'atr_h1':a,'correct_direction_level':ref-.25*a,'adverse_direction_level':ref+.25*a})
  candidates.sort(key=lambda z:(-z['score'],z['style']));memory['last_scored_minute']=minute.isoformat();memory['candidate']=candidates[0] if candidates else None
 candidate=memory.get('candidate');out['candidate']=candidate
 check('setup','Pemicu SELL M1/M5 selesai',candidate is not None,'Tunggu sentuhan dan reclaim pola')
 threshold=manifest()['rule']['threshold'];passed=candidate is not None and candidate['score']>=threshold
 check('score','Skor melewati ambang R2',passed,f"{candidate['score']:.4f} / {threshold:.4f}" if candidate else f'Ambang {threshold:.4f}')
 allowed=memory['count']<2
 if memory.get('last_selected_at'):allowed&=(minute-stamp(memory['last_selected_at'])).total_seconds()>=120*60
 # An existing same-minute signal is a frozen plan, never another selection.
 same=memory.get('last_selected_at')==minute.isoformat()
 check('limits','Batas dua sinyal dan jeda 120 menit',allowed or same,f"{memory['count']}/2 sinyal teramati hari ini")
 current_distance=candidate is not None and abs(bid-candidate['level'])<=candidate['atr_h1'] and ask-bid<=.25*candidate['atr_h1']
 check('distance','Harga masih dalam batas entry',current_distance,'Maksimum 1 ATR H1 dari garis pemicu')
 if candidate and passed and current_distance and (allowed or same):
  if not same:memory['count']+=1;memory['last_selected_at']=minute.isoformat();memory['last_signal']=dict(candidate,signal_id=f"R2:{minute.isoformat()}:{candidate['style']}",created_at=now.isoformat())
  out.update(status='TRIGGER_SELL',direction='SELL',signal=memory['last_signal'],reason='Pemicu R2 teramati; keputusan entry tetap manual')
 elif candidate and not passed:out.update(status='WATCH_SCORE',reason='Pemicu ada, skor belum melewati ambang model')
 elif not allowed:out.update(status='WAIT_LIMIT',reason='Menunggu batas sinyal atau jeda model')
 else:out.update(status='WATCH_SETUP',reason='Memantau pola SELL; belum ada pemicu yang memenuhi syarat')
 out['memory']=memory;out['signals_today']=memory['count'];return out
