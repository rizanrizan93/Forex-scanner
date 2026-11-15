# Deliverable3 — Combined Strategy Research & Robustness

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

| scenario | candidate | starting_equity | ending_equity | profit_factor | trades | floating_equity_dd |
| --- | --- | --- | --- | --- | --- | --- |
| BASE_PERIODS | MOMENTUM_ASIA_FULL_R1.5 | 10,000.0000 | 105.9937 | 0.6354 | 1032 | 0.9896 |
| BASE_PERIODS | SWEEP_MSS_FVG_ASIA_FULL_R2.0 | 10,000.0000 | 9,629.4463 | 0.6234 | 35 | 0.0686 |
| BASE_PERIODS | OPENING_BREAKOUT_ASIA_FULL_R1.5 | 10,000.0000 | 75.9002 | 0.5058 | 841 | 0.9925 |
| BASE_PERIODS | NY_CONTINUATION_ASIA_FULL_R3.0 | 10,000.0000 | 7,704.5393 | 0.8321 | 452 | 0.3391 |
| BASE_PERIODS | TREND_FVG_ASIA_FULL_R3.0 | 10,000.0000 | 8,860.2483 | 0.5320 | 81 | 0.1642 |
| STRESS15_PERIODS | MOMENTUM_ASIA_FULL_R1.5 | 10,000.0000 | 64.6420 | 0.2668 | 548 | 0.9936 |
| STRESS15_PERIODS | SWEEP_MSS_FVG_ASIA_FULL_R2.0 | 10,000.0000 | 9,455.3914 | 0.4107 | 31 | 0.0657 |
| STRESS15_PERIODS | OPENING_BREAKOUT_ASIA_FULL_R1.5 | 10,000.0000 | 59.3234 | 0.3138 | 568 | 0.9941 |
| STRESS15_PERIODS | NY_CONTINUATION_ASIA_FULL_R3.0 | 10,000.0000 | 3,745.9309 | 0.5759 | 467 | 0.6826 |
| STRESS15_PERIODS | TREND_FVG_ASIA_FULL_R3.0 | 10,000.0000 | 8,606.9563 | 0.3844 | 74 | 0.1821 |
| STRESS20_PERIODS | MOMENTUM_ASIA_FULL_R1.5 | 10,000.0000 | 60.5946 | 0.0895 | 376 | 0.9940 |
| STRESS20_PERIODS | SWEEP_MSS_FVG_ASIA_FULL_R2.0 | 10,000.0000 | 9,556.6325 | 0.3658 | 26 | 0.0490 |
| STRESS20_PERIODS | OPENING_BREAKOUT_ASIA_FULL_R1.5 | 10,000.0000 | 58.8096 | 0.1128 | 382 | 0.9941 |
| STRESS20_PERIODS | NY_CONTINUATION_ASIA_FULL_R3.0 | 10,000.0000 | 221.1694 | 0.2779 | 479 | 0.9923 |
| STRESS20_PERIODS | TREND_FVG_ASIA_FULL_R3.0 | 10,000.0000 | 8,442.3618 | 0.2607 | 69 | 0.1881 |
| ZERO_DIAGNOSTIC_PERIODS | MOMENTUM_ASIA_FULL_R1.5 | 10,000.0000 | 15,065.5160 | 1.1815 | 1133 | 0.0926 |
| ZERO_DIAGNOSTIC_PERIODS | SWEEP_MSS_FVG_ASIA_FULL_R2.0 | 10,000.0000 | 9,989.7599 | 0.9912 | 46 | 0.0572 |
| ZERO_DIAGNOSTIC_PERIODS | OPENING_BREAKOUT_ASIA_FULL_R1.5 | 10,000.0000 | 13,416.0028 | 1.1076 | 1272 | 0.1634 |
| ZERO_DIAGNOSTIC_PERIODS | NY_CONTINUATION_ASIA_FULL_R3.0 | 10,000.0000 | 13,187.0741 | 1.2616 | 443 | 0.0881 |
| ZERO_DIAGNOSTIC_PERIODS | TREND_FVG_ASIA_FULL_R3.0 | 10,000.0000 | 10,009.3586 | 1.0038 | 88 | 0.0982 |
| BASE_COMPOUND_PERIODS | MOMENTUM_ASIA_FULL_R1.5 | 10,000.0000 | 3,423.3785 | 0.6285 | 1129 | 0.6702 |
| BASE_COMPOUND_PERIODS | SWEEP_MSS_FVG_ASIA_FULL_R2.0 | 10,000.0000 | 9,640.8858 | 0.6302 | 35 | 0.0670 |
| BASE_COMPOUND_PERIODS | OPENING_BREAKOUT_ASIA_FULL_R1.5 | 10,000.0000 | 2,694.8373 | 0.5610 | 1273 | 0.7391 |
| BASE_COMPOUND_PERIODS | NY_CONTINUATION_ASIA_FULL_R3.0 | 10,000.0000 | 7,665.6260 | 0.7898 | 446 | 0.2900 |
| BASE_COMPOUND_PERIODS | TREND_FVG_ASIA_FULL_R3.0 | 10,000.0000 | 8,931.0364 | 0.5284 | 81 | 0.1560 |
| BASE_COMPOUND_100_PERIODS | MOMENTUM_ASIA_FULL_R1.5 | 100.0000 | 100.0000 | N/A | 0 | N/A |
| BASE_COMPOUND_100_PERIODS | SWEEP_MSS_FVG_ASIA_FULL_R2.0 | 100.0000 | 100.0000 | N/A | 0 | N/A |
| BASE_COMPOUND_100_PERIODS | OPENING_BREAKOUT_ASIA_FULL_R1.5 | 100.0000 | 100.0000 | N/A | 0 | N/A |
| BASE_COMPOUND_100_PERIODS | NY_CONTINUATION_ASIA_FULL_R3.0 | 100.0000 | 100.0000 | N/A | 0 | N/A |
| BASE_COMPOUND_100_PERIODS | TREND_FVG_ASIA_FULL_R3.0 | 100.0000 | 100.0000 | N/A | 0 | N/A |

Tanpa friction beberapa hipotesis terlihat positif; pada biayaBASE hasilnya negatif. Pelebaran biaya mengubah bukan hanya P/L, tetapi juga apakah limit tersentuh, lot/minimum yang terjangkau, dan kesempatan entry berikutnya. Karena itu net profit sensitivitas tidak harus menurun monoton untuk setiap setup; jangan menafsirkan nonmonotonisitas sebagai biaya tinggi menambah alpha.

SkenarioUSD100 dengan risk0,5% current balance menghasilkan0trade untuk seluruh5setup:minimum1oz dan jarakSL/biaya tidak terjangkau. SaldoUSD100 yang tetap bukan keuntungan. Ini tidak menguji seedEUR atau perpindahan125 Frozen.

## Statistik, walk-forward dan stabilitas

| candidate | expectancy_usd | ci95_low | ci95_high | one_sided_centered_bootstrap_p | prob_expectancy_positive | replicates | block_trading_days | holm_p_5_asia_setups |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MOMENTUM_ASIA_FULL_R1.5 | -9.5872 | -12.7038 | -6.4009 | 1.0000 | 0.0000 | 3000 | 5 | 1.0000 |
| SWEEP_MSS_FVG_ASIA_FULL_R2.0 | -10.5872 | -26.5614 | 5.6769 | 0.8954 | 0.0973 | 3000 | 5 | 1.0000 |
| OPENING_BREAKOUT_ASIA_FULL_R1.5 | -11.8004 | -14.8092 | -8.7959 | 1.0000 | 0.0000 | 3000 | 5 | 1.0000 |
| NY_CONTINUATION_ASIA_FULL_R3.0 | -5.0785 | -10.6091 | 0.3711 | 0.9637 | 0.0337 | 3000 | 5 | 1.0000 |
| TREND_FVG_ASIA_FULL_R3.0 | -14.0710 | -25.1537 | -1.8225 | 0.9943 | 0.0133 | 3000 | 5 | 1.0000 |

Confidence interval adalah bootstrap blok5trading-day,3000replicates, termasuk hari kerja tanpa trade. Holm diterapkan pada5setup full-Asia, tetapi tidak sepenuhnya meniadakan pemilihan keluarga model/75percobaan. Positive-return probability adalah frekuensi bootstrap, bukan probabilitas keuntungan masa depan. P-value dihitung satu sisi terhadap mean nol dengan centered bootstrap; seluruh setup tidak lolos bukti expectancy positif.

Walk-forward memilih TP dari3tahun sebelum tahun test2022…2026 dan dilaporkan per setup/sesi pada walk_forward.csv. Parameter grid awal TP1,5/2/3R bukan optimasi semua elemen strategi. Grid eksploratif9kombinasi jarak/holding×5setup menghasilkan45baris test;1berprofit positif. Grid ditambahkan setelah hasil awal terlihat; hasilnya bukan test konfirmatori baru.

Sensitivitas jarakSL×1/1,6/2,3333 dari jarak awal, holding60/120/300menit, TP tetap hasil training. Hasil terpisah di parameter_sensitivity.csv. Arah perbaikan yang terlihat pada test lama memerlukan validasi baru, bukan promosi otomatis. Seluruh historical splits bersifat retrospective:periode test sudah tersedia ketika penelitian ini dirancang. Tidak ada klaim forward/prospective validation.

## Keputusan gabungan

Belum ada kandidat Asia full-Asia dengan parameter training yang memberi bukti net expectancy positif dan layak dipasangkan ke Frozen pada risiko setara. Model total-profit terbaik maupun risk-adjusted terbaik untuk model1–7 secara lengkap **belum dapat ditetapkan**. Lowest drawdown pada strategi yang masih rugi tidak membuktikan alpha. Batas DD deployment baru belum disetujui karena belum ada kandidat lolos.

## Satu kandidat eksploratif positif, tetapi gagal robustness

+TREND_FVG dengan jarakSL≈3,5ATR (2,3333×jarak awal), TP3R dan holding maksimum300menit memperoleh net profitUSD177,44 (+1,77%), PF1,1522, floatingDD2,6305%,78trade pada2024–Maret2026. Varian ini ditemukan setelah hasil awal terlihat dan tidak dipromosikan sebagai pemenang OOS konfirmatori.

+| period | net_profit | profit_factor | trades | floating_equity_dd |
| --- | --- | --- | --- | --- |
| TRAIN | -834.0742 | 0.3803 | 60 | 0.0964 |
| VALIDATION | -474.0730 | 0.5868 | 55 | 0.0500 |
| OOS | 177.4423 | 1.1522 | 78 | 0.0263 |

+Training2019–2021 rugiUSD834,07; validation2022–2023 rugiUSD474,07. Pada spread×1,5/slippage0,25 hasiltest berubah menjadi −USD84,25; pada spread×2/slippage0,50 menjadi −USD346,96. Confidence interval95% expectancy pertradeUSD-6.40 sampai 11.97, centered-bootstrap p=0.318. Interval melintasi nol dan p belum memperhitungkan penuh pencarian tambahan. Tahun2025 juga rugi; profit tidak konsisten setiap tahun. Kesimpulan:belum robust, tidak layak deployment atau klaim diversifikasi.

+| scenario | period | net_profit | profit_factor | trades | floating_equity_dd |
| --- | --- | --- | --- | --- | --- |
| STRESS15 | TRAIN | -853.4142 | 0.2350 | 48 | 0.0857 |
| STRESS15 | VALIDATION | -565.4075 | 0.4386 | 51 | 0.0616 |
| STRESS15 | OOS | -84.2512 | 0.9262 | 71 | 0.0407 |
| STRESS20 | TRAIN | -921.5612 | 0.1474 | 45 | 0.0924 |
| STRESS20 | VALIDATION | -613.9120 | 0.3197 | 45 | 0.0665 |
| STRESS20 | OOS | -346.9636 | 0.6865 | 66 | 0.0596 |
| BASE_ANNUAL | 2019 | -161.1782 | 0.3610 | 10 | 0.0233 |
| BASE_ANNUAL | 2020 | -276.0915 | 0.4360 | 24 | 0.0332 |
| BASE_ANNUAL | 2021 | -396.8045 | 0.3431 | 26 | 0.0533 |
| BASE_ANNUAL | 2022 | -143.4247 | 0.7355 | 27 | 0.0340 |
| BASE_ANNUAL | 2023 | -330.6482 | 0.4536 | 28 | 0.0464 |
| BASE_ANNUAL | 2024 | 168.7903 | 1.2413 | 44 | 0.0247 |
| BASE_ANNUAL | 2025 | -151.1713 | 0.6477 | 27 | 0.0213 |
| BASE_ANNUAL | 2026 YTD_MARCH | 159.8232 | 5.3256 | 7 | 0.0060 |
