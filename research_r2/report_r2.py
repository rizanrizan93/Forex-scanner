import pathlib,json,numpy as np,pandas as pd
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'r2_results';REPORT=ROOT/'r2_reports';REPORT.mkdir(exist_ok=True)
def tab(d):
 def fmt(x):
  if pd.isna(x):return 'N/A'
  if isinstance(x,(float,np.floating)):return f'{x:,.3f}'
  return str(x).replace('|','/')
 return '| '+' | '.join(d.columns)+' |\n| '+' | '.join(['---']*len(d.columns))+' |\n'+'\n'.join('| '+' | '.join(fmt(x) for x in row)+' |' for row in d.itertuples(index=False,name=None))+'\n'
def label(k):
 if k.startswith('BB_RANGE'):return 'Bollinger + EUR + setelah news'
 if k.startswith('OPEN_FADE'):return 'Opening fade + EUR + yield + news'
 if k.startswith('DONCHIAN'):return 'Donchian + yield + news'
 if k.startswith('RSI_FADE'):return 'RSI fade + EUR + yield + news'
 return 'Sweep NY + EUR'
def main():
 allm=pd.read_csv(OUT/'all_period_metrics.csv');gates=pd.read_csv(OUT/'final_train_validation_gates.csv');review=pd.read_csv(OUT/'review_period_metrics.csv');rob=pd.read_csv(OUT/'review_robustness_metrics.csv');bs=pd.read_csv(OUT/'review_block_bootstrap.csv');cfg=json.loads((OUT/'review_configs.json').read_text())
 eligibility=int(gates.eligible.sum());vint=json.loads((ROOT/'r2_audit/alfred_manifest.json').read_text());eur=json.loads((ROOT/'r2_audit/eur_integrity.json').read_text());news=pd.read_csv(ROOT/'r2_audit/bls_release_calendar.csv');fed=pd.read_csv(ROOT/'r2_audit/fomc_releases.csv')
 p=review.pivot(index='candidate',columns='period',values=['net_profit','trades','profit_factor','floating_equity_dd'])
 summary=pd.DataFrame({'Setup':[label(k) for k in p.index],'Train_USD':p[('net_profit','TRAIN')].to_numpy(),'Train_trades':p[('trades','TRAIN')].to_numpy(),'Validation_USD':p[('net_profit','VALIDATION')].to_numpy(),'Validation_trades':p[('trades','VALIDATION')].to_numpy(),'Test_USD':p[('net_profit','TEST')].to_numpy(),'Test_PF':p[('profit_factor','TEST')].to_numpy(),'Test_trades':p[('trades','TEST')].to_numpy(),'Floating_DD_pct':p[('floating_equity_dd','TEST')].to_numpy()*100})
 status=pd.DataFrame([
 ['Audit XAU/EUR','PARTIAL','174 exact-byte files; source end March 2026; independent primary parity and FP history incomplete'],
 ['Indicator/SMC screen','COMPLETE_FOR_DEFINED_GRID','312 combinations / 13 families'],
 ['Macro/news/volatility ablation','COMPLETE_FOR_DEFINED_GRID','180 experiments, including repeated controls'],
 ['Expected-return models','COMPLETE_FOR_DEFINED_GRID','12 thresholds/model variants, causal model cutoffs'],
 ['Selected robustness','COMPLETE_FOR_WATCHLIST','Cost stress, annual reset, continuous, compounding, tick-marked curves'],
 ['Geopolitical text / news surprise','BLOCKED','No verified full historical first-seen text and contemporaneous consensus panel'],
 ['Intraday Treasury nowcast / official DXY','BLOCKED','Weekly vintage daily yields and EUR proxy do not supply these histories'],
 ['New LIVE strategy','NOT_APPROVED_BY_EVIDENCE','No candidate passes discovery/validation gates; no deployment']
 ],columns=['Bagian','Status','Bukti atau batas'])
 text='''# RIZAN XAU Asian Session R2 — Expanded Entry Research

Tanggal: 15 November 2026 WIB. Jam sasaran: 08.00–13.00 WIB. **Riset tetap terpisah dari LIVE dan Frozen V1.**

## Keputusan

Pencarian diperluas menjadi **504 skenario**: 312 kombinasi indikator/struktur harga, 180 ablation yield/news/volatilitas, dan 12 varian model expected return. Sebagian merupakan kontrol yang diulang untuk membandingkan penambahan fitur. **Belum ada kandidat yang lolos seluruh syarat discovery dan validation.** Dua pola setelah berita masih positif pada test, tetapi jumlah transaksinya sangat kecil. Tidak dibuat algo baru atau perubahan LIVE.

Kesimpulan ini berlaku untuk aturan, data dan biaya yang diuji. Belum mencakup seluruh kemungkinan strategi Asia, feed makro intraday, news surprise, atau geopolitik. Hasil tick Dukascopy dengan model biaya bukan bukti kesetaraan fill historis FP Markets.

'''+tab(status)+'''
## Data dan biaya

Digunakan 474.178.064 tick XAUUSD dan '''+f"{sum(x['rows'] for x in eur):,}"+''' tick EURUSD, total **667.053.507 tick**, Januari 2019–Maret 2026. Seluruh 174 file bulanan cocok SHA256 manifest VPS. XAU reuse audit R1; EUR lolos pemeriksaan harga positif, bid≤ask dan timestamp tidak terbalik. Kuotasi duplikat dipertahankan; dataset card pihak ketiga dan rate-limit primary crosscheck R1 tetap menjadi batas provenance. Tidak ada klaim data April–November 2026.

Baseline akun terpisah USD10.000, risk budget tetap USD50/trade, leverage1:200, maksimum margin20% equity, minimum/step1oz, 100oz/lot. Satu posisi dan maksimal3entry/hari. Biaya: bid/ask asli arsip, slippageUSD0,10/oz pada market execution, komisiUSD6/lot roundturn. Stress1: spread×1,5/slippage0,25/komisi6. Stress2: spread×2/slippage0,50/komisi8. Komisi mengacu pada FP Markets cTrader Raw saat penelitian; spesifikasi/biaya/fill historis broker belum diverifikasi.

Entry dibolehkan pada window 08.00–10.30, 10.30–12.30 atau 08.00–12.30; posisi dapat bertahan sampai13.00. Semua memakai bar selesai, quote berikutnya, bid/ask sesuai sisi, stop pada quote aktual ketika gap, dan exit maksimal300menit atau13.00. Quarantine data menggunakan kelengkapan≥95%, tanpa gap>5menit dan quote pada kedua sisi batas sesi. Ini definisi sampel audit retrospektif, bukan filter live yang mengetahui masa depan.

## Apa yang diuji

| Kelompok | Cakupan |
| --- | --- |
| Indikator | RSI14, Bollinger20×2σ, EMA20/50/200, ATR14, ADX14, Donchian20; timeframe M15/H1 |
| Struktur/SMC | Sweep high/low NY sebelumnya, pembalikan opening range, breakout opening range, pra-Asia continuation/reversal, FVG continuation |
| Kontrol | Buy/sell jam tetap, risk budget sama |
| Dollar pressure | Return EURUSD satu jam, quote fresh; ini proxy satu mata uang, bukan ICE DXY |
| Yield/real yield | 379 vintage ALFRED terverifikasi untuk US2Y, US10Y dan TIPS10Y |
| News | '''+str(len(news))+''' tanggal rilis asli CPI/PPI/NFP/JOLTS dan '''+str(len(fed))+''' pernyataan Fed/FOMC; hanya rilis yang sudah tersedia |
| Rezim volatilitas | ATR H1 dibanding persentil95 dari200bar H1 sebelumnya, serta range pra-Asia |
| Model expected return | Ridge dan shallow gradient boosting, PRICE dibanding PRICE+PIT_MACRO_NEWS |
| Geopolitik | Belum di-backtest; tidak memakai headline saat ini atau tanggal krisis yang dipilih setelah kejadian |

### Makro/news benar-benar tersedia sebelum entry

ALFRED diminta dengan vintage yang sama **untuk setiap seri**, lalu setiap suffix kolom diperiksa. Satu parameter vintage scalar pada URL multi-seri ternyata hanya mengatur seri pertama; respons semacam itu ditolak. Sentinel GDP vintage4Januari2019 memastikan kuartal2018Q4 yang belum dirilis tidak muncul. Semua379snapshot lolos pemeriksaan header dan tidak memuat observasi masa depan.

Snapshot mingguan memakai vintage Sabtu dan batas ketersediaan konservatif Minggu12.00UTC; baru dipakai sesudah batas itu. Ini **filter yield harian tertunda yang di-update mingguan**, sehingga tidak menguji informasi yield terbaru semalam secara sempurna dan tidak menghasilkan nowcast intraday. Aturan arah menguji hipotesis inverse-yield dari jumlah tanda perubahan nominal2Y/10Y/real10Y; bukan asumsi bahwa korelasi selalu berlaku. Usia observasi>10hari memblokir gate.

News AFTER/QUIET berarti ada/tidak ada rilis **yang sudah diketahui** dalam24jam sebelumnya. Rilis BLS menggunakan tanggal archive asli dan jam publikasi reguler dengan buffer1jam; pernyataan Fed memakai waktu resmi yang tercantum dan buffer1jam. Filter ini tidak menggunakan hasil news yang belum terjadi untuk memutuskan entry pagi. Tidak ada actual-minus-consensus surprise tanpa arsip consensus/first-release yang sah.

### Model dilatih tanpa target masa depan

Label long/short berasal dari replay tick berbiaya pada kesempatan entry08.05, SL1,25ATR H1, TP2R, flat13.00. Model2019 memprediksi2020; model2019–2020 memprediksi2021; model2019–2021 dibekukan untuk2022–Maret2026. Semua exit training mendahului cutoff fit. Scaling hanya dilatih pada training. Output adalah perkiraan netR, **bukan probabilitas kemenangan terkalibrasi**. Threshold entry0,05/0,10/0,20R tidak dioptimasi pada test.

## Hasil discovery, validation dan test

Discovery2019–2021; validation2022–2023; test2024–Maret2026. Akun tiap periode dimulaiUSD10.000 secara independen. Untuk model, discovery memakai prediksi forward2020–2021 setelah warmup2019. Data test ini sudah tersedia ketika R2 dirancang, sehingga berstatus **retrospective historical test**, bukan bukti forward yang belum pernah dilihat.

Syarat kandidat: setidaknya60trade discovery (40untuk model forward dua tahun),30trade validation, expectancy dan PF positif/di atas1 pada keduanya, DD validation≤30%. Jumlah yang lolos: **'''+str(eligibility)+'''**. Syarat ini tidak dilonggarkan untuk mengubah sampel kecil menjadi pemenang.

Lima kasus berikut adalah **watchlist diagnostik**, dipilih dari discovery/validation; hasil test tidak dipakai untuk memilihnya. Empat keluarga awal profit pada dua periode tetapi kekurangan sampel. Sweep NY menjadi pembanding bersampel lebih besar dan gagal pada discovery.

'''+tab(summary)+'''
### Aturan dua pola yang masih positif pada test

**Opening fade + EUR + yield + news:** setelah opening range08.00–08.30, arah awal harus melampaui0,3ATR H1. Cari pembalikan melalui high/low tiga bar M5 sebelumnya. EURUSD satu jam harus searah tekanan yang mendukung buy/sell emas, perubahan yield vintage harus mendukung arah hipotesis, dan sudah ada rilis utama dalam24jam. Entry sebelum10.30, SL1,25ATR H1, TP2R, tutup13.00. Test hanya18trade; net profitUSD23,20 dan floatingDD sekitar1,41%.

**RSI fade + EUR + yield + news:** RSI14 M15<35 diikuti closeM5 di atas high bar sebelumnya untuk buy; kondisi simetris RSI>65 untuk sell. Entry10.30–12.30, SL1,25ATR H1, TP1R, flat13.00, dengan gate EUR/yield/news yang sama. Test hanya5trade; net profitUSD33,57. PF tinggi dari lima transaksi tidak cukup untuk menyimpulkan alpha.

Kedua pola masuk daftar penelitian. Keduanya belum layak LIVE. Efek dolar, yield dan berita harus dibaca bersama perubahan jumlah kesempatan entry; pengurangan kerugian karena lebih sedikit transaksi tidak otomatis membuktikan tambahan kemampuan prediksi.

## Ketahanan biaya dan sizing

'''
 costs=rob[(rob.period=='TEST')&rob.scenario.isin(['REVIEW_STRESS15','REVIEW_STRESS20'])].copy();costs['Setup']=costs.candidate.map(label);costs['DD_pct']=costs.floating_equity_dd*100
 text+=tab(costs[['Setup','scenario','net_profit','profit_factor','trades','DD_pct']])+'''
Opening fade yang positif kecil pada biaya dasar menjadi negatif saat biaya dinaikkan. RSI masih positif sangat kecil pada stress tetapi hanya beberapa transaksi. BASE memakai spread Dukascopy, bukan arsip spread FP Markets. Tidak ditarik kesimpulan universal tentang semua kondisi broker.

Skenario compounding dipisahkan dari fixed risk. Menambah leverage/risk bukan ukuran tambahan alpha. Continuous dimulai sekali pada2019; annual reset dimulaiUSD10.000 setiap Januari. Jangan menjumlahkan saldo dari reset akun independen menjadi satu equity portfolio.

'''
 continuous=rob[rob.scenario.isin(['REVIEW_CONTINUOUS','REVIEW_COMPOUND'])].copy();continuous['Setup']=continuous.candidate.map(label);continuous['DD_pct']=continuous.floating_equity_dd*100;text+=tab(continuous[['Setup','scenario','starting_equity','ending_equity','net_profit','profit_factor','trades','DD_pct']])
 annual=rob[rob.scenario=='REVIEW_ANNUAL'].copy();annual['Setup']=annual.candidate.map(label);a=annual.pivot(index='period',columns='Setup',values='ending_equity').reset_index();text+='\n## Hasil tahunan — saldo akhir annual reset USD10.000\n\n'+tab(a)+'''
2026 hanya YTD sampai31Maret. Tahun tanpa transaksi adalah tidak ada exposure, bukan bukti strategi profit. Log lengkap juga memuat losing streak, worst month, trades/month, closed-balance DD dan floating-equity DD.

## Bukti statistik

'''
 b=bs.copy();b['Setup']=b.candidate.map(label);text+=tab(b[['Setup','trades','status','ci95_low_usd','ci95_high_usd','raw_p','bonferroni504_p']])+'''
Inferensi bootstrap ditolak untuk test<30trade. Kasus dengan sampel cukup memakai20hari trading per blok,20.000replicates, serta koreksi Bonferroni504 sebagai batas konservatif untuk banyak percobaan. Semua hasil bersifat retrospektif. Tidak ada kandidat dengan bukti statistik dan stabilitas biaya yang cukup untuk deployment.

Walk-forward dalam package hanya menguji pemilihan tahunan di antara watchlist eksploratif yang dipilih memakai data sampai2023. Oleh sebab itu, segmen2022–2023 dari analisis watchlist tersebut bersifat deskriptif dan bukan pure out-of-sample family selection. Ini tidak dilabel sebagai bukti forward yang bersih.

## Yang masih belum teruji

- Geopolitik/news-text memerlukan arsip yang mencatat kapan berita pertama diketahui, deduplikasi, cakupan publisher dan latency. GDELT membedakan event-day dari DATEADDED; tanggal peristiwa saja tidak cukup. Tidak dibuat skor geopolitik buatan.
- Actual-versus-consensus CPI/PPI/NFP memerlukan original first-release dan contemporaneous forecast. Kalender rilis bukan pengganti surprise.
- Treasury intraday terbaru semalam, TIPS intraday, dan histori ICE DXY berlisensi belum tersedia. Hasil weekly vintage dan proxy EUR tidak dianggap identik.
- Periode tick April–November2026, parity brokerFP dan portfolio Frozen V1 belum diuji. File/parameter Frozen dan bridge LIVE tetap tidak diubah.

## Rekomendasi

Pertahankan konfigurasi existing. **Belum menambahkan strategi Asia R2 ke LIVE.** Opening fade setelah news dan RSI fade berfilter masuk watchlist penelitian karena masih menunjukkan beberapa hasil positif; jumlah sampel dan robustness-nya belum mencukupi. Tidak ada janji bahwa menambah indikator atau makro pasti menghasilkan strategi profitable.

## Isi package dan reproduksi

Source R2, dependency R1 yang digunakan, parameter semua skenario,379manifest vintage dan panel PIT terverifikasi, kalender BLS/Fed, model fit audit/prediksi,CSV periode/tahunan/ablation, log transaksi, curveCSV/PNG, serta log gagal/retry disertakan. Raw tick tidak didistribusikan ulang; URL/checksum tersedia. Semua379respons ALFRED penuh disimpan dalam archive terkompresi dan dapat dipulihkan dengan checksum aslinya. Jalankan README satu worker pada satu waktu. Dua proses riset yang terkena batas memori telah dijalankan ulang berurutan hingga exit0; hasil gagal tidak diklaim sebagai backtest selesai.

Sumber utama: [ALFRED real-time periods](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html), [BLS archive schedules](https://www.bls.gov/bls/archived_sched.htm), [BLS CPI archives](https://www.bls.gov/bls/news-release/cpi.htm), [BLS employment archives](https://www.bls.gov/bls/news-release/empsit.htm), [Fed FOMC calendars](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm), [GDELT codebook](https://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf), [FP Markets cTrader fees](https://www.fpmarkets.com/en-id/ctrader-fees-and-charges/).
'''
 (REPORT/'LAPORAN_RIZAN_ASIA_R2_20261115.md').write_text(text,encoding='utf-8');status.to_csv(OUT/'status.csv',index=False)
 print('Report characters',len(text),'eligible',eligibility)
if __name__=='__main__':main()
