"""Causal manual-trading indicator primitives. No order/broker operations."""
from __future__ import annotations
from datetime import datetime,timezone
import numpy as np
import pandas as pd

FAMILIES=['RSI2_TREND_PULLBACK','BOLLINGER_REENTRY','KELTNER_RANGE_FADE','KIJUN_TREND_PULLBACK','SQUEEZE_BREAKOUT','SESSION_MEAN_FADE','CHANDELIER_PULLBACK','ADX_DI_BREAKOUT']


def bars(d,minutes):
    return d.resample(f'{minutes}min',label='right',closed='left').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()


def atr(d,n=14):
    prev=d.close.shift(1)
    tr=pd.concat([d.high-d.low,(d.high-prev).abs(),(d.low-prev).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False,min_periods=n).mean()


def rsi(close,n=2):
    delta=close.diff();up=delta.clip(lower=0).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    down=(-delta.clip(upper=0)).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    result=100-100/(1+up/down)
    return result.mask((up==0)&(down==0),50)


def adx(d,n=14):
    u=d.high.diff();v=-d.low.diff()
    positive=u.where((u>v)&(u>0),0);negative=v.where((v>u)&(v>0),0)
    a=atr(d,n)
    plus=100*positive.ewm(alpha=1/n,adjust=False,min_periods=n).mean()/a
    minus=100*negative.ewm(alpha=1/n,adjust=False,min_periods=n).mean()/a
    dx=(100*(plus-minus).abs()/(plus+minus)).mask((plus+minus)==0,0)
    return dx.ewm(alpha=1/n,adjust=False,min_periods=n).mean(),plus,minus


def map_values(series,t):
    idx=np.searchsorted(series.index.asi8,t,side='right')-1
    values=series.to_numpy()[np.maximum(idx,0)].astype(float);values[idx<0]=np.nan
    return values


def context(d):
    m5=bars(d,5);m15=bars(d,15);h1=bars(d,60)
    a5,a15=atr(m5),atr(m15)
    ah,ph,mh=adx(h1);am,pm,mm=adx(m15)
    eh=h1.close.ewm(span=50,adjust=False,min_periods=50).mean()
    em=m15.close.ewm(span=20,adjust=False,min_periods=20).mean()
    width=m5.close.rolling(20).std(ddof=0)*4/m5.close.rolling(20).mean()
    return {'m5':m5,'m15':m15,'h1':h1,'a5':a5,'a15':a15,'h1_adx':ah,'m15_adx':am,
            'm15_plus':pm,'m15_minus':mm,'h1_side':np.sign(h1.close-eh).fillna(0),
            'ema20':em,'rsi2':rsi(m5.close),'squeeze_width':width}


def levels(family,scale,d,ctx):
    m5,m15,a15=ctx['m5'],ctx['m15'],ctx['a15'];valid=None
    if family==0:
        center=ctx['ema20'];upper=center+.5*a15;lower=center-.5*a15
    elif family==1:
        center=m15.close.rolling(20).mean();width=[1.5,2,2.5,3][scale]*m15.close.rolling(20).std(ddof=0)
        upper=center+width;lower=center-width
    elif family==2:
        center=ctx['ema20'];width=[1,1.5,2,2.5][scale]*a15;upper=center+width;lower=center-width
    elif family==3:
        center=(m15.high.rolling(26).max()+m15.low.rolling(26).min())/2
        width=[0,.25,.5,.75][scale]*a15;upper=center+width;lower=center-width
    elif family==4:
        upper=m5.high.rolling(20).max();lower=m5.low.rolling(20).min()
        width=ctx['squeeze_width'];q=width.rolling(5760,min_periods=1000).quantile([.1,.2,.3,.4][scale]).shift(1)
        recent=(width<=q).rolling(3).max().fillna(0)
        valid=map_values(recent,d.index.asi8)>0
    elif family==5:
        local=d.index.tz_convert('Asia/Jakarta');minute=local.hour*60+local.minute
        phase=np.where(minute<420,3,np.where(minute<840,0,np.where(minute<1140,1,2)))
        days=(d.index.asi8//60_000_000_000+420)//1440;key=days*4+phase
        counts=d.close.groupby(key).cumcount()+1
        mean=d.close.groupby(key).cumsum()/counts
        mean.index=mean.index+pd.Timedelta(minutes=1) # M1 close available after its close, never at its open
        width=map_values(a15,mean.index.asi8)*[1,1.5,2,2.5][scale]
        upper=mean+width;lower=mean-width
    elif family==6:
        k=[2,2.5,3,3.5][scale]
        lower=m15.high.rolling(22).max()-k*a15
        upper=m15.low.rolling(22).min()+k*a15
    elif family==7:
        upper=m5.high.rolling(3).max();lower=m5.low.rolling(3).min()
    else:raise ValueError('Unknown indicator family')
    return upper,lower,valid


def regime_mask(family,scale,direction,d,ctx):
    t=d.index.asi8;ah=map_values(ctx['h1_adx'],t)
    side=map_values(ctx['h1_side'],t)
    if family in [0,3,6]:mask=(ah>=20)&(side==direction)
    elif family==1:mask=ah<25
    elif family in [2,5]:mask=ah<20
    else:mask=np.ones(len(d),dtype=bool)
    if family==0:
        rr=map_values(ctx['rsi2'],t);threshold=[5,10,15,20][scale]
        mask&=rr<=threshold if direction==1 else rr>=100-threshold
    if family==7:
        am=ctx['m15_adx'];rising=map_values((am>am.shift(1)).astype(float),t)>0
        amv=map_values(am,t);di=map_values(ctx['m15_plus']-ctx['m15_minus'],t)
        mask&=(amv>=[15,20,25,30][scale])&rising&(direction*di>0)
    return mask


def _utc(value):
    ts=pd.Timestamp(value)
    if ts.tzinfo is None:raise ValueError('Timestamp must include timezone')
    return ts.tz_convert('UTC')


def _news_allowed(events,when):
    if events is None:return False,'Kalender berita belum tersedia'
    for item in events:
        name=str(item.get('event','')).upper()
        if name not in ['CPI','PPI','NFP','FOMC']:continue
        at=_utc(item['at']);window=60 if name=='FOMC' else 30
        if abs((when-at).total_seconds())<=window*60:return False,f'Jendela risiko {name}: ±{window} menit'
    return True,'Di luar jendela berita yang dimasukkan'


def evaluate_snapshot(frame,*,now,bid=None,ask=None,quote_as_of=None,news_events=None,memory=None):
    """Read-only selected R3 overlay, consuming timestamped closed M1 OHLC.

    `frame` timestamps are M1 OPEN times, UTC/aware. Forming bars are excluded.
    `news_events` uses [{event:'CPI',at:'...+00:00'}]; None blocks READY.
    Keep returned memory between refreshes to freeze plans and deduplicate alerts.
    Returns JSON-safe data. This prototype never connects to or trades an account.
    """
    now=_utc(now);memory=dict(memory or {})
    out={'name':'RIZAN Manual Range Reclaim R3','status':'WAIT_DATA','as_of_utc':now.isoformat(),
         'research_status':'EXPERIMENTAL_MANUAL_AID','direction':'WAIT','execution_authority':False,
         'score_is_win_probability':False,'alert_new':False,'memory':memory,'checks':[],'plan':None}
    out['manual_constraints']={'one_position':True,'maximum_trades_per_day':2,'maximum_risk_pct':.5,
                               'enforce_by_user_or_scanner_position_feed':True}
    if not isinstance(frame.index,pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError('M1 frame must have timezone-aware DatetimeIndex')
    d=frame[['open','high','low','close']].copy();d.index=d.index.tz_convert('UTC')
    d=d[d.index+pd.Timedelta(minutes=1)<=now].sort_index()
    if d.index.has_duplicates or len(d)<2000 or d.isna().any().any():
        out['reason']='Butuh setidaknya 2.000 candle M1 historis yang valid dan tanpa duplikat';return out
    if ((d.low>d[['open','close']].min(axis=1))|(d.high<d[['open','close']].max(axis=1))|(d.high<d.low)).any():
        out['reason']='OHLC tidak konsisten';return out
    last_close=d.index[-1]+pd.Timedelta(minutes=1)
    if (now-last_close).total_seconds()>90:
        out['reason']='Candle M1 terbaru sudah lewat 90 detik';return out
    ctx=context(d);t=d.index.asi8;last=d.index[-1]
    a=float(map_values(ctx['a5'],[now.value])[0]);adx_now=float(map_values(ctx['h1_adx'],[now.value])[0])
    upper,lower,_=levels(2,2,d,ctx);u=map_values(upper,t);l=map_values(lower,t)
    live_u=float(map_values(upper,[now.value])[0]);live_l=float(map_values(lower,[now.value])[0])
    emah=ctx['h1'].close.ewm(span=20,adjust=False,min_periods=20).mean()
    slope_series=np.sign(emah-emah.shift(3)).fillna(0)
    slope_now=int(map_values(slope_series,[now.value])[0])
    if not all(np.isfinite(x) for x in [a,adx_now,live_u,live_l]) or a<=0:
        out['reason']='Indikator masih mengumpulkan riwayat H1/M15';return out
    loc=now.tz_convert('Asia/Jakarta');minute=loc.hour*60+loc.minute
    day_ok=loc.dayofweek<=2;session_ok=14*60<=minute<1440
    news_ok,news_reason=_news_allowed(news_events,now)
    quote_ok=False
    if bid is not None and ask is not None and quote_as_of is not None:
        age=(now-_utc(quote_as_of)).total_seconds()
        quote_ok=bool(np.isfinite(bid) and np.isfinite(ask) and 0<bid<=ask and -5<=age<=30)
    reference=float((bid+ask)/2) if quote_ok else float(d.close.iloc[-1])
    out.update({'regime':'RANGE' if adx_now<20 else 'TREND_OR_UNCLEAR',
                'h1_adx':adx_now,'bias':'BUY' if slope_now>0 else 'SELL' if slope_now<0 else 'WAIT',
                'zone_buy':{'low':live_l-.25*a,'high':live_l+.25*a,'trigger_line':live_l},
                'zone_sell':{'low':live_u-.25*a,'high':live_u+.25*a,'trigger_line':live_u},
                'atr_m5':a,'last_closed_m1_utc':last_close.isoformat()})
    # Reconstruct the same first qualified crossing per side/date/session as replay.
    local=d.index.tz_convert('Asia/Jakarta');mins=local.hour.to_numpy()*60+local.minute.to_numpy()
    dates=(t//60_000_000_000+420)//1440;phase=np.where(mins<840,0,np.where(mins<1140,1,2))
    today=(now.value//60_000_000_000+420)//1440
    prev=np.r_[np.nan,d.close.to_numpy()[:-1]];signals=[]
    for side in [1,-1]:
        lev=l if side==1 else u
        cross=(d.low.to_numpy()<=lev)&(prev>lev) if side==1 else (d.high.to_numpy()>=lev)&(prev<lev)
        eligible=cross&(dates==today)&(mins>=420)&(local.dayofweek<5)&regime_mask(2,2,side,d,ctx)&np.isfinite(lev)
        ids=np.flatnonzero(eligible)
        if not len(ids):continue
        _,first=np.unique(dates[ids]*3+phase[ids],return_index=True)
        for i in ids[np.sort(first)]:
            for j in range(i,min(i+5,len(d))):
                if t[j]!=t[i]+(j-i)*60_000_000_000:break
                if side*(float(d.close.iloc[j])-lev[i])<=0:continue
                sig=d.index[j]+pd.Timedelta(minutes=1)
                if sig>now:break
                # The 20H1 EMA slope is evaluated when the signal becomes available.
                slope=int(map_values(slope_series,[sig.value])[0]);local_sig=sig.tz_convert('Asia/Jakarta')
                allowed,_=_news_allowed(news_events,sig)
                if slope==side and local_sig.dayofweek<=2 and local_sig.hour>=14 and allowed:
                    signals.append({'side':side,'level':float(lev[i]),'sweep_at':d.index[i],
                                    'signal_at':sig,'signal_close':float(d.close.iloc[j]),
                                    'range_adx':float(map_values(ctx['h1_adx'],[t[i]])[0]),
                                    'atr':float(map_values(ctx['a5'],[sig.value])[0])})
                break
    signals.sort(key=lambda z:z['signal_at'])
    signal=signals[-1] if signals else None
    rows=[{'key':'range','label':'H1 dalam kondisi range','pass':adx_now<20,'value':f'ADX14 H1 {adx_now:.1f} < 20'},
          {'key':'day','label':'Hari yang diuji','pass':day_ok,'value':'Senin–Rabu'},
          {'key':'session','label':'Sesi aktif','pass':session_ok,'value':'14.00–00.00 WIB'},
          {'key':'news','label':'Di luar jendela berita','pass':news_ok,'value':news_reason},
          {'key':'quote','label':'Harga bid/ask terbaru','pass':quote_ok,'value':'Maksimal 30 detik'},
          {'key':'bias','label':'Slope EMA20 H1 memiliki arah','pass':slope_now!=0,'value':'BUY jika naik; SELL jika turun'},
          {'key':'reclaim','label':'Close M1 sudah reclaim','pass':False,'value':'Tunggu close kembali melewati garis zona'},
          {'key':'distance','label':'Harga belum terlalu jauh','pass':False,'value':'Maksimal 1 ATR M5 dari garis pemicu'},
          {'key':'window','label':'Jendela entry masih berlaku','pass':False,'value':'60 detik setelah close pemicu'}]
    out['checks']=rows
    out['checklist_passed']=sum(x['pass'] for x in rows);out['checklist_total']=len(rows)
    if signal is not None:
        side=signal['side'];age=(now-signal['signal_at']).total_seconds()
        ident=f"R3:{side}:{signal['sweep_at'].isoformat()}"
        price=float(ask if side==1 else bid) if quote_ok else reference
        distance=abs(price-signal['level'])/signal['atr']
        out.update({'direction':'BUY' if side==1 else 'SELL','signal_id':ident,'signal_at_utc':signal['signal_at'].isoformat(),
                    'valid_until_utc':(signal['signal_at']+pd.Timedelta(seconds=60)).isoformat(),
                    'distance_from_zone_atr':distance,'frozen_trigger_line':signal['level']})
        rows[6].update({'pass':True,'value':signal['signal_at'].isoformat()})
        rows[7]['pass']=quote_ok and distance<=1
        rows[8]['pass']=age<60
        out['checklist_passed']=sum(x['pass'] for x in rows)
        if age<60:
            rows[0].update({'pass':True,'label':'H1 range ketika zona disentuh','value':f"ADX14 H1 {signal['range_adx']:.1f} < 20 pada pemicu"})
            rows[5].update({'pass':True,'value':'Slope H1 searah ketika pemicu selesai'})
            out['checklist_passed']=sum(x['pass'] for x in rows)
            if distance>1:
                out['status']='EXPIRED_PRICE';out['reason']='Harga sudah lebih dari 1 ATR M5 dari garis pemicu';return out
            if not all([day_ok,session_ok,news_ok,quote_ok]):
                out['status']='WAIT_CHECKLIST';out['reason']='Pemicu ada; lengkapi syarat sesi, kalender, dan harga terbaru';return out
            previous=memory.get('last_plan')
            if previous and previous.get('signal_id')==ident:plan=previous
            else:
                spread=float(ask-bid);risk=max(3*signal['atr'],2*spread)
                plan={'signal_id':ident,'side':'BUY' if side==1 else 'SELL','entry_reference':price,
                      'sl':price-side*risk,'tp':price+side*3*risk,'risk_price':risk,'rr_before_costs':3,
                      'max_fill_buy':signal['level']+signal['atr'] if side==1 else None,
                      'min_fill_sell':signal['level']-signal['atr'] if side==-1 else None,
                      'max_hold_minutes':240,'time_exit_utc':min(now+pd.Timedelta(minutes=240),loc.normalize().tz_convert('UTC')+pd.Timedelta(days=1)).isoformat(),
                      'plan_created_at_utc':now.isoformat()}
                memory['last_plan']=plan
            out['plan']=plan;out['status']='TRIGGER_BUY' if side==1 else 'TRIGGER_SELL'
            out['alert_new']=memory.get('last_alert_id')!=ident;memory['last_alert_id']=ident
            out['reason']='Reclaim M1 selesai; keputusan entry tetap manual';return out
        if age<15*60:
            out['status']='EXPIRED_TIME';out['reason']='Jendela entry 60 detik sudah selesai';return out
    out['direction']='WAIT'
    if not day_ok or not session_ok:out['status']='WAIT_SESSION';out['reason']='Tunggu Senin–Rabu 14.00–00.00 WIB'
    elif not news_ok:out['status']='WAIT_NEWS';out['reason']=news_reason
    elif adx_now>=20:out['status']='WAIT_REGIME';out['reason']='ADX H1 belum mendukung pola range'
    elif slope_now==1 and abs(reference-live_l)<=.5*a:out['status']='PREPARE_BUY';out['reason']='Dekat pita bawah; tunggu close M1 reclaim'
    elif slope_now==-1 and abs(reference-live_u)<=.5*a:out['status']='PREPARE_SELL';out['reason']='Dekat pita atas; tunggu close M1 reclaim'
    else:out['status']='WATCH_ZONE';out['reason']='Pantau pita bawah BUY atau pita atas SELL sesuai slope H1'
    return out
