# Audit lanjutan cBot XAU–EUR–BTC FROZEN WEEKEND V1.2.1

**Baseline beku valid secara identitas paket dan rekonsiliasi, tetapi gagal batas floating DD ≤56% dan target saldo portofolio $90 juta. EnableTrading tetap false; tidak ada deployment atau order live.**

Periode modal 1 Januari 2019 sampai bar 9 Oktober 2026 21:58 UTC (cutoff eksklusif 21:59), $100 tanpa top-up. BTC input sampai 15 Oktober tidak memperpanjang periode portfolio. Semua angka USD. PF dan win rate dihitung pada basket, setelah biaya model.

| Ukuran | PATH A | PATH B |
|---|---|---|
| Saldo akhir | 14,168,707.28 | 18,043,274.23 |
| Floating equity DD | 62.94884% | 63.77678% |
| Balance DD | 49.62417% | 51.61029% |
| Profit factor | 2.44654 | 2.39867 |
| Win rate basket | 45.81% | 49.20% |
| Basket total | 561 | 565 |
| XAU / EUR / BTC | 287 / 178 / 96 | 291 / 179 / 95 |
| BTC BUY / SELL | 41 / 55 | 40 / 55 |

## Bukti identitas dan audit

- Source asli pada commit `1d6ad83f285f293b103342073b637fa16e597fb9` cocok dengan 14 hash source dalam manifest; delapan file strategi XAU/EUR identik byte dengan baseline sebelumnya.
- Head rilis yang diperiksa: `1981615a5e11c21b07a8e7b9900667b3568af4ee`. Branch riset terpisah: `research/weekend-v121-audit-stress-20261020`.
- Actions audit asli [39372200611](https://github.com/rizanrizan93/Forex-scanner/actions/runs/39372200611), job 118462333957: completed/success, diperiksa lewat jobs dan log aktual. Artefak 12241388216 diunduh dan checksum diverifikasi.
- ZIP luar: 4.486.869 byte, SHA256 `35a21f3814b5a43ce532e5096ca0acdd6b4aaee615216633912c8f1d79bf1453`.
- ZIP beku: 3.999.574 byte, SHA256 `6b5387dbea7c874c60d5479a61ac5f6a29f86c9907a8fdc370a04b72f7c0095f`; seluruh 75 anggota manifest lolos.
- Binary asli: `RizanXauEurBtcPortfolio_FROZEN_WEEKEND_V1_2_1.algo`, assembly 1.2.1.0; SHA256 `2384b0526e70ae8a0f3efe2ad26aa99d33627b7a42b8454dbdc44e442b28ec86`. Metadata membuktikan default OFF dan risk cap terkunci.
- Bukti VPS asli: `/home/Rizanrizan/rizan-ticks/REPLAY_RESULTS/xau-eur-btc-frozen-weekend-v121/run-39372200611/`; seluruh 19 baris VPS_VERIFICATION.txt menyatakan OK. Ini bukti penyimpanan saat run asli, bukan klaim pemeriksaan ulang isi VPS hari ini.
- Rebuild native resmi pada audit lanjutan berhasil; compiler log 0 byte (0 error/warning). Seluruh 1.326 pemeriksaan diulang dan lulus: 171 settlement, 827 portfolio termasuk 200 reconnect, 121 timing, 182 BTC, 25 weekend. Pengujian memakai stub untuk regresi; build native tidak sama dengan replay tick native.
- Replay NORMAL A/B audit lanjutan cocok persis seluruh BrokerHistory beku, serta saldo, DD, PF dan jumlah basket. Stress dan kontrol baru dijalankan lokal melalui source C# dan fake broker yang sama; jangan menyebutnya hasil native cTrader atau run Actions stress.
- Rekonsiliasi cash residual A -1.6763806343078613e-08 USD; B -2.0116567611694336e-07 USD. Seluruh bulan/tahun cocok kembali dengan saldo kas. Nol posisi akhir, terminal forced close, runtime error, quarantine dan accounting block pada baseline.
- Audit mandiri 191 posisi BTC: 0 entry weekend, 0 melewati close Jumat, 0 melewati cutoff 21:30 UTC dalam toleransi 5 detik untuk kalender asumsi.

## Perkembangan saldo tahunan

| Tahun | Saldo akhir A | Saldo akhir B | DD tahunan A | DD tahunan B |
|---|---|---|---|---|
| 2019 | 633.16 | 569.50 | 62.95% | 63.78% |
| 2020 | 2,479.92 | 2,815.53 | 46.94% | 49.96% |
| 2021 | 3,387.59 | 11,846.42 | 47.44% | 45.48% |
| 2022 | 12,841.37 | 73,742.44 | 44.16% | 35.03% |
| 2023 | 36,940.78 | 253,179.36 | 57.32% | 60.09% |
| 2024 | 107,630.51 | 663,178.97 | 45.38% | 44.23% |
| 2025 | 4,852,692.47 | 9,423,341.11 | 43.04% | 28.91% |
| 2026 | 14,168,707.28 | 18,043,274.23 | 29.81% | 18.37% |

2026 berakhir pada 9 Oktober. DD tahunan memakai puncak awal tahun masing-masing, bukan pengganti maximum DD seluruh periode.

## Kontribusi arah dan instrumen

Profit positif/rugi di bawah adalah penjumlahan net PnL fill yang untung/rugi, sesudah biaya; keduanya bukan gross trading PnL sebelum biaya. Basket yang mengandung beberapa fill bisa berbeda klasifikasi dari fill individual.

| Path | Instrumen/arah | Basket | Profit fill positif | Rugi fill negatif | Laba bersih |
|---|---|---|---|---|---|
| A | XAUUSD BUY | 194 | 8,735,866.79 | -4,821,036.47 | 3,914,830.32 |
| A | XAUUSD SELL | 93 | 12,705,129.80 | -3,469,130.63 | 9,235,999.17 |
| A | EURUSD BUY | 98 | 622,954.12 | -429,299.18 | 193,654.94 |
| A | EURUSD SELL | 80 | 452,165.08 | -208,402.63 | 243,762.45 |
| A | BTCUSD BUY | 41 | 379,527.22 | -433,226.39 | -53,699.17 |
| A | BTCUSD SELL | 55 | 1,087,067.01 | -453,007.43 | 634,059.57 |
| B | XAUUSD BUY | 198 | 12,396,806.14 | -5,678,736.42 | 6,718,069.73 |
| B | XAUUSD SELL | 93 | 13,047,208.17 | -4,213,905.13 | 8,833,303.04 |
| B | EURUSD BUY | 102 | 1,672,826.97 | -916,661.55 | 756,165.42 |
| B | EURUSD SELL | 77 | 802,857.16 | -439,705.98 | 363,151.18 |
| B | BTCUSD BUY | 40 | 1,806,892.00 | -1,086,909.59 | 719,982.42 |
| B | BTCUSD SELL | 55 | 1,245,142.67 | -592,640.22 | 652,502.45 |

XAU SELL menghasilkan laba bersih terbesar pada kedua path. XAU BUY menyumbang total rugi fill paling besar pada kedua path. BTC BUY PATH A negatif bersih. Kontribusi nominal ini sudah terpengaruh ukuran posisi dan compounding saldo bersama; bukan ukuran edge standalone.

## Layering dan arah

| Path | Instrumen | Basket | BUY/SELL | Basket stage tambahan | Maks fill/basket |
|---|---|---|---|---|---|
| A | XAUUSD | 287 | 194/93 | 5 | 10 |
| A | EURUSD | 178 | 98/80 | 147 | 89 |
| A | BTCUSD | 96 | 41/55 | 0 | 1 |
| B | XAUUSD | 291 | 198/93 | 6 | 10 |
| B | EURUSD | 179 | 102/77 | 149 | 135 |
| B | BTCUSD | 95 | 40/55 | 0 | 1 |

Konfigurasi XAU/EUR masing-masing memiliki tiga stage pada depth 0/0,2/0,4. Banyak fill dalam satu stage adalah pemecahan order batch, bukan jumlah layer strategi. BTC hanya satu posisi/basket tanpa layering, BE atau trailing.

## Kontrol setara XAU–EUR

| Path | XAU–EUR saja | Dengan BTC weekend | Rasio saldo | DD kontrol | DD dengan BTC |
|---|---|---|---|---|---|
| A | 4,945,782.89 | 14,168,707.28 | 2.86x | 54.08% | 62.95% |
| B | 14,014,134.90 | 18,043,274.23 | 1.29x | 52.87% | 63.78% |

Kontrol memakai input, cutoff, biaya normal, jalur OHLC, shared gate, delay fill/ACK dan leverage XAU/EUR 200× yang sama; hanya BTC dinonaktifkan pada fake host. Rasio lama 4,96× tidak digunakan sebagai pembanding versi weekend.

## Stress yang benar-benar dijalankan

Setiap stress mengubah satu dimensi dari baseline. Spread XAU/EUR dan BTC tetap. Biaya mengalikan komisi, slippage serta financing/swap; perkiraan budget biaya dalam strategi tetap beku. Leverage XAU/EUR tetap 200× pada seluruh skenario; BTC normal 10×. NEXT_M1 berarti setiap permintaan entry market (termasuk stage tambahan) diisi pada pembukaan M1 berikutnya, ACK tetap 2 detik; ClosePosition/exit mengikuti model baseline tanpa tambahan delay.

| Skenario | Saldo A | Saldo B | Floating DD A | Floating DD B | PF A/B | Basket A/B |
|---|---|---|---|---|---|---|
| NORMAL | 14,168,707.28 | 18,043,274.23 | 62.95% | 63.78% | 2.447 / 2.399 | 561 / 565 |
| COST_15 | 6,674.56 | 8,780.44 | 67.76% | 70.71% | 1.550 / 1.590 | 579 / 578 |
| COST_20 | 3,268.32 | 2,323.66 | 64.23% | 70.29% | 1.646 / 1.462 | 565 / 576 |
| NEXT_M1 | 1,814,887.87 | 1,630,677.68 | 63.31% | 72.51% | 2.187 / 2.197 | 555 / 558 |
| BTC_L2 | 7,142,693.90 | 13,910,114.81 | 53.69% | 52.18% | 2.189 / 2.410 | 570 / 569 |
| BTC_L5 | 12,383,378.88 | 16,909,441.06 | 52.85% | 49.94% | 2.432 / 2.439 | 559 / 558 |

Biaya 1,5×/2× menurunkan saldo akhir menjadi ribuan USD; hasil normal belum menunjukkan ketahanan terhadap stress biaya ini. Balance DD, win rate, BUY/SELL, gross/commission/funding, cash residual dan flag keselamatan setiap run ada dalam STRESS_CONTROL_METRICS.csv. Skenario leverage lebih rendah bukan rilis baru atau rekomendasi mengganti parameter beku.

## Mengapa weekend mengubah hasil dan DD

Perbandingan berikut memakai urutan diagnostik yang dideklarasikan, tanpa optimasi parameter:

| Model BTC | Saldo A | Saldo B | Floating DD A | Floating DD B |
|---|---|---|---|---|
| LEGACY_7D | 24,536,880.31 | 24,801,270.16 | 54.48% | 52.47% |
| FULL_INDICATORS | 21,656,470.11 | 19,994,969.26 | 57.59% | 59.58% |
| NORMAL | 14,168,707.28 | 18,043,274.23 | 62.95% | 63.78% |

Efek berurutan pada saldo akhir: kebijakan weekend mengurangi A $2.880.410,19 dan B $4.806.300,91; penggantian indikator kemudian mengurangi A $7.487.762,83 dan B $1.951.695,02. Ini efek total yang sudah memuat perubahan ukuran dan peluang berikutnya.

Pada langkah penggantian indikator PATH B, kontribusi net BTC justru bertambah $193.754,10, tetapi kontribusi XAU turun $2.095.675,83 dan EUR turun $49.773,30. Source XAU/EUR tetap identik; jalur saldo, gate margin/risiko dan ukuran posisi bersama berubah. Karena itu seluruh penurunan portfolio tidak dapat disebut kerugian langsung BTC.


LEGACY_7D memakai engine lama dan pasar tujuh hari. FULL_INDICATORS mengaktifkan pengaman weekend, tetapi indikator tetap membaca bar tujuh hari. NORMAL mempertahankan pengaman yang sama dan membuang bar luar sesi dari indikator. Selisih langkah pertama mencakup blok entry, cutoff flat, expiry, konsumsi sinyal dan akibat shared wallet; tidak boleh dilabeli efek close Jumat saja. Selisih langkah kedua mengukur perubahan indikator beserta konsekuensi sinyal dan compounding berikutnya.

| Path | Sinyal indikator 7 hari | Sinyal indikator weekday | Timestamp sama | Timestamp hilang/baru | ATR berubah pada timestamp sama |
|---|---|---|---|---|---|
| A | 158 | 107 | 76 | 82/31 | 76 |
| B | 158 | 107 | 76 | 82/31 | 76 |

| Path | Pasangan close Jumat teridentifikasi | Efek exit pada volume lama | Efek exit pada volume baru |
|---|---|---|---|
| A | 26 | -917,893.74 | -491,849.99 |
| B | 25 | -719,558.62 | -518,652.56 |

Angka efek exit hanya subset label sinyal yang cocok dan exit lama melewati cutoff baru. Ini perbandingan hasil per BTC dengan volume dinyatakan jelas, bukan seluruh perubahan profit portfolio.

Masing-masing baseline memiliki 23 exit BTC BUY bertimestamp Jumat 21:30; net kelompok tersebut A $379.484,14 dan B $1.806.853,15. Timestamp saja tidak membuktikan alasan exit, tetapi pola tersebut cocok dengan cutoff kebijakan.

`SEQUENTIAL_RESULT_DECOMPOSITION.csv` merekonsiliasi selisih laba per instrumen: basket baru/hilang, perubahan hasil per unit pada basket yang cocok, dan perubahan kuantitas. Kuantitas mencakup compounding, floor lot, layering serta gate shared wallet; tidak tersedia identifikasi kausal unik untuk compounding murni. Tidak tepat mengatribusikan seluruh selisih saldo pada BTC langsung.

Puncak equity yang mendasari maximum DD baseline tercatat pada episode BTC BUY 26 Juni 2019: model peak A $1.086,56 dan B $1.113,62, sementara cash sekitar $600. Posisi tersebut kemudian tercatat net loss sekitar $124,66/$127,85. Maximum DD keseluruhan sudah muncul pada snapshot 6 Agustus 2019 23:00 UTC, saat BTC BUY berikutnya masih aktif. Grafik per jam menunjukkan episode dan cumulative DD; waktu extremum event persis tidak disimpan dalam snapshot. Ini membedakan equity DD yang mencakup pelepasan floating profit dari balance DD.

## Konfigurasi replikasi beku

BTC BUY 7844: H4 displacement_follow; body bullish/ATR14 >1,4; close >high sebelumnya; H4 closed close >EMA80 dan EMA20 >EMA80; sesi 00–08 UTC; SL 2 ATR; TP 12R; hold 128 jam; risk budget 23%; margin budget 95%.

BTC SELL 2269: H1 compression_break; mean range 4 bar <0,7 ATR sebelumnya; close <low 16 bar −0,1 ATR; H4 bearish close <EMA80 dan EMA20 <EMA80; abs body ≤2,5 ATR; RSI14 ≥25; ATR14/ATR14 20 bar lalu 0,6–1,8; semua sesi; SL 1,5 ATR; TP 2R; hold 8 jam; risk 18%; margin 30%.

Keduanya memakai candle closed dan open berikutnya, chase maksimum 0,5 ATR, satu basket aktif, sinyal busy dikonsumsi tanpa antrean, konflik dua arah dibuang. Model volume 0,01 BTC step/min dan maksimal 100 BTC; native juga mengikuti batas broker. BTC floor margin 10× dan GetEstimatedMargin yang lebih konservatif tetap dipakai. Budget risiko bukan jaminan maksimum kerugian.

Portfolio: saldo/margin bersama, compounding, risk cap entry 20,75%, margin cap entry 50%, prioritas EUR → XAU → BTC, pengelolaan keselamatan BTC lebih dahulu. Source lengkap XAU/EUR dalam paket adalah spesifikasi otoritatif; delapan file itu tidak diubah.

XAU contract: tiga stage 0/0,2/0,4, add window 90 menit dengan konfirmasi, initial fraction 1, weight power 0,5, risk 12,1%, margin 50%, TP 5,5R, stop multiplier 2,4 ATR serta anchor, hold maksimum 480 menit dengan cutoff harian. EUR F0245: tiga stage 0/0,2/0,4, add window 210 menit, initial fraction 0,4, weight power 1,5, risk 20,75%, margin 50%, TP 10R; execution distance ×0,845; hold 240 menit dengan cutoff harian; BE cost-adjusted aktif setelah 2R. Sizing/degear/regime, sinyal dan recovery harus mengikuti source, bukan tabel ringkasan semata.

Weekend native: jadwal Symbol.MarketHours dalam UTC; entry stop 60 menit, flat mulai 30 menit sebelum close mingguan; hold dipotong cutoff, Sabtu/Minggu blok entry, jadwal tidak tersedia fail-closed. ExitPending disimpan sebelum close, gagal close di-retry ketika buka, intent bertahan restart. Hanya prefix BTC RZBTC8500283| yang dikelola. OFF tidak mengirim close ataupun order. Offline, broker reject atau pasar tutup dapat menghalangi flat.

Biaya BTC normal: spread 5 bp; komisi 5 bp per sisi; slippage 1 bp per sisi; financing debit 3 bp notional/hari kedua arah. XAU spread berasal dari kolom input, komisi $0,03/unit/sisi, slip $0,05/unit/sisi dan swap model sesuai hari rollover. EUR spread 0,00001, komisi 0,00003/unit/sisi dan slip 0,00001; model tidak membebankan financing EUR.

## Batas validasi

- BTC adalah Bitstamp OHLC M1, bukan bid/ask tick broker. XAU/EUR OHLC dan macro rekonstruksi belum FULL_PARITY/vintage certified.
- Kalender replay asumsi Senin 00–Jumat 22 UTC; bar BTC luar sesi dibuang dari indikator. Histori broker/DST belum disertifikasi; native membaca jadwal broker aktual.
- PATH A/B diagnosis urutan intramenit sintetis, bukan bound konservatif semua lintasan M1.
- Stress ini menguji asumsi tertentu, bukan validasi biaya broker aktual atau jaminan performa masa depan. Tidak ada pencarian jutaan konfigurasi baru.
- Risk/margin cap pada entry tidak menjamin rasio exposure sesudah equity berubah; baseline model pernah mengamati margin sekitar 59,6% dan open risk sekitar 25,7–26,0%.

## Saldo bulanan lengkap

Perubahan kas dan net fill yang closed direkonsiliasi secara terpisah. Pada input ini tidak ada selisih di batas bulan; CSV tetap menyimpan kolom rekonsiliasi dan enam arah instrumen. Oktober 2026 parsial sampai tanggal 9.

| Bulan | Net kas A | Saldo A | Net kas B | Saldo B |
|---|---|---|---|---|
| 2019-01 | 3.85 | 103.85 | 3.84 | 103.84 |
| 2019-02 | 86.05 | 189.89 | 85.98 | 189.82 |
| 2019-03 | 73.97 | 263.86 | 73.99 | 263.81 |
| 2019-04 | 175.10 | 438.96 | 184.17 | 447.97 |
| 2019-05 | -68.42 | 370.54 | -69.76 | 378.21 |
| 2019-06 | 107.41 | 477.95 | 101.68 | 479.89 |
| 2019-07 | -2.68 | 475.28 | -4.47 | 475.43 |
| 2019-08 | 57.47 | 532.74 | 56.73 | 532.16 |
| 2019-09 | 3.18 | 535.93 | -20.73 | 511.43 |
| 2019-10 | 38.70 | 574.62 | 29.79 | 541.22 |
| 2019-11 | 1.78 | 576.40 | 8.29 | 549.51 |
| 2019-12 | 56.76 | 633.16 | 19.99 | 569.50 |
| 2020-01 | 131.17 | 764.34 | 130.27 | 699.78 |
| 2020-02 | 0.81 | 765.15 | -6.60 | 693.18 |
| 2020-03 | 20.04 | 785.19 | -15.26 | 677.92 |
| 2020-04 | 46.61 | 831.81 | 128.22 | 806.14 |
| 2020-05 | 103.90 | 935.71 | 109.72 | 915.86 |
| 2020-06 | -232.58 | 703.12 | -249.57 | 666.29 |
| 2020-07 | 497.66 | 1,200.79 | 485.44 | 1,151.73 |
| 2020-08 | -229.89 | 970.90 | -294.79 | 856.94 |
| 2020-09 | 338.10 | 1,309.00 | 399.21 | 1,256.16 |
| 2020-10 | 242.08 | 1,551.08 | 483.10 | 1,739.26 |
| 2020-11 | -136.30 | 1,414.78 | -155.46 | 1,583.80 |
| 2020-12 | 1,065.14 | 2,479.92 | 1,231.74 | 2,815.53 |
| 2021-01 | -742.14 | 1,737.78 | -546.90 | 2,268.63 |
| 2021-02 | 1,082.75 | 2,820.52 | 1,228.61 | 3,497.24 |
| 2021-03 | 669.93 | 3,490.45 | 830.71 | 4,327.95 |
| 2021-04 | 1,190.50 | 4,680.94 | 3,189.96 | 7,517.91 |
| 2021-05 | -214.31 | 4,466.64 | 4,230.60 | 11,748.51 |
| 2021-06 | -499.95 | 3,966.69 | -1,105.88 | 10,642.64 |
| 2021-07 | 1,593.76 | 5,560.44 | 4,604.15 | 15,246.79 |
| 2021-08 | -320.68 | 5,239.76 | 2,412.20 | 17,658.98 |
| 2021-09 | 68.62 | 5,308.38 | -483.26 | 17,175.73 |
| 2021-10 | 102.10 | 5,410.47 | -1,744.65 | 15,431.07 |
| 2021-11 | -1,523.10 | 3,887.37 | -3,480.80 | 11,950.27 |
| 2021-12 | -499.78 | 3,387.59 | -103.85 | 11,846.42 |
| 2022-01 | -100.99 | 3,286.60 | -1,460.59 | 10,385.84 |
| 2022-02 | 223.34 | 3,509.94 | 1,192.75 | 11,578.59 |
| 2022-03 | 4,765.20 | 8,275.14 | 11,462.19 | 23,040.77 |
| 2022-04 | 1,363.87 | 9,639.00 | 4,214.03 | 27,254.80 |
| 2022-05 | 2,057.37 | 11,696.37 | 4,064.29 | 31,319.09 |
| 2022-06 | -423.26 | 11,273.12 | -2,208.06 | 29,111.03 |
| 2022-07 | -2,247.51 | 9,025.61 | -4,553.86 | 24,557.17 |
| 2022-08 | -626.46 | 8,399.15 | 2,511.68 | 27,068.84 |
| 2022-09 | -608.10 | 7,791.05 | -352.42 | 26,716.42 |
| 2022-10 | 5,340.91 | 13,131.96 | 26,214.16 | 52,930.58 |
| 2022-11 | -653.07 | 12,478.90 | 9,151.28 | 62,081.86 |
| 2022-12 | 362.47 | 12,841.37 | 11,660.58 | 73,742.44 |
| 2023-01 | 7,560.86 | 20,402.22 | 55,023.27 | 128,765.70 |
| 2023-02 | 10,356.98 | 30,759.20 | 101,322.96 | 230,088.66 |
| 2023-03 | -526.90 | 30,232.30 | -30,401.23 | 199,687.43 |
| 2023-04 | -1,048.35 | 29,183.96 | -15,430.97 | 184,256.46 |
| 2023-05 | 4,085.18 | 33,269.13 | 24,891.61 | 209,148.08 |
| 2023-06 | -8,457.88 | 24,811.25 | -34,953.17 | 174,194.91 |
| 2023-07 | -2,048.98 | 22,762.27 | -11,247.18 | 162,947.73 |
| 2023-08 | -2,410.38 | 20,351.90 | -20,513.16 | 142,434.57 |
| 2023-09 | 397.50 | 20,749.40 | -4,933.81 | 137,500.76 |
| 2023-10 | 9,219.68 | 29,969.08 | 66,589.91 | 204,090.67 |
| 2023-11 | 3,312.03 | 33,281.10 | 24,206.05 | 228,296.72 |
| 2023-12 | 3,659.68 | 36,940.78 | 24,882.64 | 253,179.36 |
| 2024-01 | -10,405.45 | 26,535.33 | -49,383.66 | 203,795.70 |
| 2024-02 | 7,737.98 | 34,273.32 | -2,123.65 | 201,672.04 |
| 2024-03 | 1,451.21 | 35,724.53 | 2,418.28 | 204,090.32 |
| 2024-04 | 26,710.42 | 62,434.95 | 224,197.25 | 428,287.57 |
| 2024-05 | 1,869.95 | 64,304.91 | 5,071.32 | 433,358.89 |
| 2024-06 | 19,915.73 | 84,220.64 | 282,059.12 | 715,418.01 |
| 2024-07 | 37,467.93 | 121,688.57 | 186,640.58 | 902,058.58 |
| 2024-08 | -19,364.47 | 102,324.10 | -201,580.14 | 700,478.44 |
| 2024-09 | 6,850.82 | 109,174.93 | 8,822.11 | 709,300.56 |
| 2024-10 | 68,755.63 | 177,930.55 | 201,089.81 | 910,390.37 |
| 2024-11 | -54,994.90 | 122,935.65 | -194,932.33 | 715,458.04 |
| 2024-12 | -15,305.14 | 107,630.51 | -52,279.07 | 663,178.97 |
| 2025-01 | 53,313.38 | 160,943.89 | 303,235.94 | 966,414.91 |
| 2025-02 | -14,846.74 | 146,097.15 | -69,566.62 | 896,848.29 |
| 2025-03 | 8,681.19 | 154,778.35 | 12,448.85 | 909,297.14 |
| 2025-04 | 383,984.96 | 538,763.30 | 2,312,591.91 | 3,221,889.05 |
| 2025-05 | 559,576.63 | 1,098,339.93 | 1,298,827.50 | 4,520,716.54 |
| 2025-06 | 286,340.76 | 1,384,680.69 | 556,180.53 | 5,076,897.07 |
| 2025-07 | -217,036.58 | 1,167,644.11 | -499,551.79 | 4,577,345.28 |
| 2025-08 | 129,556.42 | 1,297,200.53 | 82,332.71 | 4,659,677.99 |
| 2025-09 | 9,030.85 | 1,306,231.38 | -24,409.63 | 4,635,268.36 |
| 2025-10 | 1,575,092.46 | 2,881,323.84 | 2,354,402.94 | 6,989,671.30 |
| 2025-11 | 1,599,693.64 | 4,481,017.48 | 1,829,106.11 | 8,818,777.41 |
| 2025-12 | 371,674.99 | 4,852,692.47 | 604,563.70 | 9,423,341.11 |
| 2026-01 | -581,613.74 | 4,271,078.74 | -543,125.34 | 8,880,215.77 |
| 2026-02 | 1,121,907.37 | 5,392,986.11 | 1,069,482.98 | 9,949,698.74 |
| 2026-03 | 4,593,175.61 | 9,986,161.72 | 4,591,322.48 | 14,541,021.23 |
| 2026-04 | 413,715.68 | 10,399,877.40 | 404,456.95 | 14,945,478.17 |
| 2026-05 | 2,082,208.88 | 12,482,086.28 | 1,514,049.25 | 16,459,527.43 |
| 2026-06 | 1,772,345.59 | 14,254,431.87 | 1,608,173.58 | 18,067,701.01 |
| 2026-07 | -417,661.95 | 13,836,769.92 | -384,375.47 | 17,683,325.54 |
| 2026-08 | 187,357.21 | 14,024,127.13 | 214,590.68 | 17,897,916.22 |
| 2026-09 | -332,696.17 | 13,691,430.96 | -336,749.36 | 17,561,166.86 |
| 2026-10 | 477,276.32 | 14,168,707.28 | 482,107.37 | 18,043,274.23 |

Ledger asli, raw replay, diff, seluruh CSV serta bukti build/tes ada dalam ZIP pendamping. Hash berkas unduhan ada pada DELIVERY_SHA256.json; hash anggota ZIP termasuk source riset ada pada MEMBER_SHA256.json.
