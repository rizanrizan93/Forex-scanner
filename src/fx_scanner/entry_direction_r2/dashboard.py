"""Compact manual entry UI. Reads a public market-only snapshot, never accounts."""
from datetime import UTC,datetime
from urllib.request import Request,urlopen
import json,math
from .runtime_contract import CONTRACT,validate_snapshot

URL='https://rizan-bridge.duckdns.org:25345/bootstrap125/entry-direction-r2.json'

def fetch_snapshot(*,now=None,opener=urlopen):
 now=now or datetime.now(UTC)
 with opener(Request(URL+'?slot='+str(int(now.timestamp()//10)),headers={'Cache-Control':'no-cache','User-Agent':'RIZAN-Entry-R2/1'}),timeout=8) as response:raw=response.read(256*1024+1)
 if len(raw)>256*1024:raise ValueError('R2_SNAPSHOT_TOO_LARGE')
 return validate_snapshot(json.loads(raw),now=now)

def _price(v):return '—' if v is None else f'{float(v):,.2f}'
def _time(value):
 import pandas as pd
 try:return pd.Timestamp(value).tz_convert('Asia/Jakarta').strftime('%d/%m %H:%M:%S WIB')
 except (TypeError,ValueError):return '—'

def render_view(snapshot=None):
 import streamlit as st
 st.subheader('Arah Entry R2 · XAUUSD')
 st.caption('Model selektif · khusus SELL · keputusan entry manual')
 st.caption('Untuk zona BUY dan SELL, buka tab Manual R3. Model R2 belum memiliki kandidat BUY yang tervalidasi.')
 st.warning('Eksperimental. Validasi 2023–2024: 63,6% dari 110 sinyal; 2025: 43,1% dari 65 sinyal. Target akurasi 80% belum tercapai.')
 labels={'WAIT_DATA':'MENUNGGU DATA','WARMUP':'MENYIAPKAN DATA','WAIT_SESSION':'DI LUAR SESI','WATCH_SETUP':'PANTAU SETUP','WATCH_SCORE':'SKOR BELUM CUKUP','WAIT_LIMIT':'MENUNGGU JEDA','TRIGGER_SELL':'PEMICU SELL'}
 p=snapshot or {'status':'WAIT_DATA','direction':'WAIT','reason':'Sumber harga model sedang diperbarui','checks':[]}
 a,b,c=st.columns(3);a.metric('Status',labels.get(p['status'],'MENUNGGU DATA'));b.metric('Arah entry',p.get('direction','WAIT'));quote=p.get('quote') or {};c.metric('XAUUSD · bid',_price(quote.get('bid')))
 st.write(p.get('reason',''))
 st.caption('Candle XAU selesai '+_time(p.get('last_closed_m1'))+' · quote '+_time(quote.get('at')))
 if p.get('history'):st.caption('Riwayat XAU '+str(p['history'].get('XAUUSD',0))+' M1 · EUR '+str(p['history'].get('EURUSD',0))+' M1')
 candidate=p.get('candidate')
 if candidate:
  x,y=st.columns(2);x.metric('Skor seleksi',f"{100*candidate['score']:.2f}/100");y.metric('Ambang seleksi',f"{100*candidate['threshold']:.2f}/100")
  st.caption('Skor dipakai untuk menyaring setup; akurasi historis ditampilkan terpisah. Pemicu '+_time(candidate['signal_at']))
 if p.get('checks'):
  st.markdown('**Syarat entry R2**')
  st.dataframe([{'Syarat':r['label'],'Status':'Terpenuhi' if r['pass'] else 'Menunggu','Rincian':r['value']} for r in p['checks']],hide_index=True,width='stretch')
 signal=p.get('signal')
 if p['status']=='TRIGGER_SELL' and signal:
  st.success('Pemicu SELL selesai · cek harga dan tentukan entry manual')
  x,y,z=st.columns(3);x.metric('Acuan entry',_price(signal['reference']));y.metric('Patokan gerakan SELL',_price(signal['correct_direction_level']));z.metric('Patokan gerakan melawan',_price(signal['adverse_direction_level']))
  st.caption('Pengukuran arah ±0,25 ATR H1 dalam 60 menit. Jendela entry sampai '+_time(signal['valid_until'])+'. Patokan ini belum menjadi aturan exit yang diuji.')
  if st.session_state.get('_entry_r2_alert')!=signal['signal_id']:st.toast('Pemicu SELL R2 baru');st.session_state['_entry_r2_alert']=signal['signal_id']
 elif signal:st.caption('Sinyal teramati terakhir: SELL · '+_time(signal.get('signal_at'))+' · acuan '+_price(signal.get('reference'))+'. Tunggu pemicu baru.')
 if p.get('observed_since'):st.caption('Observasi panel sejak '+_time(p['observed_since'])+' · '+str(p.get('signals_today',0))+'/2 sinyal teramati hari ini')
 with st.expander('Hasil historis dan cara membaca',expanded=False):
  st.dataframe([{'Periode':'2022 H2 · pengembangan','Sinyal':30,'Arah benar':22,'Akurasi':'73,3%'},{'Periode':'2023–2024 · validasi','Sinyal':110,'Arah benar':70,'Akurasi':'63,6%'},{'Periode':'2025','Sinyal':65,'Arah benar':28,'Akurasi':'43,1%'},{'Periode':'Q1 2026','Sinyal':24,'Arah benar':14,'Akurasi':'58,3%'}],hide_index=True,width='stretch')
  st.write('R2 menggabungkan model HGB dan ExtraTrees dengan fitur harga XAU/EUR, struktur, volatilitas, dan sesi. Model terakhir yang terpilih hanya menilai setup SELL. BUY menunggu penelitian terpisah.')
  st.write('Arah dinilai benar bila BID chart bergerak 0,25 ATR sesuai prediksi sebelum bergerak 0,25 ATR melawannya, dalam 60 menit. Angka arah dan hasil setelah spread/biaya dihitung terpisah.')
  st.write('Pada 26 kasus SELL 2025 yang arah awalnya benar dan pullback teramati, median puncak close sebelum pullback 0,25 ATR adalah sekitar US$4,05/ons. Angka ini bersyarat dan diketahui sesudah kejadian, bukan target untuk setiap sinyal.')
  st.caption('Data replay: arsip Dukascopy BID M1; data panel: cTrader/FP Markets. Spread menit teramati dihitung dari quote historis. Belum ada validasi native broker yang menyatakan akurasi sama. Periode telah digunakan dalam riset terdahulu.')
 st.caption('Panel pemantauan manual. Model tidak memiliki fungsi pengiriman order.')

def render_entry_direction():
 import streamlit as st
 @st.cache_data(ttl=5,show_spinner=False)
 def load(slot):return fetch_snapshot()
 @st.fragment(run_every='10s')
 def panel():
  try:p=load(int(datetime.now(UTC).timestamp()//5))
  except (OSError,ValueError,TypeError,KeyError,TimeoutError,ImportError):p=None
  render_view(p)
 panel()
