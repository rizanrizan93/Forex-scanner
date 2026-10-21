"""Display-only projection of pinned cBot calculations and independently read state."""
from datetime import UTC,datetime,timedelta
from copy import deepcopy
import math
CONTRACT='RIZAN_CBOT_MANUAL_V1'
SOURCE_COMMIT='e357272fec03411a6e7c4d2397faf742d1a11047'
HASHES={'XAUUSD':'44db60b75e3eb19c0fb94f10baca96f35ab4686086a70eea53f626533ca9923c','EURUSD':'d39e1192b64c3044f3215fa82ceaacdb732b4cf758389ad4f609692e54bdae9a'}
def stamp(value):
 try:
  d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
  return d.astimezone(UTC) if d.tzinfo else None
 except (ValueError,TypeError):return None
def fresh(value,now,seconds):
 d=stamp(value);return d is not None and -5<=(now-d).total_seconds()<=seconds
def macro_reason(m,signal,now):
 at=stamp(signal['at']);side=1 if signal['side']=='BUY' else -1
 if not at or not fresh(m.get('ProducedUtc'),now,180) or not m.get('ForexFactoryOk') or not m.get('BlsOk'):return 'Menunggu feed makro dan kalender berita'
 start,end=stamp(m.get('CoverageFromUtc')),stamp(m.get('CoverageToUtc'))
 if not start or not end or start>at-timedelta(minutes=30) or end<at+timedelta(minutes=495):return 'Cakupan kalender berita belum lengkap'
 point=m.get('Dfii10' if side==1 else 'Dgs10') or {};pa=stamp(point.get('AvailableUtc'));delta=point.get('Delta')
 if not pa or not 0<=(at-pa).total_seconds()<=7*86400 or not isinstance(delta,(int,float)) or not math.isfinite(delta):return 'Data yield belum valid'
 if side*delta>0:return 'Arah yield menahan '+signal['side']
 for event in m.get('Events') or []:
  t=stamp(event.get('AtUtc'))
  if event.get('Category') in {'NFP','CPI','PPI','JOLTS','ECI','FOMC'} and t and at-timedelta(minutes=30)<=t<=at+timedelta(minutes=495):return 'Berita besar berada dalam rencana holding'
 return None
def project(calculations,market,native,*,now=None):
 now=now or datetime.now(UTC);rows=[]
 for calc in calculations:
  c=deepcopy(calc);symbol=c['symbol'];c.update(status='WAIT',entry=None,sl=None,tp=None,layers=[],blockers=[])
  if c.get('error'):
   c['reason']='Feed strategi BTC belum tersedia';rows.append(c);continue
  bar=stamp(c.get('bar_at'));limit=3660 if symbol=='BTCUSD' else (960 if symbol=='EURUSD' else 360)
  if not bar or not fresh(c.get('bar_at'),now,limit):
   c.update(status='DATA_TERLAMBAT',reason='Candle strategi belum diperbarui',areas=[],signal=None);rows.append(c);continue
  s=c.get('signal');c['status']='WATCH' if c.get('session_open') else 'WAIT';c['reason']='Menunggu pola dan penutupan candle sesuai strategi' if c.get('session_open') else 'Di luar jendela sinyal strategi'
  # The native window is <60 seconds for FX and <=5 seconds for BTC.
  valid_until=(stamp(s['at'])+timedelta(seconds=5 if symbol=='BTCUSD' else 60)) if s else None
  c['valid_until']=valid_until.isoformat() if valid_until else None
  if s and (not stamp(s['at']) or stamp(s['at'])>now or (now>=valid_until if symbol!='BTCUSD' else now>valid_until)):
   c['last_signal_at']=s['at'];c['signal']=None;s=None;c['reason']='Sinyal sebelumnya sudah lewat; tunggu sinyal baru'
  if s:
   c['status']='ENTRY_MANUAL';c['reason']='Pola entry kode beku terkonfirmasi; acuan untuk diperiksa manual'
   ns=(native.get('states') or {}).get(symbol) or {}
   if symbol in HASHES:
    if not market.get('account_binding') or market.get('account_binding')!=native.get('account_binding'):c['blockers'].append('Pembacaan broker dan checkpoint belum cocok pada akun yang sama')
    if ns.get('ContractHash')!=HASHES[symbol]:c['blockers'].append('Versi checkpoint cBot belum cocok')
    if not fresh(ns.get('LastBarUtc'),now,120):c['blockers'].append('Status terminal belum cukup baru')
    if ns.get('Quarantined'):c['blockers'].append('cBot sedang dikarantina')
    if ns.get('pending_intent') or ns.get('has_basket'):c['blockers'].append('cBot memiliki basket atau intent berjalan')
    for key in ['LastSignalUtc','LastRealExitUtc']:
     t=stamp(ns.get(key))
     if t and t>=stamp(s['at']):c['blockers'].append('Sinyal sudah diproses atau mendahului exit terakhir');break
    resume=stamp(ns.get('XauResumeUtc'))
    if symbol=='XAUUSD' and resume and now<resume:c['blockers'].append('Cooldown XAU belum selesai')
    if symbol=='XAUUSD':
     why=macro_reason(native.get('macro') or {},s,now)
     if why:c['blockers'].append(why)
     day=stamp(ns.get('XauDay'))
     if day and day.date()==(stamp(s['at'])+timedelta(hours=7)).date() and ns.get('XauDaySignals',0)>=6:c['blockers'].append('Batas basket harian XAU tercapai')
   else:
    # Native BTC permits only a five-second window and broker schedule; never infer it from weekday alone.
    c['blockers'].append('Jadwal broker dan readiness terminal BTC perlu diperiksa')
   q=(market.get('quotes') or {}).get(symbol) or {};bid=q.get('BID') or {};ask=q.get('ASK') or {}
   quote_ok=all(fresh(v.get('at'),now,15) and isinstance(v.get('price'),(int,float)) and math.isfinite(v['price']) and v['price']>0 for v in [bid,ask])
   if quote_ok and ask['price']>=bid['price']:
    spread=ask['price']-bid['price'];side=1 if s['side']=='BUY' else -1;entry=(ask if side==1 else bid)['price'];c['quote_at']=min(bid['at'],ask['at'])
    if symbol=='XAUUSD':
     entry+=side*.10;anchor=s['anchor']+(spread if side==-1 else 0);distance=max(.5,2.4*s['atr'],side*(entry-anchor))
    elif symbol=='BTCUSD':
     entry+=side*bid['price']*.0001;distance=s['distance']
     if side*(entry-s['anchor'])>.5*s['atr']:c['blockers'].append('Harga telah menjauh dari referensi BTC')
    else:distance=s['distance']
    if distance>0 and entry-side*distance>0:
     c.update(entry=entry,sl=entry-side*distance,tp=entry+side*distance*c['target_r'])
     c['layers']=[{'stage':i,'price':entry-side*distance*d,'depth':d,'confirmation':c['addition_confirmation'] and i>0} for i,d in enumerate(c['depths'])]
    if (symbol=='XAUUSD' and spread>1.5) or (symbol=='EURUSD' and spread>.00022):c['blockers'].append('Spread melebihi batas strategi')
   else:c['blockers'].append('Quote bid/ask belum cukup baru')
   if not fresh(native.get('as_of'),now,90):c['blockers'].append('Pembacaan checkpoint belum diperbarui')
   if market.get('foreign_exposure') or market.get('pending_orders'):c['blockers'].append('Ada posisi asing atau pending order; periksa exposure akun')
   if market.get('positions'):c['blockers'].append('Ada posisi portofolio; periksa risiko gabungan sebelum menambah')
   if c['blockers']:c['status']='BLOCK';c['reason']='; '.join(dict.fromkeys(c['blockers']))
  c['positions']=[p for p in market.get('positions',[]) if p.get('symbol')==symbol]
  if c['positions']:
   c.update(status='POSISI_AKTIF',reason='Posisi cBot teramati di broker; bukan entry baru',entry=None,sl=None,tp=None,layers=[])
  rows.append(c)
 return {'contract':CONTRACT,'as_of':now.isoformat(),'market_observed_at':market.get('as_of'),'native_observed_at':native.get('as_of'),'source_commit':SOURCE_COMMIT,'source_release':'V1.3.0','execution_authority':False,'execution_influence':False,'symbols':rows}
def validate(payload,*,now=None):
 now=now or datetime.now(UTC);p=deepcopy(payload)
 if p.get('contract')!=CONTRACT or p.get('source_commit')!=SOURCE_COMMIT or p.get('execution_authority') is not False or p.get('execution_influence') is not False:raise ValueError('Invalid monitor contract')
 p['fresh']=fresh(p.get('as_of'),now,90) and fresh(p.get('market_observed_at'),now,90)
 for c in p.get('symbols',[]):
  s=c.get('signal');expires=stamp(c.get('valid_until'))
  expired=s and (not expires or (now>=expires if c.get('symbol')!='BTCUSD' else now>expires))
  if not p['fresh'] or expired:
   c.update(status='DATA_TERLAMBAT' if not p['fresh'] else 'WAIT',reason='Data terlambat' if not p['fresh'] else 'Jendela entry sudah lewat; tunggu sinyal baru',entry=None,sl=None,tp=None,layers=[],signal=None)
   if not p['fresh']:c.update(areas=[],positions=[])
 return p
