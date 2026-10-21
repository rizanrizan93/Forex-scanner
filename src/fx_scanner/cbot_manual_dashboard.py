"""Read-only cBot strategy monitor, isolated from all order modules."""
from datetime import UTC,datetime
from .manual_reversal_dashboard import read_json
from .cbot_manual import stamp
def wib(value):
 d=stamp(value)
 if not d:return "—"
 from zoneinfo import ZoneInfo
 return d.astimezone(ZoneInfo("Asia/Jakarta")).strftime("%d/%m %H:%M:%S WIB")
from .cbot_manual import validate
BASE='https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/'
BRANCH='cbot-manual-snapshots';PATH='/runtime/cbot_manual_snapshot.json'
from functools import lru_cache
import base64,json
_LAST_GOOD=None
@lru_cache(maxsize=4)
def _api_snapshot(bucket):
 # Shared process cache bounds anonymous API fallback traffic to 40 calls/hour.
 meta=read_json('https://api.github.com/repos/rizanrizan93/Forex-scanner/contents'+PATH+'?ref='+BRANCH)
 if meta.get('encoding')!='base64':raise ValueError('Unsupported snapshot encoding')
 raw=base64.b64decode(meta['content'],validate=False)
 if len(raw)>900000:raise ValueError('Snapshot too large')
 return json.loads(raw)
def fetch():
 global _LAST_GOOD
 now=datetime.now(UTC);bucket=int(now.timestamp()//15);candidate=None
 try:
  candidate=read_json(BASE+BRANCH+PATH+'?minute='+str(bucket))
  p=validate(candidate)
  _LAST_GOOD=candidate
  if p['fresh']:return p
 except (ValueError,OSError,KeyError,TypeError):pass
 try:
  candidate=_api_snapshot(int(now.timestamp()//90))
  p=validate(candidate)
  _LAST_GOOD=candidate
  return p
 except (ValueError,OSError,KeyError,TypeError):
  if _LAST_GOOD is not None:return validate(_LAST_GOOD)
  raise ValueError('Snapshot unavailable')
def render_snapshot(payload):
 import streamlit as st
 p=validate(payload)
 st.subheader('cBots · persiapan dan entry manual')
 st.caption('Strategi beku XAU–EUR–BTC V1.3.0 · pembacaan pasar dan posisi saja')
 st.caption('Perhitungan memakai kode sinyal cBot. Ini cermin terpisah: perbedaan history pemanasan dan status terminal dapat menghasilkan keputusan berbeda. Periksa volume, margin, posisi, dan harga di cTrader sebelum entry manual.')
 if not p['fresh']:st.warning('WAIT · pembaruan terlambat. Hanya area pantauan terakhir ditampilkan beserta waktunya; entry dan posisi lama disembunyikan.')
 st.caption('Pembaruan '+wib(p['as_of'])+' · tampilan mengecek 10 detik')
 labels={'ENTRY_MANUAL':'ENTRY · acuan manual','WATCH':'WATCH · persiapan','WAIT':'WAIT · menunggu','BLOCK':'BLOCK · syarat belum lengkap','POSISI_AKTIF':'POSISI AKTIF','DATA_TERLAMBAT':'WAIT · data terlambat'}
 for c in p.get('symbols',[]):
  symbol=c['symbol'];digits=5 if symbol=='EURUSD' else 2
  st.markdown('### '+symbol+' · '+labels.get(c['status'],c['status']))
  st.write(c['reason'])
  if c.get('bar_at'):st.caption('Candle strategi selesai '+wib(c['bar_at']))
  for area in c.get('areas',[]) or c.get('reference_areas',[]):
   st.metric(area['side']+(' · area terakhir (bukan entry)' if not p['fresh'] else ' · level pemicu'),f"{area['low']:,.{digits}f}" if area['low']==area['high'] else f"{area['low']:,.{digits}f}–{area['high']:,.{digits}f}")
   st.caption(area['condition'])
  if symbol=='BTCUSD' and not c.get('error'):st.caption('BUY: momentum H4 bullish sesi awal UTC. SELL: breakout bawah range H1 dengan tren H4 bearish dan filter volatilitas/RSI. Feed Bitstamp tujuh hari; jadwal broker tetap wajib.')
  if c.get('signal'):
   st.write('**'+c['signal']['side']+' · konfirmasi '+wib(c['signal']['at'])+'**')
   st.caption('Berlaku sampai '+wib(c.get('valid_until'))+'; sinyal lama tidak boleh dikejar.')
  if c.get('entry') is not None:
   for label,key in [('Entry referensi','entry'),('SL skenario','sl'),('TP skenario','tp')]:st.metric(label,f"{c[key]:,.{digits}f}")
   if c['status']=='BLOCK':st.caption('Level skenario saja; syarat entry belum lengkap.')
   st.caption('Quote '+wib(c.get('quote_at'))+' · lot mengikuti pemeriksaan equity dan margin di cTrader')
   if c.get('layers'):
    st.dataframe([{'Tahap':'Awal' if x['stage']==0 else 'Layer '+str(x['stage']),'Level acuan':round(x['price'],digits),'Kedalaman R':x['depth'],'Syarat':'Konfirmasi baru' if x['confirmation'] else 'Sesuai pemicu strategi'} for x in c['layers']],hide_index=True,width='stretch')
  for pos in c.get('positions',[]):
   st.write('**'+pos['side']+' · posisi broker**')
   for label,key in [('Entry posisi','entry'),('SL posisi','sl'),('TP posisi','tp')]:
    if pos.get(key):st.metric(label,f"{pos[key]:,.{digits}f}")
  st.divider()
def _render():
 import streamlit as st
 load=st.cache_data(ttl=8,show_spinner=False)(fetch)
 try:render_snapshot(load())
 except Exception:
  st.subheader('cBots · persiapan dan entry manual')
  st.warning('WAIT · koneksi feed sedang terganggu. Dashboard mencoba ulang otomatis; belum ada entry baru yang dapat diverifikasi.')
def render_cbot_manual_dashboard():
 import streamlit as st
 st.fragment(run_every='10s')(_render)()
