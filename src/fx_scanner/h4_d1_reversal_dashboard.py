"""Display-only H4/D1 reversal study; no execution authority."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def render_h4_d1_reversal_dashboard():
 import streamlit as st
 st.subheader('XAU · zona H4 + regime D1 · 20 juta kombinasi')
 st.caption('Order block H4, pivot terkonfirmasi, range H4/D1 dan liquidity sweep. TP ≥25% ADR20; konteks D1 dari candle tertutup.')
 try:r=json.loads((ROOT/'calibration/h4_d1_reversal_results.json').read_text())
 except (OSError,ValueError):
  st.info('Replay 2016–2025 sedang berjalan. Probabilitas titik balik dan zona hasil batch ini belum tervalidasi.')
  st.caption('Sentuhan, reclaim M5/M15 dan sweep dibandingkan secara terpisah. Pivot/OB tidak ditandai mundur.')
  return
 qualified=[e for e in r.get('selected_by_side',[]) if e.get('qualified')]
 c=st.columns(3);c[0].metric('Kombinasi diuji',f"{r.get('configurations_evaluated',0):,}".replace(',','.'));c[1].metric('Periode','2016–2025');c[2].metric('Kandidat lolos',len(qualified))
 st.caption('Status: '+r.get('status','UNKNOWN')+'. Peluang TP-before-SL adalah ukuran historis bersyarat, bukan jaminan reversal.')
 if not qualified:st.warning('Belum ada konfigurasi yang lolos seluruh syarat profit, biaya dan kestabilan; contoh penelitian tidak menjadi rekomendasi entry.')
 for e in r.get('selected_by_side',[]):
  cfg=e['config'];test=e.get('fresh_2026',{});h=cfg['session_utc']
  st.markdown('**'+('BUY' if cfg['side']==1 else 'SELL')+' · '+cfg['zone_source']+' · '+('Lolos evaluasi kandidat 2026' if e.get('qualified') else 'Kandidat tidak lolos / penelitian')+'**')
  st.write({'Regime D1':cfg['regime'],'Konfirmasi':cfg['confirmation'],'Sesi WIB':f'{(h+7)%24:02d}:00–{(h+13)%24:02d}:00','Target ADR20':cfg['target_adr_fraction'],'TP sebelum SL 2026':test.get('target_hit_rate'),'PF 2026':test.get('profit_factor'),'N 2026':test.get('n')})
  with st.expander('Rincian kandidat'):st.json(e)
 examples=r.get('diagnostic_examples',[])
 if examples:
  with st.expander('Contoh deskriptif terbaik per sisi · belum tervalidasi'):
   rows=[]
   for e in examples:
    cfg=e['config'];a=e['train'];b=e['validation'];h=cfg['session_utc']
    rows.append({'Arah':'BUY' if cfg['side']==1 else 'SELL','Zona':cfg['zone_source'],'D1':cfg['regime'],'Konfirmasi':cfg['confirmation'],'Sesi WIB':f'{(h+7)%24:02d}:00–{(h+13)%24:02d}:00','N train':a['n'],'N validation':b['n'],'TP-hit train':f"{a['target_hit_rate']:.1%}",'TP-hit validation':f"{b['target_hit_rate']:.1%}",'PF train':round(a['profit_factor'] or 0,3),'PF validation':round(b['profit_factor'] or 0,3),'TP rata-rata':round(b['mean_target_points'],2),'SL rata-rata':round(b['mean_risk_points'],2),'Gagal':', '.join(e.get('failed_gates',[]))})
   st.dataframe(rows,hide_index=True,width="stretch")
   st.caption('Jarak dalam poin harga XAU/USD per ounce, bukan nominal akun. Censored dikeluarkan dari peluang; lihat ukurannya di rincian. Jam belum disebut waktu terbaik tanpa kelulusan.')
   st.json(examples)
 st.caption('Synthetic spread/slippage; beberapa tuple berbagi keputusan. Confidence tidak dikoreksi banyak pencarian. Tidak ada perubahan strategy/execution cBot.')
 try:sensitivity=json.loads((ROOT/'calibration/h4_d1_sensitivity_results.json').read_text())
 except (OSError,ValueError):sensitivity={}
 if sensitivity:
  with st.expander('Pivot H4 · sensitivitas biaya · tidak dipromosikan'):
   st.caption('Dua tuple lolos PF train/validation pada biaya cautious, tetapi gagal biaya stress. Audit 2026 ini bersifat eksploratif dan tidak mengubah kelulusan utama.')
   for e in sensitivity.get('selected_by_side',[]):
    cfg=e['config'];a=e['train'];b=e['validation'];t=e.get('test_2026',{});h=cfg['session_utc']
    st.write({'Arah':'BUY' if cfg['side']==1 else 'SELL','Zona':cfg['zone_source'],'D1':cfg['regime'],'Konfirmasi':cfg['confirmation'],'Sesi WIB':f'{(h+7)%24:02d}:00–{(h+13)%24:02d}:00','PF train':a['profit_factor'],'PF validation':b['profit_factor'],'PF 2026':t.get('profit_factor'),'TP sebelum SL 2026':t.get('target_hit_rate'),'N 2026':t.get('n'),'Expectancy stress validation':b['mean_stress_r'],'Status':'PENELITIAN SAJA'})
    st.json(e)
 with st.expander('Perbandingan sepuluh keluarga zona · diagnostik'):
  st.dataframe([{'Arah':'BUY' if e['config']['side']==1 else 'SELL','Zona':e['config']['zone_source'],'D1':e['config']['regime'],'Konfirmasi':e['config']['confirmation'],'N validation':e['validation']['n'],'TP-hit validation':round(e['validation']['target_hit_rate']*100,2),'PF train':round(e['train']['profit_factor'] or 0,3),'PF validation':round(e['validation']['profit_factor'] or 0,3)} for e in r.get('diagnostics_by_source',[])],hide_index=True,width="stretch")
