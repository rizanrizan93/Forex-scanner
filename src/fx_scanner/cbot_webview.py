"""Minimal display DTO for the cTrader WebView. Never exports account/position data."""
from datetime import UTC,datetime,timedelta
import json,math,re
from .cbot_manual import CONTRACT,SOURCE_COMMIT,stamp

SCHEMA='RIZAN_WEBVIEW_V1'
def num(v):return isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v)
def iso(t):return t.astimezone(UTC).isoformat() if t else None
def recent(value,now,seconds):
    at=stamp(value)
    return bool(at and -5<=(now-at).total_seconds()<=seconds)

def frame(raw,cut):
    if not isinstance(raw,dict) or raw.get('execution_authority') is not False or raw.get('execution_influence') is not False:return None
    at=stamp(raw.get('at_utc'))
    if not at or at>cut or not all(num(raw.get(k)) and raw[k]>0 for k in ['open','high','low','close']):return None
    if raw['low']>min(raw['open'],raw['close']) or raw['high']<max(raw['open'],raw['close']):return None
    if type(raw.get('signal_side')) is not int or raw['signal_side'] not in (-1,0,1):return None
    out={k:raw[k] for k in ['open','high','low','close','signal_side']}
    out['at_utc']=iso(at)
    for key in ['buy_trigger_next','sell_trigger_estimate','sell_sweep_next']:
        out[key]=raw.get(key) if num(raw.get(key)) and raw[key]>0 else None
    out.update(h1_bias=raw.get('h1_bias') if raw.get('h1_bias') in (-1,0,1) else 0,
        m15_bias=raw.get('m15_bias') if raw.get('m15_bias') in (-1,0,1) else 0,
        warm=raw.get('warm') is True,buy_prior_eligible=raw.get('buy_prior_eligible') is True,
        sell_setup_expires=iso(stamp(raw.get('sell_setup_expires'))))
    return out

def build_view(payload,*,now=None,symbol='XAUUSD',demo=False):
    now=now or datetime.now(UTC)
    base=dict(schema=SCHEMA,mode='demo' if demo else 'live',symbol='XAUUSD',
        core='XAU V1.3.0',source_commit=SOURCE_COMMIT,status='DATA_TIDAK_VALID',
        reason='Data indikator belum dapat diverifikasi.',source_as_of=None,candle_as_of=None,
        fresh_until=None,entry_until=None,entry=None,frame=None,history=[],target_r=5.5,
        hold_minutes=480,execution_authority=False,execution_influence=False)
    if not re.fullmatch(r'XAUUSD[.A-Z0-9_-]*',str(symbol).upper()):
        base.update(status='SIMBOL_TIDAK_DIDUKUNG',reason='Plugin ini khusus XAUUSD. Buka simbol XAUUSD.');return base
    if (not isinstance(payload,dict) or payload.get('contract')!=CONTRACT or
        payload.get('source_commit')!=SOURCE_COMMIT or payload.get('source_release')!='V1.3.0' or
        payload.get('execution_authority') is not False or payload.get('execution_influence') is not False):return base
    rows=[c for c in payload.get('symbols',[]) if isinstance(c,dict) and c.get('symbol')=='XAUUSD']
    if len(rows)!=1:return base
    c=rows[0];bar=stamp(c.get('bar_at'));source=stamp(payload.get('as_of'));market=stamp(payload.get('market_observed_at'))
    base.update(source_as_of=iso(source),candle_as_of=iso(bar))
    if not all([source,market,bar]) or bar>now:return base
    until=min(source+timedelta(seconds=90),market+timedelta(seconds=90),bar+timedelta(seconds=360))
    base['fresh_until']=iso(until)
    if not all([recent(payload.get('as_of'),now,90),recent(payload.get('market_observed_at'),now,90),recent(c.get('bar_at'),now,360)]):
        base.update(status='DATA_TERLAMBAT',reason='Menunggu candle dan publikasi baru. Sinyal lama tidak menjadi entry baru.');return base
    f=frame(c.get('indicator'),bar)
    if not f or stamp(f['at_utc'])!=bar:
        base.update(status='MENUNGGU_INDIKATOR',reason='Monitor belum menerbitkan frame indikator yang cocok.');return base
    history=[];previous=None
    for raw in (c.get('indicator_history') or [])[-96:]:
        row=frame(raw,bar)
        if row is None or (previous is not None and stamp(row['at_utc'])<=previous):
            base.update(reason='Urutan candle indikator tidak valid.');return base
        previous=stamp(row['at_utc']);history.append(row)
    if history and previous!=bar:
        base.update(reason='History tidak cocok dengan candle indikator.');return base
    base.update(frame=f,history=history,status='MENUNGGU_POLA',reason='Tunggu aturan entry cBot lengkap pada penutupan M5.')
    session=now.weekday()<5 and 12<=now.hour<17
    if not f['warm']:base.update(status='WARMUP',reason='Menunggu sedikitnya 200 candle H1 untuk pemanasan.')
    elif not session:base.update(status='DI_LUAR_SESI',reason='Sesi asli XAU: 19:00–00:00 WIB, hari kerja.')
    elif f['buy_prior_eligible'] and f['h1_bias']==1 and f['m15_bias']==1:
        base.update(status='PERSIAPAN_BUY',reason='Prasyarat BUY tersedia. Tunggu close M5 bullish melewati batas channel.')
    elif f['sell_trigger_estimate'] and f['h1_bias']==-1 and f['m15_bias']==-1:
        base.update(status='PERSIAPAN_SELL',reason='Sweep tersedia. Tunggu close M5 bearish; ambang SELL masih mengikuti ATR konfirmasi.')
    if c.get('status') in ('BLOCK','POSISI_AKTIF','DATA_TERLAMBAT'):
        base.update(status=c['status'],reason=str(c.get('reason') or 'Syarat entry belum lengkap.')[:240])
    s=c.get('signal') or {};side=1 if s.get('side')=='BUY' else -1 if s.get('side')=='SELL' else 0
    signal=stamp(s.get('at'));expires=stamp(c.get('valid_until'));native=stamp(payload.get('native_observed_at'));quote=stamp(c.get('quote_at'))
    geometry=all(num(c.get(k)) and c[k]>0 for k in ['entry','sl','tp'])
    if geometry and side:
        risk=side*(c['entry']-c['sl'])
        geometry=risk>=.5-1e-7 and abs(side*(c['tp']-c['entry'])-5.5*risk)<max(1e-6,risk*1e-6)
    eligible=(not demo and c.get('status')=='ENTRY_MANUAL' and not c.get('blockers') and
        session and f['warm'] and side in (-1,1) and side==f['signal_side'] and signal==bar and
        signal is not None and signal<=now and expires is not None and now<expires<=signal+timedelta(seconds=60) and
        recent(c.get('quote_at'),now,15) and recent(payload.get('native_observed_at'),now,90) and
        geometry and c.get('target_r')==5.5)
    if eligible:
        base.update(status='ENTRY_MANUAL',reason='Acuan manual dari monitor. Periksa harga dan kesiapan akun di cTrader.',
            entry={k:c[k] for k in ['entry','sl','tp']}|{'side':s['side']},
            entry_until=iso(min(until,expires,signal+timedelta(seconds=60),quote+timedelta(seconds=15),native+timedelta(seconds=90))))
    if demo:base.update(status='MODE_UJI',reason='Contoh historis untuk uji tampilan; bukan sinyal live.',entry=None,entry_until=None)
    return base

def safe_json(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
