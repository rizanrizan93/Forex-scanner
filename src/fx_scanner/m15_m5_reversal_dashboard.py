"""Research display for M15 sweep/M5 confirmation; no order authority."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def render_m15_m5_reversal_dashboard():
 import streamlit as st
 st.subheader('XAU · reversal M15 → konfirmasi M5 · 1 juta kombinasi')
 st.caption('Level harian/sesi dan konteks H1; M15 sweep/reclaim, M5 displacement dalam 30 menit. Khusus scanner.')
 try:r=json.loads((ROOT/'calibration/m15_m5_reversal_results.json').read_text())
 except (OSError,ValueError):
  st.info('Replay 2016–2025 sedang berjalan. Belum ada probabilitas atau zona dari batch ini yang tervalidasi.')
  return
 qualified=[x for x in r.get('selected_by_side',[]) if x.get('qualified')]
 c=st.columns(3);c[0].metric('Kombinasi diuji',f"{r.get('configurations_evaluated',0):,}".replace(',','.'));c[1].metric('Periode','2016–2025');c[2].metric('Konfigurasi lolos',len(qualified))
 if not qualified:st.warning('Belum ada konfigurasi batch ini yang lolos seluruh syarat profit, biaya dan kestabilan. Kandidat penelitian tidak menjadi rekomendasi entry.')
 else:st.success('Ada kandidat lolos pengujian kandidat 2026; lihat ukuran sampel dan batas hasil historis.')
 st.caption('Status: '+r.get('status','UNKNOWN')+'. TP sebelum SL berbeda dari trade net positif. Banyak tuple berbagi keputusan; ranking bukan confidence terkoreksi banyak percobaan.')
 rows=[]
 for e in r.get('diagnostic_examples',[]):
  cfg=e['config'];a=e['train'];b=e['validation'];h=cfg['session_utc']
  rows.append({'Arah':'BUY' if cfg['side']==1 else 'SELL','Anchor':cfg['zone_source'],'Sesi WIB':f'{(h+7)%24:02d}:00–{(h+13)%24:02d}:00',
   'N train':a['n'],'N validation':b['n'],'TP sebelum SL train':f"{a['target_hit_rate']:.1%}",'TP sebelum SL validation':f"{b['target_hit_rate']:.1%}",
   'PF train':round(a['profit_factor'] or 0,3),'PF validation':round(b['profit_factor'] or 0,3),'TP / ADR20':f"{cfg['target_adr_fraction']:.0%}",'Buffer SL / ATR H1':cfg['stop_extension_atr'],'Status':'PENELITIAN'})
 if rows:
  with st.expander('Contoh penelitian · probabilitas historis deskriptif'):
   st.dataframe(rows,hide_index=True,width="stretch")
   st.caption('Jam ini belum disebut waktu reversal terbaik. SL di luar ekstrem seed M15 +buffer; jarak harga berubah sesuai volatilitas.')
 for e in r.get('selected_by_side',[]):
  st.json({'config':e['config'],'train':e.get('train'),'validation':e.get('validation'),'test_2026':e.get('fresh_2026'),'qualified':e.get('qualified',False)})
