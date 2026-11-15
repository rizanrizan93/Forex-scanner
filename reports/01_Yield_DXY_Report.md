# Deliverable1 — Yield & DXY Research Report

## Temuan yang sudah bisa dipastikan

Treasury CMT bukan harga transaksi satu obligasi. Treasury membentuk kurva par dari indicative bid-side quotations sekitar15.30NewYork. Website Treasury biasanya menyediakan hasil paling lambat18.00Eastern, tetapi dapat terlambat. H.15 Federal Reserve berjadwal16.15Eastern. Perbedaan ini membuat04.15WIB bukan jam publikasi Treasury yang tetap.

| Peristiwa | New York | WIB ketika EDT | WIB ketika EST |
| --- | --- | --- | --- |
| Anchor kuotasi Treasury |15.30|02.30 hari berikut|03.30 hari berikut|
| Jadwal H.15|16.15|03.15 hari berikut|04.15 hari berikut|
| Treasury biasanya tersedia paling lambat|18.00|05.00 hari berikut|06.00 hari berikut|

Waktu curve dihitung secara persis dan waktu pertama kali angka tersedia pada setiap tanggal historis tidak diberikan oleh tabel daily. Tidak dibuat timestamp publikasi palsu dari tanggalNEW_DATE, jadwal nominal, atau waktu download saat ini. Kalender observasi resmi digunakan; extraordinary closures dan publikasi tertunda tidak diasumsikan mengikuti jadwal biasa. Treasury mengganti metode quasi-cubic Hermite menjadi monotone-convex pada6Desember2021; ini menjadi structural break yang wajib dipisah pada model berikutnya. SOFR sekitar08.00ET memakai transaksi hari sebelumnya dan juga dapat direvisi pada hari publikasi; SOFR bukan feed yield Treasury intraday.

## Data aktual dan model yang belum dapat dinilai

Terkumpul1,968 tanggal observasi daily Treasury sampai2026-11-13:nominal2Y/5Y/10Y, real5Y/10Y, spread10Y−2Y, dan pendekatan breakeven nominal−real. Seluruh XML dan checksum disertakan. Breakeven memuat komponen premi risiko/likuiditas dan tidak diperlakukan sebagai ekspektasi inflasi murni. File daily dipakai hanya untuk statistik retrospektif, tidak sebagai input yang seolah tersedia intraday.

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

| factor | n | pearson_correlation | factor_up_count | gold_up_given_factor_up |
| --- | --- | --- | --- | --- |
| US2Y | 1771 | -0.3014 | 756 | 0.3981 |
| US10Y | 1771 | -0.2847 | 828 | 0.4312 |
| REAL10Y | 1771 | -0.3409 | 792 | 0.3927 |
| BE10Y | 1771 | 0.0523 | 812 | 0.5394 |

Pada sekitar43,1% observasiUS10Y naik, gold juga naik; untuk real10Y sekitar39,3%. Kenaikan yield tidak memaksa XAU turun. Safe-haven demand, premi inflasi, perubahan dollar, aliran fisik dan likuiditas adalah penjelasan calon yang perlu event-level validation; penelitian ini belum mengatribusikan penyebab setiap penyimpangan. Rezim suku bunga/inflasi/geopolitik belum dilabel menggunakan arsip informasi yang tersedia saat itu.

## Audit modul existing

Repository dipin pada7b6f5095d42fe20df37d262e440643ca867a19e7. xau_treasury_daily_official.py secara eksplisit menyebut daily, bukan intraday; NEW_DATE adalah observation-date marker. dxy_broker_context.py membedakan broker CFD dan rekonstruksi enam mata uang dari feed ICE resmi; kelengkapan enam komponen/sinkronisasi diperlukan. xau_macro_spot_news_v2.py memuat referensi minyak indikatifDIA dan RSS dengan pemeriksaan timestamp. Kode current-feed ini tidak membuktikan tersedianya arsip2019–2026. Dashboard, feed dan bridge produksi tidak diubah atau dinyatakan telah memiliki histori yang belum ditemukan.

Sumber resmi:[Treasury methodology](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics/treasury-yield-curve-methodology),[Treasury FAQ](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics/interest-rates-frequently-asked-questions),[H.15](https://www.federalreserve.gov/releases/h15/),[NY Fed SOFR](https://www.newyorkfed.org/markets/reference-rates/sofr),[ALFRED real-time periods](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html),[ICE USDX](https://www.ice.com/forex/usdx).

Tambahan akuisisi:16/16seri FRED reference berhasil diarsipkan (CPI/core,PPI/core,NFP,unemployment,claims,JOLTS,FedFunds,SOFR,minyakspot,VIX,broadUSD,EURUSD/USDJPY daily). Semua berlabelLATEST_AT_RETRIEVAL_NOT_HISTORICAL_PIT dan historical_feature_eligible=false. Data ini tidak dipakai untuk trading atau klaim prediksi. DTWEXBGS adalah broadUSD Federal Reserve, bukan ICE DXY.
