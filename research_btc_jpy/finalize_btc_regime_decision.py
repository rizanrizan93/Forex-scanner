import pathlib,hashlib,zipfile,json,csv,shutil,os
import pandas as pd
R=pathlib.Path.cwd();download=R/'downloaded';out=R/'decision_results';out.mkdir(exist_ok=True)
p=download/'RIZAN_BTC_ENTRY_EXIT_REGIME_RESEARCH.zip';expected=(download/'PACKAGE_SHA256.txt').read_text().split()[0];assert hashlib.sha256(p.read_bytes()).hexdigest()==expected
with zipfile.ZipFile(p) as z:assert z.testzip() is None;z.extractall(out)
m=pd.read_csv(out/'MANIFEST_SHA256.csv')
for _,r in m.iterrows():
 x=out/r.path;assert x.stat().st_size==r.bytes and hashlib.sha256(x.read_bytes()).hexdigest()==r.sha256
base=pd.read_csv(out/'FINAL_METRICS.csv');b=base[base.id==289].iloc[0];stress=pd.read_csv(out/'LOCKED_STRESS.csv');s=stress[stress.id==289].copy();y=pd.read_csv(out/'YEARLY.csv');y=y[y.id==289].copy();con=pd.read_csv(out/'DIRECTIONAL_CONTRIBUTIONS.csv');con=con[con.id==289].copy();cat=pd.read_csv(out/'CATALOG.csv')
assert b.buy_pnl>0 and b.sell_pnl>0 and b.floating_dd<=56 and b.y2025>0 and b.y2026>0
assert (s[s['case'].isin(['BASE','COST1_5','COST2','DELAY_NEXT_M1'])].floating_dd<=56).all()
config=dict(id=289,initial_USD=100,topups=0,leverage=10,margin_fraction=.5,buy_risk_budget=.15,sell_risk_budget=.075,layers=0,buy_profile=5989,sell_profile=7488,profile_details=cat[cat.profile.isin([5989,7488])].to_dict('records'),shared_balance=True,one_active_basket=True,simultaneous_opposing_signals='DISCARD_BOTH',selection_status='One of four pre2025 ranked finalists; highlighted after fullperiod/stress inspection; not untouched OOS')
(out/'CHALLENGER_289_CONFIG.json').write_text(json.dumps(config,indent=2))
s.to_csv(out/'CHALLENGER_289_STRESS.csv',index=False);y.to_csv(out/'CHALLENGER_289_YEARLY.csv',index=False);con.to_csv(out/'CHALLENGER_289_CONTRIBUTIONS.csv',index=False)
comparison=pd.DataFrame([dict(candidate='Old287447',final_balance=1407536.806952766,floating_dd=55.14158634233607,pf=1.4776513991633091,buy_net=1477890.1418330404,sell_net=-70453.33488027364,return2025=69.696642,return2026=-40.80506688785429),dict(candidate='Challenger289',final_balance=b.equity,floating_dd=b.floating_dd,pf=b.pf,buy_net=b.buy_pnl,sell_net=b.sell_pnl,return2025=float(y[y.period==2025].return_pct.iloc[0]),return2026=float(y[y.period==2026].return_pct.iloc[0]))]);comparison.to_csv(out/'COMPARISON_WITH_BASELINE.csv',index=False)
st=s[['case','equity','floating_dd','balance_dd','pf','trades','buys','sells','y2026']].copy()
report=f'''# BTCUSD — keputusan perbaikan entry, SL, TP dan syarat pasar

**Ditemukan challenger riset yang lebih berimbang, tetapi target $600.000 belum tercapai.** ID289 menghasilkan saldo ${b.equity:,.2f} dari $100 tanpa top-up pada1Januari2019–15Oktober2026. FloatingDD {b.floating_dd:.6f}%,balanceDD {b.balance_dd:.6f}%,PF {b.pf:.6f},winrate {b.win_rate:.6f}%,117basket(66BUY,51SELL),tanpalayer.

## Perbandingan yang harus dibaca bersama

{comparison.to_markdown(index=False,floatfmt='.6f')}

BUY dan SELL sama-sama memberi profit bersih sepanjang replay. SELL menyumbang sekitar26,79% dari net profit; bukan sekadar diaktifkan dengan satu transaksi. Pada2021BUY merugi tetapi SELL membuat tahun tetap positif;2022 seluruh profit berasal dari SELL. Pada2026SELL positif mengimbangi sebagian rugi BUY. Tahun2025dan2026 tetap negatif. Ini bukti diversifikasi historis yang lebih baik daripada kandidat lama,bukan bukti bebas ketergantungan regime atau unggul dalam semua kondisi. Saldo akhir jauh lebih kecil dan PF baseline tetap lebih tinggi.

## Aturan BUY — profile5989

- TimeframeH4,keluarga inside_break. Candle sebelumnya harus berada di dalam range candle dua bar sebelumnya; candle sinyal menutup di atas high insidebar ditambah0,1ATR14.
- Tunggu satu candleH4 berikutnya CLOSED di atas high candle sinyal. Entry market pada open berikutnya.
- D1 CLOSED bullish(close>EMA80 dan EMA20>EMA80);H4 tidak boleh bearish.
- SL1,5ATR14 dari fill;ATR berasal dari candle konfirmasi CLOSED. TP6R. Maksimalhold8H4=32jam sejak sinyal tersedia. Tidak memakai BE atau trailing pada BUY.
- Budget risiko15% dari saldo saat entry,margin50%. Budget adalah batas model sizing,bukan kerugian pasti15%.

## Aturan SELL — profile7488

- TimeframeH4,keluarga ema_cross. EMA20 menyeberang ke bawah EMA80 pada candle CLOSED,dengan body turun lebih dari0,1ATR14.
- H4 CLOSED bearish(close<EMA80 dan EMA20<EMA80). Entry open setelah candle tersebut CLOSED.
- SL di atas high candle sinyal ditambah spread model dan buffer0,15ATR;jarak fill–SL harus0,5–3ATR. TP6R;holdmaksimal16H4=64jam.
- Setelah closeM1 mencapai profit1,5R,SL dapat mengikuti close dikurangi jarak1,5R ke arah berlawanan posisi;untuk SELL:SL=closeASK+1,5R. SL hanya diketatkan dan baru berlaku pada menit berikutnya.
- Budget risiko7,5%,margin50%.

## Filter dan eksekusi bersama

Entry ditolak jika fill sudah lebih dari0,5ATR melewati close sinyal/konfirmasi searah posisi. Body candle maksimum2,5ATR. BUY ditolak jikaRSI>75;SELL ditolak jikaRSI<25. ATR14 dibanding ATR20bar sebelumnya harus0,6–1,8. Semua indikator dan regime memakai candle yang sudah selesai.

Satu saldo,margin,compounding dan state eksekusi bersama. Satu basket aktif,sinyal saatbusy diabaikan,sinyal BUYdanSELL bersamaan dibuang keduanya. Minimum/step0,01BTC,max100BTC,leverage10×,spread5bp,komisi5bp/sisi,slippage1bp/sisi,financingdebit3bp/hari kedua arah. Stop-first untuk ambiguM1,gapSL memakaiopen lebih buruk. Tidakada penjumlahan dua rekening,top-up,reset modal,atauaturan kalender perdagangan.

## Kontribusi arah

{con.to_markdown(index=False,floatfmt='.6f')}

## Hasil per tahun

{y.to_markdown(index=False,floatfmt='.6f')}

2026:6BUY,2menang,net-$386,16;2SELL,keduanya menang,net+$276,51. Netgabungan-$109,65 atau-7,6614%. Dua kemenangan SELL merupakan sampel kecil dan tidak menjamin kejadian serupa di masa depan.

## Stress konfigurasi terkunci

{st.to_markdown(index=False,floatfmt='.6f')}

Biaya1,5×/2× hanya mengalikan komisi/slippage/financing;spread tetap5bp. Delay entry satu menit. Leverage2dan5 adalah absolut. Pada leverage2,minvolume menyebabkan banyak penolakan dan tidak ada transaksi2021–2026;DD kecil skenario itu bukan bukti ketahanan. Leverage5masihaktif2026. Empat kondisi normal/biaya/delay mempertahankan floatingDD<=56% pada sampelini,tetapi tidak mencapai targetsaldo600k.

## Proses seleksi dan batas kesimpulan

Batch1 menguji7776konfigurasiarah;hasil utamanya ditolak karena berhenti mendapat order pada tahunakhir. Batch2 menguji15552konfigurasiarah dari7776geometri(12keluargadasar,H1/H4,variasientry/regime/SL/TP/hold/exit),dan2880pasangan sizing.

Diagnostik kualitas profile memakai modal10000USD untuk mengurangi distorsi minimumlot. Seleksi pasangan memakaiTRAIN2019–2022 dari100USD danVALID2023–2024 dari10000USD,returndinormalisasi serta minimal3basket setiap tahun di segmen seleksi. Modal diagnostik tidak pernah dijumlahkan atau dipindahkan ke replayakhir. Replay penuh2019–2026 tetap dimulai100USD,tanpatopup/reset.

ID290 adalah peringkat utama sebelum2025,tetap dilaporkan meskiDDpenuh60,38%. ID289 termasuk empat finalis yang dikunci dari data sampai2024;baru disorot sebagai challenger setelah hasilperiodepenuh danstress dilihat.2025–2026 sudah pernah dilihat pada penelitian lama dan memotivasi perbaikanini,jadi bukan untouchedOOS. Optimasi ulang pada riwayat yang sama tidak membuktikan keunggulan masa depan.

Ledger semua30skenario finalis direkonsiliasi independen:grossPnL,komisi,financing dihitung ulang dari setiapopenM1,net,saldokumulatif,jumlaharah serta tidakadaposisi overlap. Error maksimum sekitar5,16e-11USD. Semua109file paket sumberdiverifikasiSHA256. Fixture9warisan+5tambahan dan reproduksibaselinelama lulus.

Input BitstampOHLCM1,bukan tickbidaskbroker;SHA256CSV c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504. FloatingDDperM1 memakaiOHLCboundwarisan;grafiksnapshotjam. Capitalfloor dan prioritasexpiry/SL/TPsebelumfallbackstopout diwarisi. BukanFULL_PARITY. Tidakadaorder,perubahanlive,bridge,envproduksi,ataumergemain. Kandidatlama tetaptersimpan.

Source/model commit:b95ded260f5f00e1e059be934c418d586a70ce4a
Search/audit:https://github.com/rizanrizan93/Forex-scanner/actions/runs/39339805695
Reviewcommit:{os.environ['GITHUB_SHA']}
Review:https://github.com/rizanrizan93/Forex-scanner/actions/runs/{os.environ['GITHUB_RUN_ID']}

**Keputusan: kandidat289 menjadi challenger riset entry/exit dan diversifikasi,bukan pengganti live atau solusi final target600k.**
'''
(out/'LAPORAN_KEPUTUSAN_BTC_CHALLENGER_289.md').write_text(report)
shutil.copy2(out/'PAIR_289_EQUITY_DD.png',out/'CHALLENGER_289_EQUITY_DD.png')
shutil.copy2(R/'research_btc_jpy/finalize_btc_regime_decision.py',out/'finalize_btc_regime_decision.py')
(out/'DECISION_PROVENANCE.json').write_text(json.dumps(dict(source_package_sha256=expected,source_run=39339805695,review_commit=os.environ['GITHUB_SHA'],review_run=os.environ['GITHUB_RUN_ID'],challenger=289,changes_live=False,old600k_target_met=False),indent=2))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
with (out/'MANIFEST_SHA256.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['path','sha256','bytes'])
 for x in sorted(out.rglob('*')):
  if x.is_file() and x.name not in ['MANIFEST_SHA256.csv','PACKAGE_SHA256.txt']:w.writerow([str(x.relative_to(out)),sha(x),x.stat().st_size])
package=out/'RIZAN_BTC_CHALLENGER_289_AUDITED.zip'
with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
 for x in sorted(out.rglob('*')):
  if x.is_file() and x!=package and x.name!='PACKAGE_SHA256.txt':z.write(x,str(x.relative_to(out)))
with zipfile.ZipFile(package) as z:assert z.testzip() is None
(out/'PACKAGE_SHA256.txt').write_text(sha(package)+'  '+package.name+'\n')
print(comparison.to_markdown(index=False),flush=True);print(st.to_markdown(index=False),flush=True)
