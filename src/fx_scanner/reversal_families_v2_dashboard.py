"""Alternative reversal family research display; no order authority."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def render_reversal_families_v2_dashboard():
 import streamlit as st
 st.subheader('XAU · 20 keluarga alternatif · 20 juta kombinasi')
 st.caption('Mean reversion, exhaustion, false break sesi, breaker/FVG, kompresi. SL mikro M5; entry langsung atau retrace50%.')
 try:r=json.loads((ROOT/'calibration/reversal_families_v2_results.json').read_text())
 except (OSError,ValueError):
  st.info('Replay2016–2025 sedang berjalan. Angka peluang dan aturan terbaik belum tersedia.')
  st.caption('TP15–75% ADR20 berbeda dari batch sebelumnya; target15% tidak otomatis disebut reversal utama harian.')
  return
 qualified=[e for e in r.get('selected_by_side',[]) if e.get('qualified')]
 c=st.columns(3);c[0].metric('Kombinasi',f"{r.get('configurations_evaluated',0):,}".replace(',','.'));c[1].metric('Keluarga aturan',20);c[2].metric('Kandidat lolos',len(qualified))
 st.caption('Status: '+r.get('status','UNKNOWN')+'. TP-before-SL adalah peluang historis bersyarat pada trigger, filter dan fill.')
 if not qualified:st.warning('Belum ada kandidat yang lolos seluruh syarat. Persentase diagnostik tidak menjadi rekomendasi entry.')
 for e in r.get('selected_by_side',[]):
  cfg=e['config'];t=e.get('fresh_2026',{});h=cfg['session_utc']
  st.markdown('**'+('BUY' if cfg['side']==1 else 'SELL')+' · '+cfg['family']+' · '+('Lolos evaluasi kandidat2026' if e.get('qualified') else 'Penelitian / ditolak')+'**')
  st.write({'Entry':cfg['entry'],'SL buffer ATR5':cfg['stop_atr5'],'TP ADR20':cfg['target_adr_fraction'],'D1':cfg['regime'],'Konfirmasi':cfg['confirmation'],'Sesi WIB':f'{(h+7)%24:02d}:00–{(h+13)%24:02d}:00','Bagian sesi':cfg['session_phase'],'TP-before-SL2026':t.get('target_hit_rate'),'PF2026':t.get('profit_factor'),'Trade2026':t.get('n'),'Fillrate2026':t.get('fill_rate'),'Target rata-rata':t.get('mean_target_points'),'SL rata-rata':t.get('mean_risk_points')})
  with st.expander('Rincian kandidat'):st.json(e)
 with st.expander('Perbandingan20keluarga · diagnostik belum tervalidasi'):
  rows=[]
  for e in r.get('diagnostics_by_source',[]):
   cfg=e['config'];a=e['train'];b=e['validation'];h=cfg['session_utc']
   rows.append({'Arah':'BUY' if cfg['side']==1 else 'SELL','Keluarga':cfg['family'],'Entry':cfg['entry'],'TP ADR20':cfg['target_adr_fraction'],'D1':cfg['regime'],'Konfirmasi':cfg['confirmation'],'SesiWIB':f'{(h+7)%24:02d}–{(h+13)%24:02d}','Phase':cfg['session_phase'],'Ntrain':a['n'],'Nval':b['n'],'TP-hitval':round(b['target_hit_rate']*100,2),'PFtrain':round(a['profit_factor'] or 0,3),'PFval':round(b['profit_factor'] or 0,3),'Fillrateval':round(b['fill_rate']*100,2),'TP harga':round(b['mean_target_points'],2),'SL harga':round(b['mean_risk_points'],2),'Gagal':', '.join(e.get('failed_gates',[]))})
  st.dataframe(rows,hide_index=True,width="stretch")
 st.caption('Poin harga XAU/USD perounce, bukan dolar akun. Retest memakai modelM1konservatif, bukan jaminan limitfill broker. Notfilled dan censored terpisah; firstintent tidak diganti berdasarkan outcome. Confidence tidak dikoreksi banyak percobaan; cBot tetap terpisah.')
