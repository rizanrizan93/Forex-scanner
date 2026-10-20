# cBot XAU–EUR–BTC FROZEN 7-DAY WEEKEND V1.3.0

**Strategi terpilih dibekukan dan .algo native dibangun, default EnableTrading=false. Versi ini tetap gagal floating DD≤56% dan target portfolio $90 juta.** V1.2.1 lama tidak diubah. Tidak ada deployment atau order live.

## Identitas dan bukti

- Source final: `787ac228837175f9c07c4e13070e2794ebc7a7fe`.
- Branch: `release/xau-eur-btc-7day-frozen-v1.3.0`.
- Actions: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39402108661 — completed/success; job118559077604.
- Artifact CI: `12255635264`. ZIP luar SHA256 `48dacfdf517b54a58d48da25013ae8e39e46b101580b6627eaa91dd7e6fa6a07`.
- Binary: `RizanXauEurBtcPortfolio_FROZEN_7DAY_WEEKEND_V1_3_0.algo`; assembly1.3.0.0; SHA256 `a3d00f27ebe1f4f9eec2ede99fe56ef581556c42492e6e04817be19b19003b9c`.
- Binary rilis ini adalah CI_NATIVE_REBUILD.algo dari source final yang dipromosikan ke nama rilis. Hash keduanya identik. Binary lokal sebelum guard null-label telah digantikan.
- FREEZE_MANIFEST.json mematok source. SHA256_MANIFEST.json mematok setiap anggota paket. CHANGE_FROM_LF122.diff menampilkan perubahan aktual.

## Hasil model yang benar-benar diulang

Periode 1 Januari 2019 sampai bar portfolio 9 Oktober 2026 21:58 UTC. Modal $100 tanpa top-up. BTC input sampai 15 Oktober tidak memperpanjang periode portfolio.

| Ukuran | PATH A | PATH B |
|---|---:|---:|
| Saldo akhir USD | 23,680,551.82 | 23,610,673.16 |
| Floating DD % | 56.66960 | 61.74720 |
| Balance DD % | 49.56154 | 49.03174 |
| Profit factor | 2.27544 | 2.16209 |
| Win rate basket % | 48.42657 | 50.00000 |
| Basket total | 572 | 574 |
| Basket BUY | 360 | 364 |
| Basket SELL | 212 | 210 |
| XAU basket | 294 | 297 |
| EUR basket | 183 | 182 |
| BTC basket | 95 | 95 |
| BTC BUY | 58 | 58 |
| BTC SELL | 37 | 37 |

XAU/EUR tetap maksimum tiga tahap layering sesuai source. BTC hanya satu basket, tanpa layering, BE atau trailing. Win rate dihitung per basket dari seluruh net P/L fill terkait, termasuk fee dan swap.

Kedua run nol posisi akhir, nol terminal forced close, nol runtime error, nol quarantine/accounting block. Cash residual absolut < $0,00001. Audit independen memeriksa 190 posisi BTC gabungan: nol entry weekend dan nol exit melewati cutoff21:30 UTC + toleransi 5 detik pada kalender replay asumsi.

BrokerHistory, basket ledger, CashEvents, equity curve, annual dan monthly seluruhnya identik dengan replay tujuh hari+200x terpilih sebelumnya. Bukti comparison JSON disertakan. Run diagnostik tanpa heartbeat idle tetap disimpan terpisah: harness lama memperbarui waktu ACK hanya ketika instrumen dikelola, sehingga gate koneksi baru menganggap sebagian simbol stale. Model normal kini memberi heartbeat sintetis andal independen dari aktivitas instrumen; ini perbaikan harness, tanpa tuning entry/SL/TP/risiko.

## Saldo tahunan USD

| Tahun | PATH A | PATH B |
|---|---:|---:|
| 2019 | 2,812.27 | 2,590.26 |
| 2020 | 29,802.30 | 34,517.79 |
| 2021 | 64,822.86 | 274,068.32 |
| 2022 | 272,332.78 | 1,097,311.03 |
| 2023 | 1,551,842.85 | 2,257,867.24 |
| 2024 | 6,036,249.20 | 6,648,353.57 |
| 2025 | 15,628,817.25 | 16,170,806.23 |
| 2026 sampai 9 Okt | 23,680,551.82 | 23,610,673.16 |

Seluruh 188 bulan/path ada di analysis/MONTHLY_CASH.csv. Saldo akhir bulan dihitung dari CashEvents sebenarnya, termasuk funding saat posisi masih terbuka. Closed basket P/L ditampilkan terpisah dan tidak dipaksakan sama dengan perubahan cash bulan yang sama. Oktober 2026 parsial.

## Kontribusi net dan kerugian basket USD

| Path / grup | Net P/L | Total basket rugi |
|---|---:|---:|
| A / XAU | 19,535,805.56 | -12,091,022.98 |
| A / EUR | 1,347,545.56 | -2,791,498.74 |
| A / BTC BUY | 1,820,104.60 | -3,157,393.81 |
| A / BTC SELL | 976,996.10 | -526,559.83 |
| B / XAU | 19,022,952.65 | -13,232,661.35 |
| B / EUR | 1,669,843.26 | -3,138,564.75 |
| B / BTC BUY | 1,868,875.45 | -3,340,217.87 |
| B / BTC SELL | 1,048,901.79 | -605,827.47 |

PATH A: kontribusi net terbesar XAU; akumulasi kerugian basket terbesar XAU. Kerugian fill individual juga tersedia di CSV, agar tidak tercampur dengan klasifikasi basket.

PATH B: kontribusi net terbesar XAU; akumulasi kerugian basket terbesar XAU. Kerugian fill individual juga tersedia di CSV, agar tidak tercampur dengan klasifikasi basket.

## Apa yang dibekukan

Indikator BTC memakai satu seri Bitstamp M1 seluruh tujuh hari, H1/H4 UTC sejak2019; 68.280 bar seed H1 dipatok hash. Tidak menyambung candle spot weekend ke CFD weekday. BtcCore.cs dan BtcWeekendPolicy.cs identik byte dengan LF122. Enam dari delapan file XAU/EUR identik byte; dua RizanRobot.cs hanya mendapat properti pemeriksaan koneksi untuk gate host. Profil entry, SL, TP, hold, risk dan layering tidak dituning.

Profil BTC BUY 7844: displacement H4, bullish body/ATR14>1,4, close>high sebelumnya, close>EMA80 dan EMA20>EMA80. Entry00–08 UTC, SL 2 ATR, TP 12R, hold 128 jam, risk 23%, margin 95%. SELL 2269: compression H1, mean range4<0,7previousATR, close<low16−0,1ATR, tren H4 bearish, body≤2,5ATR, RSI14≥25, ATR/ATR20back0,6–1,8; SL 1,5 ATR, TP 2R, hold 8 jam, risk 18%, margin 30%.

Sinyal candle closed, model next-open, chase maksimum 0,5 ATR, satu basket BTC. Busy signal dikonsumsi, opposite bersamaan dibuang. Minimum/step 0,01 BTC, maksimum 100 BTC dan tetap mengikuti unit broker. Budget risiko bukan jaminan batas kerugian.

Risk entry gabungan 20,75%, margin entry 50%, satu saldo/margin bersama, prioritas EUR→XAU→BTC. Model leverage ketiga simbol 200x. Native memakai GetEstimatedMargin per simbol/tier seperti engine lain, tanpa floor BTC 10x; cBot tidak dapat memaksa FP Markets memberi BTC 200x hanya karena leverage akun 200x. MODEL_CONFIG.json dan source memuat parameter penuh XAU/EUR/BTC beserta perbedaan reserve budget dan friction aktual replay.

Pengaman BTC: broker MarketHours UTC, blok entry 60 menit, mulai flat 30 menit sebelum penutupan mingguan, hold dipotong cutoff, Sabtu/Minggu entry diblokir. ExitPending tersimpan sebelum close dan close gagal tetap di-retry. Intent bertahan lewat restart. EnableTrading=false melarang request trading termasuk close. Terminal mati, jaringan putus, pasar tutup atau broker menolak close dapat menggagalkan flat tepat waktu.

## Bridge dan state

Service produksi hanya dibaca melalui SSH pada Actions. Snapshot final menunjukkan service aktif, monitor 14,866 detik pada siklus publikasi 30 detik, XAU/EUR masing-masing satu koneksi, macro/event XAU ready, kontrak cocok, tanpa quarantine atau pending intent pada lima checkpoint yang diperiksa. Authority=NONE. Ini snapshot kesehatan, bukan jaminan keamanan tanpa batas waktu. Source checksum dan JSON lengkap disertakan.

Bridge BTC7D baru BELUM dipasang di produksi. Paket bridge/server.py berfungsi sebagai endpoint data/checkpoint terpisah, tanpa broker credential atau executor. Bind 127.0.0.1:8130, token baru terpisah, account binding, WSS :25345 melalui konfigurasi proxy yang disertakan untuk ditinjau. Script tidak memuat .env produksi. Tidak ada installer/restart otomatis.

Client menolak public ws/plaintext, port/URL credential yang salah, data stale/future, seed berubah dan bar extension yang tidak lengkap. State menggunakan SQLite WAL synchronous FULL, CAS revision dan lease 45 detik. Local WAL dibaca ulang setelah flush; entry BTC menunggu remote ACK intent. Replay atau restart dengan Sending tidak pasti tidak otomatis mengirim order lagi. Heartbeat stale 25 detik atau bridge gagal memblokir entry gabungan. Manajemen posisi tetap berjalan, termasuk retry exit BTC. Nilai token tidak ditampilkan pada judul cBot.

## Validasi dan batas

Build native resmi cTrader.Automate 1.0.21,  .NET 6 target: 0 error/0 warning. SDK 8.0.426/runtime 8.0.32. Total 1.087 assertion C# lulus: portfolio 827 termasuk 200 reconnect, weekend 25, leverage 31, feed/state 204 termasuk 158 sinyal M1 identik. Enam tes Python network/store lulus. CI mengulang native build, metadata default OFF/token hidden, dan seluruh suite tersebut.

Tes Settlement/Timing lama yang mengharapkan entry setelah bridge outage disimpan di work/legacy_validation dengan log gagal diagnostiknya. Perilaku itu sengaja diblokir oleh gate V1.3.0 dan tidak dihitung sebagai tes lulus. Ledger dan cash pada replay normal tetap direkonsiliasi dan identik dengan model terpilih. Tidak memindahkan klaim 1.326/1.357 tes dari versi lain ke binary ini.

Full portfolio stress biaya 1,5×/2×, next-M1 delay, serta leverage BTC 2×/5× BELUM dijalankan untuk V1.3.0. Tes sizing leverage 31 assertion bukan hasil stress portfolio. Untuk stress berikutnya commission/slippage/funding dikali, spread tetap.

Replay source menggunakan fake broker, OHLC dua lintasan, fee normal dan reliable synthetic ACK. Native websocket/feed/state diuji terpisah; native ACK/timer/feed latency tidak dimodelkan penuh oleh replay entry, sehingga ini bukan FULL_PARITY atau hasil backtest cTrader tick broker. Native .algo belum dijalankan pada akun demo/live. Jadwal broker historis/DST dan macro XAU vintage point-in-time belum disertifikasi.

## Penggunaan paket

Import binary melalui cTrader Algo yang mendukung cBot dan biarkan EnableTrading=false. URL/token/ExpectedAccount sengaja kosong. Endpoint XAU/EUR lama dan endpoint BTC7D baru harus tersedia dan diverifikasi secara terpisah sebelum entry dapat siap. Jangan menjalankan dua versi pada akun yang sama atau menganggap checkpoint lama dapat dipindahkan tanpa rekonsiliasi posisi. Tidak ada aktivasi live yang dilakukan dalam pekerjaan ini.

Rekonstruksi build: unduh NuGet resmi cTrader.Automate 1.0.21 dan Microsoft.NETCore.App.Ref6.0.36 ke work/vendor, jalankan work/build_native.py --sdk PATH_SDK. CI workflow dalam paket memberikan perintah lengkap. Input replay mengacu INPUT_SHA256.json dan CSV EUR penuh yang benar, bukan arsip EUR terpotong 2025. Seed H1 disertakan untuk feed; CSV M1 besar tidak diduplikasi.

Jalankan verify_release.py terhadap ZIP untuk memeriksa hash setiap anggota. Native source commit di atas dan manifest bersifat otoritatif; paket final dapat disimpan pada commit arsip berikutnya tanpa mengubah source beku.

## Catatan penyelesaian source final

Replay lengkap aktual terakhir yang berhasil disimpan memakai source sebelum dua guard null-label terakhir (commit43d78e4a…). Replay ulang dari source final terhenti akibat pemeliharaan workspace dan tidak diklaim selesai. Source engine final787ac228… identik dengan source replay tersebut setelah dua ekspresi ownership null-safe dinormalisasi. Seluruh label dalam ledger replay non-null. Dengan demikian perubahan ini tidak mengubah fungsi ownership pada data replay yang tersimpan; hasil model di atas tetap diberi identitas replay aslinya. FINAL_GUARD_EQUIVALENCE.json mencatat bukti dan batas ini.

Binary final berasal dari build CI resmi pada commit787ac228…, dengan tes posisi/history BTC manual berlabel null yang lulus. Posisi manual dilewati dan tidak ditutup oleh aturan BTC weekend. Tidak ada perubahan entry, SL, TP, risk, indikator atau sizing dalam perbaikan terakhir. Belum ada uji tick native/demo/forward dan tidak ada deployment live.
