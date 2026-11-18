"""Read-only causal XAU H1/H4 research. No broker, no orders, no account access.

M1 timestamp is opening UTC minute. A signal at t only uses completed
H1/H4 candles with close timestamps <=t, entering M1 open at t.
Public HistData is not FP Markets executable bid/ask data.
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd

MINUTE_NS=60_000_000_000
TARGET_USD=10.0
EXECUTION_AUTHORITY=False
EXECUTION_INFLUENCE=False

def validate_m1(raw:pd.DataFrame)->pd.DataFrame:
    d=raw.copy()
    if 'timestamp' in d.columns:d=d.set_index('timestamp')
    d.index=pd.to_datetime(d.index,utc=True);d=d.sort_index()
    if d.index.has_duplicates:raise ValueError('DUPLICATE_M1_TIMESTAMP')
    if not {'open','high','low','close'}.issubset(d.columns):raise ValueError('MISSING_OHLC')
    d=d[['open','high','low','close']].astype('float64')
    if d.empty or not np.isfinite(d.to_numpy()).all():raise ValueError('MISSING_PRICE')
    if ((d.low>d[['open','close']].min(axis=1))|
        (d.high<d[['open','close']].max(axis=1))|
        (d.low<=0)).any():raise ValueError('INVALID_OHLC')
    if np.any((d.index.asi8%MINUTE_NS)!=0):raise ValueError('UNALIGNED_M1_TIMESTAMP')
    return d

def completed_bars(d:pd.DataFrame,minutes:int)->pd.DataFrame:
    """A H1/H4 bar exists only when ALL constituent M1 rows exist."""
    g=d.resample(f'{minutes}min',label='right',closed='left')
    v=g.agg({'open':'first','high':'max','low':'min','close':'last'})
    return v.loc[g.close.count().eq(minutes)].dropna()

def _atr(f:pd.DataFrame)->pd.Series:
    p=f.close.shift(1)
    tr=pd.concat([f.high-f.low,(f.high-p).abs(),(f.low-p).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()

def _features(f:pd.DataFrame)->pd.DataFrame:
    o=f.copy()
    o['ema20']=f.close.ewm(span=20,adjust=False,min_periods=20).mean()
    o['ema50']=f.close.ewm(span=50,adjust=False,min_periods=50).mean()
    o['atr']=_atr(f)
    o['prior_high']=f.high.shift(1).rolling(20,min_periods=20).max()
    o['prior_low']=f.low.shift(1).rolling(20,min_periods=20).min()
    o['bull_trend']=(f.close>o.ema20)&(o.ema20>o.ema50)&(o.ema20>o.ema20.shift(3))
    o['bear_trend']=(f.close<o.ema20)&(o.ema20<o.ema50)&(o.ema20<o.ema20.shift(3))
    return o

def candidates(m1:pd.DataFrame,*,timeframe:int)->pd.DataFrame:
    """Candidate geometry and scores are hypothetical, NOT calibrated win probabilities."""
    if timeframe not in (60,240):raise ValueError('TIMEFRAME_MUST_BE_H1_OR_H4')
    d=validate_m1(m1);f=_features(completed_bars(d,timeframe))
    h4=_features(completed_bars(d,240))
    h4state=h4[['bull_trend','bear_trend']].rename(columns={'bull_trend':'h4_bull','bear_trend':'h4_bear'})
    h4state=h4state.reindex(f.index,method='ffill')
    prior_h4_index=pd.Series(h4.index,index=h4.index).reindex(f.index,method='ffill')
    h4age_hours=(f.index.to_series()-prior_h4_index).dt.total_seconds()/3600
    if timeframe==240:h4age_hours=pd.Series(0.,index=f.index)
    ready=(f.atr>0)&f.prior_high.notna()&f.prior_low.notna()&(h4age_hours<=8)
    body=f.close-f.open
    sweep_buy=(f.low<f.prior_low)&(f.close>f.prior_low)&(body>0)
    sweep_sell=(f.high>f.prior_high)&(f.close<f.prior_high)&(body<0)
    pullback_buy=f.bull_trend&(f.low<=f.ema20)&(f.close>f.ema20)&(body>0)
    pullback_sell=f.bear_trend&(f.high>=f.ema20)&(f.close<f.ema20)&(body<0)
    breakout_buy=f.bull_trend&(f.close>f.prior_high)&(body>.3*f.atr)
    breakout_sell=f.bear_trend&(f.close<f.prior_low)&(-body>.3*f.atr)
    base_buy=np.select([sweep_buy,pullback_buy,breakout_buy],[4,3,3],default=0)
    base_sell=np.select([sweep_sell,pullback_sell,breakout_sell],[4,3,3],default=0)
    aligned_buy=h4state.h4_bull.fillna(False).astype(bool)
    aligned_sell=h4state.h4_bear.fillna(False).astype(bool)
    score_buy=np.where(base_buy>0,base_buy+2*aligned_buy.astype(int)-3*aligned_sell.astype(int),0)
    score_sell=np.where(base_sell>0,base_sell+2*aligned_sell.astype(int)-3*aligned_buy.astype(int),0)
    reason_buy=np.select([sweep_buy,pullback_buy,breakout_buy],['SWEEP_RECLAIM_LOW','TREND_PULLBACK','BOS_BREAKOUT'],default='NONE')
    reason_sell=np.select([sweep_sell,pullback_sell,breakout_sell],['SWEEP_RECLAIM_HIGH','TREND_PULLBACK','BOS_BREAKOUT'],default='NONE')
    out=pd.DataFrame({'decision_ts':f.index,'timeframe':timeframe,'atr':f.atr,
        'buy_score':score_buy,'sell_score':score_sell,'buy_reason':reason_buy,'sell_reason':reason_sell,
        'h4_bull':aligned_buy,'h4_bear':aligned_sell,'demand':f.prior_low,
        'supply':f.prior_high,'last_close':f.close,'ready':ready},index=f.index)
    return out.loc[ready].copy()

def apply_policy(frame:pd.DataFrame,*,threshold:int=4,require_h4:bool=False)->pd.DataFrame:
    if threshold not in (3,4,5,6):raise ValueError('UNAPPROVED_THRESHOLD')
    z=frame.copy();bs=z.buy_score.to_numpy().copy();ss=z.sell_score.to_numpy().copy()
    if require_h4:
        bs=np.where(z.h4_bull.to_numpy(),bs,0)
        ss=np.where(z.h4_bear.to_numpy(),ss,0)
    side=np.where((bs>=threshold)&(bs>ss),1,np.where((ss>=threshold)&(ss>bs),-1,0))
    z['side']=side
    z['direction']=np.where(side==1,'BUY',np.where(side==-1,'SELL','WAIT'))
    z['reason']=np.where(side==1,z.buy_reason,np.where(side==-1,z.sell_reason,'WAIT_CONFIRMATION'))
    z['score']=np.where(side==1,bs,np.where(side==-1,ss,np.maximum(bs,ss)))
    return z

def replay(m1:pd.DataFrame,signals:pd.DataFrame,*,spread_scenario_usd:float=.5)->pd.DataFrame:
    """Complete M1 horizon; same-bar target/adverse tie loses; no-fill/gaps unscored."""
    if spread_scenario_usd<0 or not math.isfinite(spread_scenario_usd):
        raise ValueError('INVALID_COST_SCENARIO')
    d=validate_m1(m1);t=d.index.asi8;op=d.open.to_numpy()
    hi=d.high.to_numpy();lo=d.low.to_numpy();cl=d.close.to_numpy();rows=[]
    for x in signals.itertuples():
        if x.side==0:continue
        entry=pd.Timestamp(x.decision_ts).value;i=int(np.searchsorted(t,entry));horizon=int(x.timeframe)
        r={'decision_ts':pd.Timestamp(entry,unit='ns',tz='UTC').isoformat(),
           'timeframe':horizon,'side':'BUY' if x.side==1 else 'SELL','score':int(x.score),
           'reason':x.reason,'atr':float(x.atr),'entry_reference':None,
           'net_horizon_move':None,'correct_net':None,'hit10_before_adverse10':None,
           'mfe':None,'mae':None,'status':'GAP',
           'year':pd.Timestamp(entry,unit='ns',tz='UTC').year}
        if (i>=len(t) or t[i]!=entry or i+horizon-1>=len(t)
                or t[i+horizon-1]!=entry+(horizon-1)*MINUTE_NS):
            rows.append(r);continue
        p=float(op[i]);s=int(x.side);end=i+horizon
        fav=hi[i:end]-p if s==1 else p-lo[i:end]
        bad=p-lo[i:end] if s==1 else hi[i:end]-p
        win_idx=np.flatnonzero(fav>=TARGET_USD+spread_scenario_usd)
        loss_idx=np.flatnonzero(bad>=TARGET_USD)
        first_win=int(win_idx[0]) if len(win_idx) else horizon+1
        first_loss=int(loss_idx[0]) if len(loss_idx) else horizon+1
        net=s*(cl[end-1]-p)-spread_scenario_usd
        r.update(entry_reference=p,net_horizon_move=float(net),correct_net=bool(net>0),
                 hit10_before_adverse10=bool(first_win<first_loss and first_win<horizon),
                 mfe=float(max(fav)-spread_scenario_usd),mae=float(max(bad)),status='EVALUATED')
        rows.append(r)
    return pd.DataFrame(rows)

def summary(ledger:pd.DataFrame)->list[dict]:
    if ledger.empty:return []
    result=[]
    for (year,tf,side),z in ledger.groupby(['year','timeframe','side']):
        ok=z[z.status=='EVALUATED'];n=len(ok)
        wins=int(ok.correct_net.sum()) if n else 0
        hits=int(ok.hit10_before_adverse10.sum()) if n else 0
        result.append({'year':int(year),'timeframe':int(tf),'side':side,
            'signals':len(z),'evaluated':n,'gaps':len(z)-n,
            'directional_wins':wins,'directional_accuracy':round(wins/n,6) if n else None,
            'net10_before_adverse10':hits,'net10_rate':round(hits/n,6) if n else None,
            'median_net_horizon_move':float(ok.net_horizon_move.median()) if n else None,
            'median_mae':float(ok.mae.median()) if n else None})
    return result
