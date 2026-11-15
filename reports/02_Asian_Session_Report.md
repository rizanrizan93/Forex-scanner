# Deliverable2 — Asian Session Backtest Report

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

| candidate | ending_equity | net_profit | profit_factor | win_rate_pct | expectancy_usd | trades | floating_DD_pct | return_over_dd |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NY_CONTINUATION_ASIA_FULL_R3.0 | 7,704.5393 | -2,295.4607 | 0.8321 | 31.1947 | -5.0785 | 452 | 33.9111 | -0.6769 |
| MOMENTUM_ASIA_FULL_R1.5 | 105.9937 | -9,894.0063 | 0.6354 | 34.3023 | -9.5872 | 1032 | 98.9588 | -0.9998 |
| SWEEP_MSS_FVG_ASIA_FULL_R2.0 | 9,629.4463 | -370.5537 | 0.6234 | 37.1429 | -10.5872 | 35 | 6.8570 | -0.5404 |
| TREND_FVG_ASIA_FULL_R3.0 | 8,860.2483 | -1,139.7517 | 0.5320 | 30.8642 | -14.0710 | 81 | 16.4155 | -0.6943 |
| OPENING_BREAKOUT_ASIA_FULL_R1.5 | 75.9002 | -9,924.0998 | 0.5058 | 31.0345 | -11.8004 | 841 | 99.2460 | -0.9999 |

Metrik lengkap starting/ending equity, net profit, PF, win rate, expectancy, jumlah/bulanan trade, closed DD, floating DD, return/DD, worst month, losing streak dan OOS ada di period_metrics.csv, annual_all_candidates.csv dan cost_and_sizing_metrics.csv. Kandidat yang kehabisan kapasitas akun tetap dicatat sebagai gagal dan minimum-lot/margin rejections disimpan; periode sesudahnya tidak diartikan sebagai bukti profit.

## Hasil setiap tahun:annual resetUSD10.000

Tiap kolom adalah saldo akhir dari akun baruUSD10.000 pada awal tahun. Angka tidak disambung menjadi compounding.2026 hanya tiga bulan.

| year | MOMENTUM | NY_CONTINUATION | OPENING_BREAKOUT | SWEEP_MSS_FVG | TREND_FVG |
| --- | --- | --- | --- | --- | --- |
| 2019 | 2,541.3108 | 7,026.0196 | 420.8315 | 9,955.2813 | 9,927.8763 |
| 2020 | 545.9924 | 7,852.9297 | 1,217.1072 | 9,980.1297 | 9,747.9446 |
| 2021 | 268.2594 | 6,890.2766 | 126.3736 | 9,893.2368 | 9,482.7454 |
| 2022 | 359.6937 | 7,008.9878 | 44.3470 | 9,723.9659 | 9,322.3309 |
| 2023 | 482.6957 | 6,640.6283 | 104.2962 | 9,803.7716 | 9,588.4792 |
| 2024 | 3,052.2773 | 7,541.9394 | 540.6277 | 10,205.5954 | 9,144.2935 |
| 2025 | 5,972.2711 | 9,676.5380 | 6,558.7040 | 9,475.8509 | 9,441.6583 |
| 2026 YTD to March | 10,133.0210 | 10,486.0619 | 10,067.6270 | 9,948.0000 | 10,274.2966 |

## Profil sesi dan liquidity

Statistik deskriptif memakai hari dengan≥90%bar tersedia; MACRO_READ memakai≥50% karena mencakup penutupan harian instrumen. Sampel replay lebih ketat:≥95%, pemeriksaan gap dan kedua sisi batas sesi. Perbedaan sampel dicatat di session_exclusions.csv dan data_quarantine.csv.

| session | days | mean_range_usd | mean_return_usd | median_return_usd | return_p05 | return_p95 | positive_return_frequency | mean_spread_usd | mean_realized_vol_pct | trend_frequency |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ASIA_EARLY | 1,861.0000 | 10.5961 | 0.4911 | 0.2120 | -10.0600 | 11.8565 | 0.5261 | 0.4392 | 0.2464 | 0.4535 |
| ASIA_FULL | 1,858.0000 | 13.0446 | 0.5111 | 0.1980 | -12.4752 | 13.9067 | 0.5178 | 0.4344 | 0.3142 | 0.4483 |
| ASIA_LATE | 1,859.0000 | 7.4117 | 0.0134 | 0.0550 | -7.2519 | 7.5672 | 0.5083 | 0.4279 | 0.1854 | 0.4271 |
| LONDON | 1,859.0000 | 13.9162 | 0.2164 | 0.3265 | -13.5730 | 14.3980 | 0.5266 | 0.4068 | 0.3743 | 0.4126 |
| MACRO_READ | 1,856.0000 | 9.1842 | 0.4509 | 0.0900 | -7.6129 | 9.5650 | 0.5135 | 0.4861 | 0.2217 | 0.3966 |
| NY_COMPARATOR | 1,860.0000 | 22.7591 | -0.1962 | 0.1775 | -25.9199 | 25.4578 | 0.5097 | 0.4121 | 0.6052 | 0.4489 |

Jam08WIB memiliki mean high–low terbesar di antara jam08–12 pada data ini. Itu ukuran range, bukan jam paling menguntungkan. entry_hour_profit.csv menyajikan keuntungan aktual menurut jam entry untuk setiap setup; tabel itu deskriptif dan tidak dipakai memilih ulang jam pada data test.

| hour_wib | days | mean_range | mean_return | mean_spread | long_net_1oz | short_net_1oz |
| --- | --- | --- | --- | --- | --- | --- |
| 8 | 1864 | 7.8733 | 0.4575 | 0.4449 | -0.2474 | -1.1624 |
| 9 | 1861 | 5.7971 | 0.0531 | 0.4333 | -0.6402 | -0.7464 |
| 10 | 1863 | 4.6394 | 0.0059 | 0.4304 | -0.6846 | -0.6963 |
| 11 | 1861 | 3.7918 | 0.0473 | 0.4265 | -0.6392 | -0.7337 |
| 12 | 1860 | 5.5872 | -0.0471 | 0.4290 | -0.7361 | -0.6419 |

long_net_1oz/short_net_1oz adalah ilustrasi midpoint-return dikurangi mean spread/komisi/slippage, bukan replay terpisah yang menjamin fill pada open/close jam. Semua mean ilustrasi arah pasif pada jam tersebut negatif setelah frictionBASE.

| session | days | breakout_days | continuations | false_breakouts | unresolved | continuation_given_resolved | opening_high_sweep_frequency | opening_low_sweep_frequency | previous_ny_high_sweep_frequency | previous_ny_low_sweep_frequency |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ASIA_EARLY | 1861 | 1600 | 664 | 858 | 78 | 0.4363 | 0.4342 | 0.4320 | 0.1172 | 0.1000 |
| ASIA_FULL | 1858 | 1760 | 730 | 994 | 36 | 0.4234 | 0.5404 | 0.5377 | 0.1395 | 0.1195 |
| ASIA_LATE | 1858 | 1789 | 803 | 963 | 23 | 0.4547 | 0.5797 | 0.6023 | 0.0700 | 0.0695 |
| LONDON | 1859 | 1835 | 842 | 980 | 13 | 0.4621 | 0.6385 | 0.6278 | 0.1276 | 0.1383 |
| NY_COMPARATOR | 1860 | 1849 | 886 | 962 | 1 | 0.4794 | 0.7242 | 0.7113 | 0.1904 | 0.1883 |

Breakout statistik:close M5 pertama melewati opening range30menit+0,05range; continuation jika close berikutnya mencapai ekstensi0,5range sebelum close kembali ke dalam range; unresolved jika sesi berakhir lebih dulu. Evaluasi memakai close berurutan sehingga tidak menebak urutan high/low candle. Sweep adalah wick menembus level dan close kembali melewatinya; ini definisi harga, bukan bukti niat smart money.

Pemilahan hari/bulan/tahun tersedia. Label news besar/non-news, rezim inflasi/Fed, physical Shanghai flows, dan surprise konsensus belum diuji karena histori/vintage yang diperlukan belum diperoleh. Jadwal Shanghai saat ini tidak diterapkan mundur sebagai kalender historis yang pasti.
