# BTC indikator tujuh hari + pengaman weekend + leverage replay 200x

Keputusan pengguna: indikator BTC tetap memakai seluruh tujuh hari, posisi BTC harus ditutup sebelum penutupan mingguan, dan leverage model portofolio 1:200. ID riset RZ-BTC-7D-WEEKEND-L200. Ini varian riset dari LF122, tidak mengganti V1.2.1 beku atau trading live.

## FP Markets dan cTrader

Halaman resmi FP Markets yang diperiksa pada 20 Oktober 2026 menyebut crypto 24/5 dan mencantumkan cTrader sebagai platform. Halaman jam trading umum mencantumkan crypto daily 00:00–23:59 dan Jumat 00:00–23:55 pada GMT+2/GMT+3 (DST). Ini informasi situs umum, bukan verifikasi spesifikasi BTCUSD akun pengguna atau histori sesi/DST. Native harus mengikuti Symbol.MarketHours, bukan jam asumsi replay yang di-hardcode.

Source native LF122 yang dibaca menggunakan MarketData.GetBars(TimeFrame.Hour/Hour4,"BTCUSD"). API ini mengambil chart bars simbol, bukan feed exchange BTC 24/7. Bila feed broker tidak berisi candle weekend, metode ini tidak menyediakan pergerakan weekend untuk indikator. Kelengkapan bar weekend pada akun pengguna belum diinspeksi. Untuk mereproduksi indikator Bitstamp riset, native memerlukan adapter feed Bitstamp tujuh hari; jika memilih feed broker, kelengkapan dan perbedaan hasil harus divalidasi terpisah. Jangan mencampur spot weekend dengan CFD weekday secara diam-diam. Gunakan satu sumber tujuh hari untuk seluruh seri indikator; broker hanya untuk quote eksekusi, margin dan jadwal.

Leverage 1:200 berlaku sebagai asumsi replay ketiga simbol. Native LF122 memakai GetEstimatedMargin simbol broker dan menghormati batas per simbol/tier. Leverage akun tidak membuktikan leverage BTCUSD 1:200. Spesifikasi akun pengguna belum dibaca.

Sumber resmi: https://www.fpmarkets.com/cryptocurrency/ ; https://www.fpmarkets.com/en-sc/trading-hours/ ; https://help.ctrader.com/ctrader-algo/references/MarketData/MarketData/GetBars/ ; https://help.ctrader.com/ctrader-algo/references/MarketData/Symbols/Symbol/ .

## Konfigurasi dan status

- Indikator: Bitstamp OHLC M1 seluruh tujuh hari, agregasi H1/H4 UTC, seed 1 Januari 2019. Ini feed yang sama dengan input penelitian sebelumnya, bukan tick bid/ask FP Markets.
- Eksekusi replay: Senin 00:00–Jumat 22:00 UTC; blok entry 60 menit dan mulai flat 30 menit sebelum penutupan. Weekend candle memengaruhi sinyal, tetapi tidak mengizinkan entry weekend.
- Leverage XAU/EUR/BTC 200x; risiko gabungan 20,75%; cap margin entry 50%; profil BTC 7844/2269, SL/TP/hold, serta source XAU/EUR identik dengan LF122.
- Modal $100, tanpa top-up; periode portfolio sampai bar 9 Oktober 2026 21:58 UTC, cutoff eksklusif 21:59. Input BTC sampai 15 Oktober tidak memperpanjang hasil portfolio.
- NativeSevenDayFeedIntegrated=false; NativeDeploymentReady=false. Tidak ada binary .algo baru yang dipublikasikan untuk keputusan tujuh hari ini. Binary LF122 sebelumnya tetap membaca bar broker dan tidak otomatis berubah menjadi feed tujuh hari.
- Tidak mengubah bridge produksi, .env, risk live, instance cBot atau main. Tidak ada order live.

## Hasil aktual

| Ukuran | PATH A | PATH B |
|---|---:|---:|
| Saldo akhir USD | 23,680,551.82 | 23,610,673.16 |
| Floating DD % | 56.66960 | 61.74720 |
| Balance DD % | 49.56154 | 49.03174 |
| PF | 2.27544 | 2.16209 |
| Win rate basket % | 48.43 | 50.00 |
| Basket | 572 | 574 |
| BTC BUY | 58 | 58 |
| BTC SELL | 37 | 37 |
| Saldo LF122 indikator weekday, 200x | 20,347,817.71 | 20,808,380.46 |
| DD LF122 indikator weekday, 200x | 65.04314 | 65.47920 |

Kualifikasi floating DD <=56%: A=False, B=False.

Kedua replay lolos cash residual absolut < $0,00001, nol runtime error, nol posisi akhir, nol quarantine/accounting block, nol terminal forced close, dan pemeriksaan timestamp entry/flat weekend. Ketiga checksum input cocok dengan checkpoint asli. Tapes XAU/EUR dibangun ulang terpisah dari CSV penuh dengan algoritme yang sama untuk menghindari cache lama/tekanan memori; jumlah sinyal XAU 1175 dan EUR 379.

Ini source replay dua lintasan intramenit OHLC sintetis, bukan tick parity native/FULL_PARITY, bukan bound DD semua lintasan. Biaya/spread/delay sama dengan kasus normal LF122. Stress biaya/delay untuk varian tujuh hari +200x ini belum dijalankan. Sumber macro XAU belum vintage-certified; histori jadwal FP Markets belum disertifikasi.

Reproduksi: .NET SDK 8.0.426/runtime 8.0.32; jalankan prepare.py, build_tapes.py, kemudian TapeBuilder untuk XAU dan EUR secara terpisah; compile work/replay dengan work/run_local.py; jalankan run_pair.py A/B. Input harus cocok INPUT_SHA256.json dan berada di inputs/ pada folder saudara research_sevenday. Dataset besar tidak diduplikasi dalam paket. Full model source, raw replay, ledger, CSV dan diff disertakan.
