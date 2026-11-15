"""Build auditable Indonesian reports from executed CSV/log evidence only."""
import json,pathlib,hashlib,platform,datetime,sys
import numpy as np,pandas as pd
from analyze import prepared,metrics
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'results';REPORTS=ROOT/'reports';REPORTS.mkdir(exist_ok=True)
def table(df):
 def fmt(x):
  if pd.isna(x):return 'N/A'
  if isinstance(x,(float,np.floating)):return f'{x:,.4f}'
  return str(x).replace('|','/')
 cols=list(df.columns);return '| '+' | '.join(cols)+' |\n| '+' | '.join(['---']*len(cols))+' |\n'+'\n'.join('| '+' | '.join(fmt(v) for v in row)+' |' for row in df.itertuples(index=False,name=None))+'\n'
def write(name,text): (REPORTS/name).write_text(text,encoding='utf-8')
def main():
 selected=json.loads((OUT/'selected_ids.json').read_text());ids=[x for x in selected if '_ASIA_FULL_' in x]
 period=pd.read_csv(OUT/'period_metrics.csv');full=period[(period.candidate.isin(ids))&(period.period=='OOS')].sort_values('profit_factor',ascending=False)
 ticks=json.loads((ROOT/'audit/tick_integrity.json').read_text());n=sum(x['rows'] for x in ticks)
 macro=pd.read_csv(ROOT/'audit/treasury_daily_descriptive.csv');corr=pd.read_csv(OUT/'macro_gold_correlations_descriptive.csv');corr=corr[corr.period=='ALL']
 fee=[]
 scenario_names=['BASE_PERIODS','STRESS15_PERIODS','STRESS20_PERIODS','ZERO_DIAGNOSTIC_PERIODS','BASE_COMPOUND_PERIODS','BASE_COMPOUND_100_PERIODS']
 for name in scenario_names:
  t=prepared(pd.read_csv(OUT/name/'trades.csv.gz'));initial=100. if '_100_' in name else 10000.
  for key in ids:
   q=t[(t.candidate==key)&(t.year>=2024)];fee.append({'scenario':name,'candidate':key,**metrics(q,initial,27)})
 fee=pd.DataFrame(fee);fee.to_csv(OUT/'cost_and_sizing_metrics.csv',index=False)
 annual=pd.read_csv(OUT/'annual_all_candidates.csv');ann=annual[annual.candidate.isin(ids)].pivot(index='year',columns='candidate',values='ending_equity');ann.columns=[x.split('_ASIA_FULL_')[0] for x in ann.columns];ann=ann.reset_index()
 boot=pd.read_csv(OUT/'oos_block_bootstrap.csv');sens=pd.read_csv(OUT/'parameter_sensitivity.csv') if (OUT/'parameter_sensitivity.csv').exists() else pd.DataFrame()
 extra=pd.read_csv(OUT/'exploratory_candidate_metrics.csv') if (OUT/'exploratory_candidate_metrics.csv').exists() else pd.DataFrame()
 eb=json.loads((OUT/'exploratory_candidate_bootstrap.json').read_text()) if (OUT/'exploratory_candidate_bootstrap.json').exists() else {}
 phases=pd.DataFrame([
 ['1 Audit','PARTIAL','Repository dan source teridentifikasi; tick hanya Jan2019–Mar2026; baseline belum replay native.'],
 ['2 Yield/DXY model','BLOCKED','Histori kuotasi yield intraday, DXY terverifikasi dan first-seen/vintage belum tersedia. Daily resmi telah diunduh; API model belum dilatih.'],
 ['3 Statistik sesi','PARTIAL','Profil per jam/sesi/hari/bulan/tahun dan liquidity selesai pada cakupan tersedia; news/macro regime belum terverifikasi.'],
 ['4 Setup/replay','PARTIAL','75 kombinasi harga/SMC dieksekusi; setup A/E yang memerlukan makro belum dijalankan.'],
 ['5 Kombinasi makro/Asia','BLOCKED','Tidak ada panel makro PIT sah; tidak membuat ablation atau profit gabungan fiktif.'],
 ['6 Robustness/portfolio','PARTIAL','Split independen, annual reset, walk-forward, biaya, bootstrap dan sensitivitas dieksekusi; portfolio Frozen belum.'],
 ['7 Laporan/package','PARTIAL','Paket R1 dan hasil yang tersedia disusun; target penelitian keseluruhan belum COMPLETE.']
 ],columns=['Fase','Status','Bukti/batas'])
 overview=f'''# RIZAN XAU — Treasury Yield Nowcast & Asian Session Alpha R1

Tanggal penelitian:15November2026 WIB. **Status keseluruhan:PARTIAL.** Tidak ada order real, perubahan Frozen V1, restart layanan, perubahan dashboard, atau penulisan checkpoint LIVE.

**Temuan utama:** lima hipotesis harga/SMC sesi08.00–13.00WIB dengan parameter yang dipilih dari2019–2021 tidak menghasilkan expectancy positif setelah biaya pada test historis2024–Maret2026. Model yield/DXY dan gabungan dengan Frozen belum mempunyai bukti hasil yang sah. Rekomendasi operasional sementara:A, pertahankan konfigurasi existing dan jangan menambahkan strategi Asia R1. Ini belum membuktikan keunggulan kuantitatif Frozen terhadap seluruh alternatif.

**Data yang benar-benar diuji:**{n:,} tick XAUUSD dalam87file bulanan, Januari2019–Maret2026.2026 hanya YTD sampai31Maret; tidak mencakup April–November. Seluruh87SHA256 cocok dengan manifest VPS. Audit struktural menemukan0harga invalid/crossed dan0timestamp terbalik. Terdapat{sum(x['adjacent_exact_duplicates'] for x in ticks):,} kuotasi berurutan dengan timestamp/bid/ask sama; volume tidak dibandingkan, sehingga ini bukan bukti seluruhnya duplikasi transaksi. Kuotasi dipertahankan. Cek silang empat jam ke sumber Dukascopy asli gagal HTTP429; parity sumber independen belum disahkan.

**Akun pengujian:**USD10.000, risk budget awal USD50/trade, leverage1:200, satu posisi, maksimum3entry/hari. Biaya BASE:bid/ask Dukascopy asli, slippageUSD0,10/oz per market execution, komisiUSD6/lot round-turn. Komisi mengacu pada halaman FP Markets cTrader Raw saat penelitian, bukan arsip biaya historis akun. Data ini bukan tick FP Markets. Batas lot/step diasumsikan0,01lot=1oz; margin masuk dibatasi20% equity. Spesifikasi broker historis, stop-out/margin bertingkat, minimum SL dan execution venue masih belum terverifikasi.

Validation2022–2023 dan test2024–Maret2026 memakai akun baruUSD10.000 masing-masing. Tabel berikut adalah test independen, bukan sambungan rekening2019 yang telah kehilangan modal. Semua return/DD memakai maximum floating equity DD tick-by-tick. NamaNY_COMPARATOR pada CSV berarti pembanding sesi19.00–00.00, bukan Frozen V1.

'''+table(phases)+ '\n'
 core=full[['candidate','ending_equity','net_profit','profit_factor','win_rate','expectancy_usd','trades','floating_equity_dd','return_over_dd']].copy();core.win_rate*=100;core.floating_equity_dd*=100;core=core.rename(columns={'win_rate':'win_rate_pct','floating_equity_dd':'floating_DD_pct'})
 report1=f'''# Deliverable1 — Yield & DXY Research Report

## Temuan yang sudah bisa dipastikan

Treasury CMT bukan harga transaksi satu obligasi. Treasury membentuk kurva par dari indicative bid-side quotations sekitar15.30NewYork. Website Treasury biasanya menyediakan hasil paling lambat18.00Eastern, tetapi dapat terlambat. H.15 Federal Reserve berjadwal16.15Eastern. Perbedaan ini membuat04.15WIB bukan jam publikasi Treasury yang tetap.

| Peristiwa | New York | WIB ketika EDT | WIB ketika EST |
| --- | --- | --- | --- |
| Anchor kuotasi Treasury |15.30|02.30 hari berikut|03.30 hari berikut|
| Jadwal H.15|16.15|03.15 hari berikut|04.15 hari berikut|
| Treasury biasanya tersedia paling lambat|18.00|05.00 hari berikut|06.00 hari berikut|

Waktu curve dihitung secara persis dan waktu pertama kali angka tersedia pada setiap tanggal historis tidak diberikan oleh tabel daily. Tidak dibuat timestamp publikasi palsu dari tanggalNEW_DATE, jadwal nominal, atau waktu download saat ini. Kalender observasi resmi digunakan; extraordinary closures dan publikasi tertunda tidak diasumsikan mengikuti jadwal biasa. Treasury mengganti metode quasi-cubic Hermite menjadi monotone-convex pada6Desember2021; ini menjadi structural break yang wajib dipisah pada model berikutnya. SOFR sekitar08.00ET memakai transaksi hari sebelumnya dan juga dapat direvisi pada hari publikasi; SOFR bukan feed yield Treasury intraday.

## Data aktual dan model yang belum dapat dinilai

Terkumpul{len(macro):,} tanggal observasi daily Treasury sampai{macro.date.max()}:nominal2Y/5Y/10Y, real5Y/10Y, spread10Y−2Y, dan pendekatan breakeven nominal−real. Seluruh XML dan checksum disertakan. Breakeven memuat komponen premi risiko/likuiditas dan tidak diperlakukan sebagai ekspektasi inflasi murni. File daily dipakai hanya untuk statistik retrospektif, tidak sebagai input yang seolah tersedia intraday.

| Target/hasil wajib | Status | Alasan |
| --- | --- | --- |
| A:Nowcast CMT yang belum terbit; MAE/RMSE bps|N/A—BLOCKED|Tidak ada pasangan kuotasi intraday yang terverifikasi dan historical publication first-seen|
| B:Yield1/3/6/12jam|N/A—BLOCKED|Daily CMT tidak menyediakan label yield pasar intraday|
| Real yield intraday|N/A—BLOCKED|Memerlukan quotes/harga TIPS dan metadata instrumen atau feed real-yield terverifikasi|
| DXY1/3/6/12jam|N/A—BLOCKED|Tidak ada histori ICE berlisensi; enam FX lengkap dan sinkron untuk proxy pun belum diperoleh|
| C:Respons XAU tambahan setelah yield|N/A—BLOCKED|Lead/lag dan incremental information belum bisa dipisah dari simultanitas|
| P(bull/bear/sideways), calibration/Brier/log loss|N/A—BLOCKED|Tidak ada fitting dan chronological calibration pada panel sah|
| Feature importance/ablation/rezim kegagalan|N/A—BLOCKED|Model terlatih belum ada; angka importance tidak dibuat|

Metode lanjutan:bandingkan last-available market quote dengan spread-adjusted ridge, autoregresi, histogram gradient boosting, ensemble dan regime-adaptive. TargetA harus dicocokkan ke tenor/kurva, bukan menyamakan on-the-run yield dengan CMT. Latih bias/spread koreksi hanya pada masa lampau. Untuk confidence interval, gunakan residual/conformal calibration pada segmen kronologis terpisah dan nilai coverage out-of-sample. Last quote pada waktu anchor mungkin mendekati angka resmi; kecilnya error angka resmi tidak otomatis memberi alpha XAU karena informasi pasar telah beredar.

Model API dalamsource memeriksa decision_at, feature_available_at, target_available_at dan verifikasi vintage/intraday. Regression ridge/nonlinear serta probabilitas dengan calibration kronologis tersedia sebagai scaffolding; model belum fitted, belum menghasilkan artefak prediksi, belum mengimplementasikan seluruh kandidat metode. Data revisi terkini FRED, nilaiCPI bulanan yang diisi mundur, atau yield resmi yang belum terbit tidak dimasukkan ke replay.

## Hubungan makro retrospektif yang benar-benar dihitung

Gold diambil dari close M5 yang sudah selesai pada anchor15.30NewYork, maksimum usia5menit. Perubahan yield dibandingkan dengan perubahan gold antartanggal anchor yang cocok. Ini korelasi daily deskriptif, bukan lead-lag intraday atau bukti kausal.

'''+table(corr[['factor','n','pearson_correlation','factor_up_count','gold_up_given_factor_up']])+'''
Pada sekitar43,1% observasiUS10Y naik, gold juga naik; untuk real10Y sekitar39,3%. Kenaikan yield tidak memaksa XAU turun. Safe-haven demand, premi inflasi, perubahan dollar, aliran fisik dan likuiditas adalah penjelasan calon yang perlu event-level validation; penelitian ini belum mengatribusikan penyebab setiap penyimpangan. Rezim suku bunga/inflasi/geopolitik belum dilabel menggunakan arsip informasi yang tersedia saat itu.

## Audit modul existing

Repository dipin pada7b6f5095d42fe20df37d262e440643ca867a19e7. xau_treasury_daily_official.py secara eksplisit menyebut daily, bukan intraday; NEW_DATE adalah observation-date marker. dxy_broker_context.py membedakan broker CFD dan rekonstruksi enam mata uang dari feed ICE resmi; kelengkapan enam komponen/sinkronisasi diperlukan. xau_macro_spot_news_v2.py memuat referensi minyak indikatifDIA dan RSS dengan pemeriksaan timestamp. Kode current-feed ini tidak membuktikan tersedianya arsip2019–2026. Dashboard, feed dan bridge produksi tidak diubah atau dinyatakan telah memiliki histori yang belum ditemukan.

Sumber resmi:[Treasury methodology](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics/treasury-yield-curve-methodology),[Treasury FAQ](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics/interest-rates-frequently-asked-questions),[H.15](https://www.federalreserve.gov/releases/h15/),[NY Fed SOFR](https://www.newyorkfed.org/markets/reference-rates/sofr),[ALFRED real-time periods](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html),[ICE USDX](https://www.ice.com/forex/usdx).
'''
 report2='''# Deliverable2 — Asian Session Backtest Report

## Setup dan pelaksanaan

75kombinasi terdiri dari5setup×5sesi×3targetR. Semua menggunakan closed M5 dan eksekusi pada urutan tick bid/ask setelah sinyal. Stop tidak diisi pada harga teoritis ketika market melompat. Floating equity dihitung tiap tick.10unit tests lulus, termasuk sisi bid/ask, stop gap, limit expiry, minimum lot, peak/TP, prefix invariance kelima setup, dan penolakan macro yang belum terbit. Ini verifikasi mesin, bukan bukti kesetaraan dengan cTrader native.

| Setup master | Implementasi R1 | Status |
| --- | --- | --- |
| A Macro Continuation |Memerlukan yield+DXY PIT|BLOCKED|
| B Liquidity Sweep Reversal |SWEEP_MSS_FVG, limit midpoint setelah MSS/displacement/FVG|Dieksekusi tanpa filter makro|
| C Asian Breakout|OPENING_BREAKOUT atas/bawah opening range30menit|Dieksekusi tanpa filter makro|
| D NY-to-Asia Continuation|NY_CONTINUATION dengan kekuatan return sesiNY dan trend/breakout M5|Dieksekusi sebagai versi harga|
| E Macro Divergence Reversal|Memerlukan panel divergensi makro PIT|BLOCKED|
| Kontrol harga|MOMENTUM dan TREND_FVG|Dieksekusi|

Definisi lengkap swing, sweep, BOS/MSS, displacement, FVG, SL/TP, limit expiry, invalidation, cooldown dan sizing ada di research_r1/PROTOCOL.md serta source. Parameter target dipilih dari training2019–2021; setup sweep kurang50trade training sehingga memakai default2R dan ditandai sampel kecil. Tidak ada klaim kelima strategi ini merupakan seluruh kemungkinan SMC/ICT.

## Lima setup full-Asia:uji historis2024–Maret2026

Urut profit factor untuk perbandingan; seluruh expectancy negatif. Tidak ada top5 yang direkomendasikan untuk LIVE.

'''+table(core)+'''
Metrik lengkap starting/ending equity, net profit, PF, win rate, expectancy, jumlah/bulanan trade, closed DD, floating DD, return/DD, worst month, losing streak dan OOS ada di period_metrics.csv, annual_all_candidates.csv dan cost_and_sizing_metrics.csv. Kandidat yang kehabisan kapasitas akun tetap dicatat sebagai gagal dan minimum-lot/margin rejections disimpan; periode sesudahnya tidak diartikan sebagai bukti profit.

## Hasil setiap tahun:annual resetUSD10.000

Tiap kolom adalah saldo akhir dari akun baruUSD10.000 pada awal tahun. Angka tidak disambung menjadi compounding.2026 hanya tiga bulan.

'''+table(ann)+'''
## Profil sesi dan liquidity

Statistik deskriptif memakai hari dengan≥90%bar tersedia; MACRO_READ memakai≥50% karena mencakup penutupan harian instrumen. Sampel replay lebih ketat:≥95%, pemeriksaan gap dan kedua sisi batas sesi. Perbedaan sampel dicatat di session_exclusions.csv dan data_quarantine.csv.

'''+table(pd.read_csv(OUT/'session_summary.csv'))+'''
Jam08WIB memiliki mean high–low terbesar di antara jam08–12 pada data ini. Itu ukuran range, bukan jam paling menguntungkan. entry_hour_profit.csv menyajikan keuntungan aktual menurut jam entry untuk setiap setup; tabel itu deskriptif dan tidak dipakai memilih ulang jam pada data test.

'''+table(pd.read_csv(OUT/'hourly_summary.csv').query('8<=hour_wib<13'))+'''
long_net_1oz/short_net_1oz adalah ilustrasi midpoint-return dikurangi mean spread/komisi/slippage, bukan replay terpisah yang menjamin fill pada open/close jam. Semua mean ilustrasi arah pasif pada jam tersebut negatif setelah frictionBASE.

'''+table(pd.read_csv(OUT/'liquidity_summary.csv'))+'''
Breakout statistik:close M5 pertama melewati opening range30menit+0,05range; continuation jika close berikutnya mencapai ekstensi0,5range sebelum close kembali ke dalam range; unresolved jika sesi berakhir lebih dulu. Evaluasi memakai close berurutan sehingga tidak menebak urutan high/low candle. Sweep adalah wick menembus level dan close kembali melewatinya; ini definisi harga, bukan bukti niat smart money.

Pemilahan hari/bulan/tahun tersedia. Label news besar/non-news, rezim inflasi/Fed, physical Shanghai flows, dan surprise konsensus belum diuji karena histori/vintage yang diperlukan belum diperoleh. Jadwal Shanghai saat ini tidak diterapkan mundur sebagai kalender historis yang pasti.
'''
 sens_summary='Belum tersedia.'
 if len(sens):
  so=sens[sens.period=='OOS'];sens_summary=f"Grid eksploratif9kombinasi jarak/holding×5setup menghasilkan{len(so)}baris test;{int((so.net_profit>0).sum())}berprofit positif. Grid ditambahkan setelah hasil awal terlihat; hasilnya bukan test konfirmatori baru."
 report3='''# Deliverable3 — Combined Strategy Research & Robustness

## Matriks model yang diminta

| Model | Hasil |
| --- | --- |
| 1 Asia tanpa makro|Dieksekusi pada5hipotesis harga/SMC,75kombinasi awal|
| 2 +US10Y|BLOCKED:histori PIT belum tersedia|
| 3 +US2Y/10Y|BLOCKED|
| 4 +yield+DXY|BLOCKED|
| 5 +nominal/real yield+DXY|BLOCKED|
| 6 Full Macro+SMC|BLOCKED|
| 7 Asia+Frozen V1 portfolio|BLOCKED:baseline tick parity dan histori lintas instrumen/PIT tidak lengkap|

Tidak ada angka correlation P/L, konflik posisi, margin gabungan, portfolio floating DD atau incremental profit yang diklaim untuk model2–7. Menjumlahkan profit standalone bukan simulasi equity portfolio. NY_COMPARATOR bukan substitusi Frozen. SourceV1 terverifikasi, tetapi bridge/checkpoint real-time tidak diarahkan ke backtest dan source tidak diubah untuk memudahkan simulasi.

## Biaya dan ukuran posisi:test2024–Maret2026

Setiap baris memiliki akun independen; bukan portofolio gabungan. ZERO_DIAGNOSTIC menggunakan spread/komisi/slippage nol dan bukan hasil trading yang bisa dieksekusi.

'''+table(fee[['scenario','candidate','starting_equity','ending_equity','profit_factor','trades','floating_equity_dd']])+'''
Tanpa friction beberapa hipotesis terlihat positif; pada biayaBASE hasilnya negatif. Pelebaran biaya mengubah bukan hanya P/L, tetapi juga apakah limit tersentuh, lot/minimum yang terjangkau, dan kesempatan entry berikutnya. Karena itu net profit sensitivitas tidak harus menurun monoton untuk setiap setup; jangan menafsirkan nonmonotonisitas sebagai biaya tinggi menambah alpha.

SkenarioUSD100 dengan risk0,5% current balance menghasilkan0trade untuk seluruh5setup:minimum1oz dan jarakSL/biaya tidak terjangkau. SaldoUSD100 yang tetap bukan keuntungan. Ini tidak menguji seedEUR atau perpindahan125 Frozen.

## Statistik, walk-forward dan stabilitas

'''+table(boot)+'''
Confidence interval adalah bootstrap blok5trading-day,3000replicates, termasuk hari kerja tanpa trade. Holm diterapkan pada5setup full-Asia, tetapi tidak sepenuhnya meniadakan pemilihan keluarga model/75percobaan. Positive-return probability adalah frekuensi bootstrap, bukan probabilitas keuntungan masa depan. P-value dihitung satu sisi terhadap mean nol dengan centered bootstrap; seluruh setup tidak lolos bukti expectancy positif.

Walk-forward memilih TP dari3tahun sebelum tahun test2022…2026 dan dilaporkan per setup/sesi pada walk_forward.csv. Parameter grid awal TP1,5/2/3R bukan optimasi semua elemen strategi. '''+sens_summary+'''

Sensitivitas jarakSL×1/1,6/2,3333 dari jarak awal, holding60/120/300menit, TP tetap hasil training. Hasil terpisah di parameter_sensitivity.csv. Arah perbaikan yang terlihat pada test lama memerlukan validasi baru, bukan promosi otomatis. Seluruh historical splits bersifat retrospective:periode test sudah tersedia ketika penelitian ini dirancang. Tidak ada klaim forward/prospective validation.

## Keputusan gabungan

Belum ada kandidat Asia full-Asia dengan parameter training yang memberi bukti net expectancy positif dan layak dipasangkan ke Frozen pada risiko setara. Model total-profit terbaik maupun risk-adjusted terbaik untuk model1–7 secara lengkap **belum dapat ditetapkan**. Lowest drawdown pada strategi yang masih rugi tidak membuktikan alpha. Batas DD deployment baru belum disetujui karena belum ada kandidat lolos.
'''
 report4=f'''# Deliverable4 — Reproducible Research Package

Status:paket partial dapat diaudit; penelitian keseluruhan belum complete.

- research_r1/:source akuisisi, audit, feature/signal, tick replay, metrics, bootstrap, walk-forward, sensitivitas, kurva, laporan, tests, dependency versions dan protocol.
- audit/:VPS inventory asli, SHA256 perfile, integrity audit, seluruh execution logs, runtime versions, kegagalan primary crosscheck dan manifest XML resmi.
- macro_raw/:daily Treasury XML yang benar-benar dipakai untuk deskripsi.
- derived/xau_m5.parquet:bar turunan dari arsip yang diuji; bukan data broker FP.
- results/:CSV setiap kandidat/tahun/periode/sesi/jam, log transaksi terkompresi, state/rejections, sensitivity, cost/sizing, dan curve CSV.
- figures/:equity dan floating drawdown OOS serta hourly range.
- baseline_identity/:identitas/checksum/aturan V1 yang relevan untuk audit; tidak memuat credential atau runtimeLIVE.
- reports/:kelima deliverable serta ringkasan utama.

Raw tick2,8GB tidak didistribusikan ulang. Audit mencatat URL arsip pihak ketiga dan checksum exact-bytes yang digunakan. Dataset card pihak ketiga menyatakan lisensi unknown; tidak diberikan klaim lisensi distribusi komersial. Pengguna dapat mereproduksi dengan salinan dataset yang telah dimilikinya. Source Dukascopy resmi menyediakan bid/ask export, tetapi parity tiap file arsip ini belum diverifikasi independen akibatHTTP429.

Ikuti research_r1/README.md. Semua hasil numerik berasal dari perintah yang benar-benar selesai; log tersimpan. Script remote_inventory.py hanya membaca folder tick dan manifest. Analisis berjalan offline di workspace terpisah. Tidak ada import mesinorder, APIbroker, websocketLIVE, restart service atau penulisan databaseLIVE. Branch riset:[research/xau-yield-asia-r1-20261115](https://github.com/rizanrizan93/Forex-scanner/tree/research/xau-yield-asia-r1-20261115). Main dipin saat audit pada7b6f5095d42fe20df37d262e440643ca867a19e7.

AttachmentSHA256:7f58f6839c21785cdcce2c629acd5a2b009593f47dabb6effd8a1b0225a22619. ZIPV1SHA256:0bd93f3f8ad3d64c3171a3fdd49d536b65fd9cfbf69d71e7740d685ac826488c. Seluruh29source file cocok manifest. Source release1.0.1 mengharuskan balance DAN equity≥125, akun flat, seed tercatat dan ACK fase tersimpan sebelum GROWTH; equity mengambang saja tidak cukup. Source file tidak membuktikan instanceLIVE yang sedang aktif atau parity hasil broker.

Untuk menyelesaikan penelitian dibutuhkan:(1)XAUbid/ask April–November2026 dan auditgap yang lebih kuat;(2)histori intraday nominal2Y/10Y/TIPS, actual availability dan licensed ICE DXY atau proxy enamFX lengkap;(3)arsip release/first-vintage/surprise ekonomi;(4)baseline adapter Frozen point-in-time dan data lintasXAU/EUR/BTC beserta kontrak/biaya/margin historis. Tidak perlu mengubahLIVE untuk menambah data tersebut.
'''
 report5='''# Deliverable5 — Final Recommendation

**Keputusan operasional sementara:A. Pertahankan Frozen V1 existing dan jangan memasang strategi Asia R1.** Riset ini belum membandingkan Frozen secara tick-native pada risk budget yang sama, sehingga rekomendasiA adalah keputusan mempertahankan sistem yang ada sambil menolak tambahan yang belum terbukti; bukan pengesahan historis profit/DD Frozen. Tidak ada dasar bukti untukB,C,D saat ini.

| Pertanyaan | Jawaban berdasarkan hasil R1 |
| --- | --- |
| 1 Yield resmi bisa diperkirakan dengan error kecil sebelum publikasi? |Secara metodologi dapat diestimasi dari quotes yang cocok, tetapi MAE kecil belum dibuktikan di R1.|
| 2 Nowcast memiliki informasi tambahan bagiXAU? |Belum diketahui; targetA berpotensi hanya mengemas ulang harga pasar yang sudah bereaksi. TargetB/C harus diuji terpisah.|
| 3 Seberapa akurat memprediksiDXY? |N/A; tidak ada run model pada histori terverifikasi.|
| 4 Yield+DXY konsisten memperbaiki prediksiXAU? |Belum diuji; korelasi harian bukan hasil ablation.|
| 5 ExpectancyAsia08–13positif setelah biaya? |Tidak pada5hipotesis awal dengan parameter training-selected dalam sample tersedia; hasil ini terbatas pada definisi/data/biaya R1.|
| 6 Jam paling menguntungkan? |Belum ada jamAsia yang lolos bukti profit robust.08WIB punya range rata-rata terbesar pada08–12, tidak otomatis expectancy tertinggi.|
| 7 Asia memperbaiki profit/DD portfolioFrozen? |Belum dapat dinilai; portfolio replay belum dilakukan.|
| 8 Paling robust untuk pasar masa depan? |Tidak ada kandidat baru yang dapat disahkan. Hasil historis yang sudah dilihat, sampel pendek/sparse dan kekurangan data menghalangi klaim robustness masa depan.|

Jika sensitivitas eksploratif menampilkan varian yang lebih baik, varian tersebut tetap research-only sampai parameter dibekukan dari training, bertahan pada biaya tinggi, memiliki sampel cukup dan lulus data/forward holdout baru. Tidak ada filealgo baru, deployment, atau perubahanLIVE dari R1 ini.

Sumber biaya:[FP Markets cTrader fees](https://www.fpmarkets.com/en-id/ctrader-fees-and-charges/). Kontrak emas contoh100oz/lot:[FP Markets metals](https://www.fpmarkets.com/metals/). Sumber tick original:[Dukascopy export](https://www.dukascopy.com/api/data/get/historical-data-export). Supply-chain archive:[dataset card](https://huggingface.co/datasets/Henrik404/dukascopy-ticks). Definisi/event/fee saat ini tidak dianggap identik untuk seluruh histori2019–2026.
'''
 parts=[('01_Yield_DXY_Report.md',report1),('02_Asian_Session_Report.md',report2),('03_Combined_Robustness_Report.md',report3),('04_Reproducibility_Package.md',report4),('05_Final_Recommendation.md',report5)]
 for name,body in parts:write(name,body)
 if len(extra):
  focus=sens[(sens.candidate=='TREND_FVG_ASIA_FULL_R3.0')&(sens.stop_scale>2.3)&(sens.holding_minutes==300)]
  additional='''\n## Satu kandidat eksploratif positif, tetapi gagal robustness\n\n+TREND_FVG dengan jarakSL≈3,5ATR (2,3333×jarak awal), TP3R dan holding maksimum300menit memperoleh net profitUSD177,44 (+1,77%), PF1,1522, floatingDD2,6305%,78trade pada2024–Maret2026. Varian ini ditemukan setelah hasil awal terlihat dan tidak dipromosikan sebagai pemenang OOS konfirmatori.\n\n+'''+table(focus[['period','net_profit','profit_factor','trades','floating_equity_dd']])+'''\n+Training2019–2021 rugiUSD834,07; validation2022–2023 rugiUSD474,07. Pada spread×1,5/slippage0,25 hasiltest berubah menjadi −USD84,25; pada spread×2/slippage0,50 menjadi −USD346,96. Confidence interval95% expectancy pertradeUSD'''+f"{eb.get('ci95_low',float('nan')):.2f} sampai {eb.get('ci95_high',float('nan')):.2f}, centered-bootstrap p={eb.get('one_sided_centered_bootstrap_p',float('nan')):.3f}."+''' Interval melintasi nol dan p belum memperhitungkan penuh pencarian tambahan. Tahun2025 juga rugi; profit tidak konsisten setiap tahun. Kesimpulan:belum robust, tidak layak deployment atau klaim diversifikasi.\n\n+'''+table(extra[['scenario','period','net_profit','profit_factor','trades','floating_equity_dd']])
  report3+=additional
  parts=[(name,report3 if name=='03_Combined_Robustness_Report.md' else body) for name,body in parts]
 if (ROOT/'audit/fred_reference_manifest.json').exists():
  frefs=json.loads((ROOT/'audit/fred_reference_manifest.json').read_text());ok=sum('error' not in x for x in frefs)
  reference_note=f'\nTambahan akuisisi:{ok}/{len(frefs)}seri FRED reference berhasil diarsipkan (CPI/core,PPI/core,NFP,unemployment,claims,JOLTS,FedFunds,SOFR,minyakspot,VIX,broadUSD,EURUSD/USDJPY daily). Semua berlabelLATEST_AT_RETRIEVAL_NOT_HISTORICAL_PIT dan historical_feature_eligible=false. Data ini tidak dipakai untuk trading atau klaim prediksi. DTWEXBGS adalah broadUSD Federal Reserve, bukan ICE DXY.\n'
  parts=[(name,body+reference_note if name=='01_Yield_DXY_Report.md' else body) for name,body in parts]
 for name,body in parts:write(name,body)
 complete=overview+'\n'.join(body+'\n\n' for _,body in parts)
 (ROOT/'LAPORAN_RIZAN_YIELD_ASIA_R1_20261115.md').write_text(complete,encoding='utf-8')
 phases.to_csv(OUT/'phase_status.csv',index=False)
 modelrows=[]
 for model in range(1,8):modelrows.append({'model':model,'status':'PARTIAL_PRICE_ONLY_EXECUTED' if model==1 else 'BLOCKED','macro_accuracy':None,'macro_mae_bp':None,'combined_profit':None})
 pd.DataFrame(modelrows).to_csv(OUT/'macro_experiment_status.csv',index=False)
 params={'selected_from':'2019-2021 only; fallback2R when training<50trades','configs':json.loads((OUT/'selected_configs.json').read_text()),'starting_equity':10000,'initial_fixed_risk_usd':50,'risk_fraction_compound':.005,'leverage':200,'margin_cap_fraction':.20,'minimum_oz':1,'costs':{'BASE':{'spread_multiplier':1,'market_slippage_usd_per_oz':.1,'commission_roundturn_per_lot':6}},'historical_test_end':'2026-03-31','macro_fitted':False,'production_changed':False}
 (OUT/'parameters.json').write_text(json.dumps(params,indent=2))
 print('Reports generated',len(complete),'characters')
if __name__=='__main__':main()
