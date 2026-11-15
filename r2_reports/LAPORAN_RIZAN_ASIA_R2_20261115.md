# RIZAN XAU Asian Session R2 — Expanded Entry Research

Tanggal: 15 November 2026 WIB. Jam sasaran: 08.00–13.00 WIB. **Riset tetap terpisah dari LIVE dan Frozen V1.**

## Keputusan

Pencarian diperluas menjadi **504 skenario**: 312 kombinasi indikator/struktur harga, 180 ablation yield/news/volatilitas, dan 12 varian model expected return. Sebagian merupakan kontrol yang diulang untuk membandingkan penambahan fitur. **Belum ada kandidat yang lolos seluruh syarat discovery dan validation.** Dua pola setelah berita masih positif pada test, tetapi jumlah transaksinya sangat kecil. Tidak dibuat algo baru atau perubahan LIVE.

Kesimpulan ini berlaku untuk aturan, data dan biaya yang diuji. Belum mencakup seluruh kemungkinan strategi Asia, feed makro intraday, news surprise, atau geopolitik. Hasil tick Dukascopy dengan model biaya bukan bukti kesetaraan fill historis FP Markets.

| Bagian | Status | Bukti atau batas |
| --- | --- | --- |
| Audit XAU/EUR | PARTIAL | 174 exact-byte files; source end March 2026; independent primary parity and FP history incomplete |
| Indicator/SMC screen | COMPLETE_FOR_DEFINED_GRID | 312 combinations / 13 families |
| Macro/news/volatility ablation | COMPLETE_FOR_DEFINED_GRID | 180 experiments, including repeated controls |
| Expected-return models | COMPLETE_FOR_DEFINED_GRID | 12 thresholds/model variants, causal model cutoffs |
| Selected robustness | COMPLETE_FOR_WATCHLIST | Cost stress, annual reset, continuous, compounding, tick-marked curves |
| Geopolitical text / news surprise | BLOCKED | No verified full historical first-seen text and contemporaneous consensus panel |
| Intraday Treasury nowcast / official DXY | BLOCKED | Weekly vintage daily yields and EUR proxy do not supply these histories |
| New LIVE strategy | NOT_APPROVED_BY_EVIDENCE | No candidate passes discovery/validation gates; no deployment |

## Data dan biaya

Digunakan 474.178.064 tick XAUUSD dan 192,875,443 tick EURUSD, total **667.053.507 tick**, Januari 2019–Maret 2026. Seluruh 174 file bulanan cocok SHA256 manifest VPS. XAU reuse audit R1; EUR lolos pemeriksaan harga positif, bid≤ask dan timestamp tidak terbalik. Kuotasi duplikat dipertahankan; dataset card pihak ketiga dan rate-limit primary crosscheck R1 tetap menjadi batas provenance. Tidak ada klaim data April–November 2026.

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
| News | 345 tanggal rilis asli CPI/PPI/NFP/JOLTS dan 61 pernyataan Fed/FOMC; hanya rilis yang sudah tersedia |
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

Syarat kandidat: setidaknya60trade discovery (40untuk model forward dua tahun),30trade validation, expectancy dan PF positif/di atas1 pada keduanya, DD validation≤30%. Jumlah yang lolos: **0**. Syarat ini tidak dilonggarkan untuk mengubah sampel kecil menjadi pemenang.

Lima kasus berikut adalah **watchlist diagnostik**, dipilih dari discovery/validation; hasil test tidak dipakai untuk memilihnya. Empat keluarga awal profit pada dua periode tetapi kekurangan sampel. Sweep NY menjadi pembanding bersampel lebih besar dan gagal pada discovery.

| Setup | Train_USD | Train_trades | Validation_USD | Validation_trades | Test_USD | Test_PF | Test_trades | Floating_DD_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Bollinger + EUR + setelah news | 30.125 | 16.000 | 138.099 | 7.000 | -205.467 | 0.330 | 13.000 | 2.195 |
| Donchian + yield + news | 48.271 | 16.000 | 127.911 | 11.000 | -262.738 | 0.199 | 11.000 | 3.205 |
| Sweep NY + EUR | -729.322 | 94.000 | 171.738 | 67.000 | -320.420 | 0.770 | 87.000 | 3.862 |
| Opening fade + EUR + yield + news | 23.771 | 15.000 | 82.779 | 8.000 | 23.201 | 1.114 | 18.000 | 1.413 |
| RSI fade + EUR + yield + news | 9.399 | 5.000 | 40.984 | 8.000 | 33.570 | 3.383 | 5.000 | 0.418 |

### Aturan dua pola yang masih positif pada test

**Opening fade + EUR + yield + news:** setelah opening range08.00–08.30, arah awal harus melampaui0,3ATR H1. Cari pembalikan melalui high/low tiga bar M5 sebelumnya. EURUSD satu jam harus searah tekanan yang mendukung buy/sell emas, perubahan yield vintage harus mendukung arah hipotesis, dan sudah ada rilis utama dalam24jam. Entry sebelum10.30, SL1,25ATR H1, TP2R, tutup13.00. Test hanya18trade; net profitUSD23,20 dan floatingDD sekitar1,41%.

**RSI fade + EUR + yield + news:** RSI14 M15<35 diikuti closeM5 di atas high bar sebelumnya untuk buy; kondisi simetris RSI>65 untuk sell. Entry10.30–12.30, SL1,25ATR H1, TP1R, flat13.00, dengan gate EUR/yield/news yang sama. Test hanya5trade; net profitUSD33,57. PF tinggi dari lima transaksi tidak cukup untuk menyimpulkan alpha.

Kedua pola masuk daftar penelitian. Keduanya belum layak LIVE. Efek dolar, yield dan berita harus dibaca bersama perubahan jumlah kesempatan entry; pengurangan kerugian karena lebih sedikit transaksi tidak otomatis membuktikan tambahan kemampuan prediksi.

## Ketahanan biaya dan sizing

| Setup | scenario | net_profit | profit_factor | trades | DD_pct |
| --- | --- | --- | --- | --- | --- |
| Bollinger + EUR + setelah news | REVIEW_STRESS15 | -231.494 | 0.272 | 13 | 2.387 |
| Opening fade + EUR + yield + news | REVIEW_STRESS15 | -3.015 | 0.985 | 18 | 1.420 |
| Donchian + yield + news | REVIEW_STRESS15 | -259.312 | 0.163 | 11 | 3.120 |
| RSI fade + EUR + yield + news | REVIEW_STRESS15 | 22.603 | 2.109 | 5 | 0.463 |
| Sweep NY + EUR | REVIEW_STRESS15 | -424.255 | 0.699 | 87 | 4.605 |
| Bollinger + EUR + setelah news | REVIEW_STRESS20 | -253.128 | 0.219 | 13 | 2.533 |
| Opening fade + EUR + yield + news | REVIEW_STRESS20 | -56.162 | 0.759 | 18 | 1.621 |
| Donchian + yield + news | REVIEW_STRESS20 | -414.453 | 0.053 | 12 | 4.544 |
| RSI fade + EUR + yield + news | REVIEW_STRESS20 | 4.861 | 1.165 | 5 | 0.504 |
| Sweep NY + EUR | REVIEW_STRESS20 | -662.890 | 0.558 | 88 | 6.964 |

Opening fade yang positif kecil pada biaya dasar menjadi negatif saat biaya dinaikkan. RSI masih positif sangat kecil pada stress tetapi hanya beberapa transaksi. BASE memakai spread Dukascopy, bukan arsip spread FP Markets. Tidak ditarik kesimpulan universal tentang semua kondisi broker.

Skenario compounding dipisahkan dari fixed risk. Menambah leverage/risk bukan ukuran tambahan alpha. Continuous dimulai sekali pada2019; annual reset dimulaiUSD10.000 setiap Januari. Jangan menjumlahkan saldo dari reset akun independen menjadi satu equity portfolio.

| Setup | scenario | starting_equity | ending_equity | net_profit | profit_factor | trades | DD_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Bollinger + EUR + setelah news | REVIEW_CONTINUOUS | 10,000.000 | 9,962.757 | -37.243 | 0.926 | 36 | 2.545 |
| Opening fade + EUR + yield + news | REVIEW_CONTINUOUS | 10,000.000 | 10,129.751 | 129.751 | 1.285 | 41 | 1.401 |
| Donchian + yield + news | REVIEW_CONTINUOUS | 10,000.000 | 9,913.444 | -86.556 | 0.904 | 38 | 3.649 |
| RSI fade + EUR + yield + news | REVIEW_CONTINUOUS | 10,000.000 | 10,083.953 | 83.953 | 2.084 | 18 | 0.730 |
| Sweep NY + EUR | REVIEW_CONTINUOUS | 10,000.000 | 9,121.996 | -878.004 | 0.766 | 248 | 9.639 |
| Bollinger + EUR + setelah news | REVIEW_COMPOUND | 10,000.000 | 9,962.100 | -37.900 | 0.925 | 36 | 2.545 |
| Opening fade + EUR + yield + news | REVIEW_COMPOUND | 10,000.000 | 10,136.911 | 136.911 | 1.302 | 41 | 1.397 |
| Donchian + yield + news | REVIEW_COMPOUND | 10,000.000 | 9,895.408 | -104.592 | 0.886 | 38 | 3.690 |
| RSI fade + EUR + yield + news | REVIEW_COMPOUND | 10,000.000 | 10,083.953 | 83.953 | 2.084 | 18 | 0.730 |
| Sweep NY + EUR | REVIEW_COMPOUND | 10,000.000 | 9,188.640 | -811.360 | 0.769 | 248 | 9.147 |

## Hasil tahunan — saldo akhir annual reset USD10.000

| period | Bollinger + EUR + setelah news | Donchian + yield + news | Opening fade + EUR + yield + news | RSI fade + EUR + yield + news | Sweep NY + EUR |
| --- | --- | --- | --- | --- | --- |
| 2019 | 9,989.212 | 10,165.682 | 9,900.121 | 9,996.991 | 9,883.732 |
| 2020 | 10,072.689 | 9,947.807 | 9,999.723 | 10,022.596 | 9,645.365 |
| 2021 | 9,968.224 | 9,934.781 | 10,123.927 | 9,989.812 | 9,741.582 |
| 2022 | 10,069.799 | 10,028.635 | 10,024.852 | 10,003.084 | 10,246.251 |
| 2023 | 10,068.300 | 10,099.276 | 10,057.927 | 10,037.900 | 9,925.487 |
| 2024 | 9,947.796 | 9,792.113 | 9,962.080 | 9,998.980 | 9,949.011 |
| 2025 | 9,932.791 | 9,945.149 | 10,010.295 | 10,008.290 | 9,762.704 |
| 2026 YTD_MARCH | 9,913.946 | 10,000.000 | 10,050.826 | 10,026.300 | 9,967.865 |

2026 hanya YTD sampai31Maret. Tahun tanpa transaksi adalah tidak ada exposure, bukan bukti strategi profit. Log lengkap juga memuat losing streak, worst month, trades/month, closed-balance DD dan floating-equity DD.

## Bukti statistik

| Setup | trades | status | ci95_low_usd | ci95_high_usd | raw_p | bonferroni504_p |
| --- | --- | --- | --- | --- | --- | --- |
| Bollinger + EUR + setelah news | 13 | INSUFFICIENT_TRADES_FOR_INFERENCE | N/A | N/A | N/A | N/A |
| Donchian + yield + news | 11 | INSUFFICIENT_TRADES_FOR_INFERENCE | N/A | N/A | N/A | N/A |
| Sweep NY + EUR | 87 | BOOTSTRAP_DESCRIPTIVE_RETROSPECTIVE_TEST | -12.837 | 5.366 | 0.791 | 1.000 |
| Opening fade + EUR + yield + news | 18 | INSUFFICIENT_TRADES_FOR_INFERENCE | N/A | N/A | N/A | N/A |
| RSI fade + EUR + yield + news | 5 | INSUFFICIENT_TRADES_FOR_INFERENCE | N/A | N/A | N/A | N/A |

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
