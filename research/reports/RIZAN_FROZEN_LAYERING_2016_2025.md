# REPLAY LAYERING SETUP FROZEN — 2016–2025

**Keputusan: pertahankan baseline frozen; layering tidak diaktifkan di production.**

Modal awal $100 sekali, tanpa deposit tambahan, dikompaun selama sepuluh tahun. Uji hanya setup XAU BUY/SELL DD50 dan EUR DD37 yang sudah dibekukan. Tidak ada riset lead–lag baru, sinyal cross-asset, atau pengganti teknikal XAU.

22 konfigurasi per instrumen (baseline + 21 varian), replay M1, tujuh fold validasi temporal, biaya/slippage dan delay, bootstrap serta Monte Carlo. Angka saldo adalah hasil simulasi dengan asumsi biaya frozen, bukan saldo akun broker.

## Hasil utama

| Instrumen / konfigurasi | Saldo akhir | PF | DD M1 | WR | Setup | Setup/bulan | Setup dengan tambahan |
|---|---:|---:|---:|---:|---:|---:|---:|
| XAUUSD / BASELINE | $11,106.24 | 1.892 | 45.57% | 37.14% | 560 | 4.67 | 0 |
| XAUUSD / FULL_INITIAL_CONFIRMED_2_0.15 | $11,040.77 | 1.877 | 46.08% | 37.14% | 560 | 4.67 | 19 |
| EURUSD / BASELINE | $11,820.23 | 2.211 | 37.08% | 52.94% | 204 | 1.70 | 0 |
| EURUSD / UNIFORM_0.15 | $4,849.76 | 2.508 | 33.76% | 57.36% | 197 | 1.64 | 163 |

XAU: varian layer aktif dengan saldo tertinggi tetap lebih rendah dari baseline, dengan PF lebih rendah dan DD lebih tinggi. EUR: varian layer berpencar terbaik berdasarkan saldo menurunkan DD dan menaikkan PF, tetapi mengorbankan sekitar 59% saldo akhir. Semua enam varian EUR FULL_INITIAL identik dengan baseline: **tidak ada tambahan layer** karena sisa plafon risiko/margin dan ukuran lot minimum tidak cukup.

Varian default yang mempertahankan layer awal penuh lalu menambah setelah reversal (`FULL_INITIAL_CONFIRMED_1_0.25`) menghasilkan XAU $11,017.64, PF 1.879, DD 51.43%, 17 setup dengan tambahan. DD melewati batas profil DD50. Pada EUR hasilnya tetap $11,820.23 tanpa tambahan. Tidak ada alasan untuk memaksakan perubahan production.

## Cara layering diuji

BUY bertambah ketika harga bergerak lebih rendah dalam area valid; SELL dicerminkan. Empat kedalaman adalah 0, s, 2s, 3s dari jarak SL awal; s diuji pada 0.15, 0.25, 0.30 R. Bobot jumlah anak rata, linear atau kuadratik. Batas waktu tambahan 120 menit. Semua anak memakai SL/TP absolut dan expiry baseline; invalidasi membatalkan tambahan, SL tidak dilebarkan.

Konfirmasi tambahan: candle M15 selesai menembus high/low candle sebelumnya searah setup, candle M5 selesai juga mengonfirmasi, serta bias H1 diizinkan; XAU juga mempertahankan strict M15. Ini definisi candle-break eksplisit, bukan klaim telah mendeteksi semua MSS/CHOCH. Kedalaman yang pernah disentuh hanya menentukan eligibility; entry tambahan memakai quote saat konfirmasi, bukan harga lembah masa lalu. Satu tahap per timestamp konfirmasi.

Dua batas risiko dibedakan: varian split mencadangkan planned USD risk baseline, sedangkan FULL_INITIAL mempertahankan posisi awal dan boleh menggunakan kapasitas yang belum terpakai sampai plafon frozen. XAU 12.5% risiko / 50% margin; EUR 27.25% dengan multiplier virtual frozen / 60% margin dan hard cap anak. Kapasitas tetap ditentukan saat basket dibuka, tanpa daur ulang floating profit. Tambahan XAU melampaui desired count berdasarkan balance hanya dalam modul riset ini. Jadi hasil FULL_INITIAL tidak boleh disebut peningkatan profit dengan exposure awal yang persis sama.

## Rekonsiliasi baseline dan data

XAU direplikasi **tepat** terhadap arsip audit independen: saldo $11,106.236716427939, 560 setup, PF 1.891902042794, DD 45.566370286442%. Semua entry/exit raw-open pada ledger dicocokkan dengan indeks harga asli. Sumber sinyal frozen: SELL sweep group 6; BUY regression-channel reentry group 274, strict H1/M15. Macro daily dan blok berita full planned hold yang sudah menjadi bagian baseline tetap dipakai; tidak ada pengembangan macro baru.

EUR direplikasi tepat untuk saldo $11,820.225714285078, 204 setup, PF 2.211141400545. Virtual opportunity stream dan feedback fast/slow tetap frozen walaupun actual layer berubah. DD marker replay ini 37.077207%; helper referensi lama memakai bound OHLC berbeda dan menghasilkan 40.003135%. Perbandingan seluruh varian EUR memakai satu marker yang sama; perbedaan estimator dipertahankan dan dijelaskan, tidak disembunyikan.

XAU memakai sepuluh CSV harga asli dengan warmup 2015 dan indeks sinyal arsip; EUR sepuluh parquet M1 public HistData. Timestamp sumber EUR fixed EST UTC−5, lalu UTC; XAU CSV sudah UTC dan trim tahun sesuai WIB untuk menjaga indeks asli. Missing bars tidak diinterpolasi; agregasi konfirmasi hanya memakai bucket lengkap. Hash setiap input dan hash implementasi terdapat di JSON.

Biaya XAU: cautious-variable spread $0.25/$0.35/$0.40 per oz, prior-bar shock dan news shock arsip, slip $0.05 per sisi, synthetic NY17 rollover per anak. EUR: spread 0.00012 dan slip 0.00001 per sisi. Leverage referensi 100. Tidak ada actual historical ASK/fill/likuiditas broker. Daily yield adalah final revised values dengan conservative publication-lag proxy, bukan point-in-time vintages.

DD XAU mengikuti marker frozen adverse-then-close; EUR memakai bound OHLC. Exact tick path tidak tersedia. Jika bar dapat menyentuh TP sebelum limit tambahan, pending limit dibatalkan agar tidak mendapat winner tambahan yang urutannya tidak diketahui. STOP_FIRST berlaku dan layer yang tersentuh sebelum invalidasi intrabar dibebani loss.

## Semua kandidat, termasuk yang ditolak

### XAUUSD

| Varian | Saldo akhir | PF | DD M1 | WR | Setup | Setup/bulan | Setup dengan tambahan |
|---|---:|---:|---:|---:|---:|---:|---:|
| BASELINE | $11,106.24 | 1.892 | 45.57% | 37.14% | 560 | 4.67 | 0 |
| UNIFORM_0.15 | $3,044.86 | 1.680 | 46.48% | 38.04% | 560 | 4.67 | 209 |
| DEEP_WEIGHTED_0.15 | $2,338.99 | 1.604 | 47.38% | 38.04% | 560 | 4.67 | 209 |
| CONFIRMED_DEEP_0.15 | $856.48 | 1.538 | 44.45% | 37.32% | 560 | 4.67 | 11 |
| CONFIRMED_MORE_0.15 | $825.11 | 1.516 | 44.45% | 37.14% | 560 | 4.67 | 4 |
| CONFIRMED_QUADRATIC_0.15 | $839.12 | 1.526 | 44.45% | 37.32% | 560 | 4.67 | 7 |
| UNIFORM_0.25 | $1,792.49 | 1.537 | 44.45% | 37.86% | 560 | 4.67 | 195 |
| DEEP_WEIGHTED_0.25 | $1,223.26 | 1.434 | 44.45% | 38.04% | 560 | 4.67 | 195 |
| CONFIRMED_DEEP_0.25 | $827.37 | 1.517 | 44.45% | 37.32% | 560 | 4.67 | 9 |
| CONFIRMED_MORE_0.25 | $814.37 | 1.510 | 44.45% | 37.14% | 560 | 4.67 | 3 |
| CONFIRMED_QUADRATIC_0.25 | $816.14 | 1.511 | 44.45% | 37.14% | 560 | 4.67 | 2 |
| UNIFORM_0.3 | $1,600.78 | 1.566 | 44.45% | 37.86% | 560 | 4.67 | 186 |
| DEEP_WEIGHTED_0.3 | $1,201.81 | 1.482 | 44.45% | 37.86% | 560 | 4.67 | 186 |
| CONFIRMED_DEEP_0.3 | $823.36 | 1.515 | 44.45% | 37.32% | 560 | 4.67 | 7 |
| CONFIRMED_MORE_0.3 | $821.15 | 1.517 | 44.45% | 37.14% | 560 | 4.67 | 2 |
| CONFIRMED_QUADRATIC_0.3 | $822.91 | 1.519 | 44.45% | 37.14% | 560 | 4.67 | 1 |
| FULL_INITIAL_CONFIRMED_1_0.15 | $9,051.83 | 1.857 | 47.30% | 37.14% | 560 | 4.67 | 21 |
| FULL_INITIAL_CONFIRMED_2_0.15 | $11,040.77 | 1.877 | 46.08% | 37.14% | 560 | 4.67 | 19 |
| FULL_INITIAL_CONFIRMED_1_0.25 | $11,017.64 | 1.879 | 51.43% | 37.14% | 560 | 4.67 | 17 |
| FULL_INITIAL_CONFIRMED_2_0.25 | $9,137.11 | 1.865 | 49.87% | 37.14% | 560 | 4.67 | 14 |
| FULL_INITIAL_CONFIRMED_1_0.3 | $8,286.89 | 1.833 | 51.43% | 37.14% | 560 | 4.67 | 15 |
| FULL_INITIAL_CONFIRMED_2_0.3 | $9,428.01 | 1.869 | 49.87% | 37.14% | 560 | 4.67 | 12 |

Seluruh varian aktif ditolak untuk tujuan meningkatkan saldo akhir: tidak mengalahkan baseline. FULL_INITIAL EUR yang identik bukan alpha baru. Penurunan DD pada split-layer tetap dicatat sebagai trade-off exposure, tanpa promosi production.

| Varian | Expectancy R* | Median R* | MAE R* | MFE R* | Holding menit | Long / Short | Max anak | Max planned risk | Max margin |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BASELINE | 0.199 | -1.000 | 0.772 | 1.425 | 185.4 | 402 / 158 | 111 | 12.48% | 44.96% |
| UNIFORM_0.15 | 0.161 | -0.786 | 0.712 | 1.286 | 185.4 | 402 / 158 | 29 | 10.78% | 44.43% |
| DEEP_WEIGHTED_0.15 | 0.154 | -0.782 | 0.706 | 1.271 | 185.4 | 402 / 158 | 23 | 10.78% | 44.89% |
| CONFIRMED_DEEP_0.15 | 0.116 | -0.293 | 0.540 | 0.971 | 185.4 | 402 / 158 | 3 | 7.76% | 16.59% |
| CONFIRMED_MORE_0.15 | 0.115 | -0.333 | 0.539 | 0.969 | 185.4 | 402 / 158 | 3 | 6.66% | 17.52% |
| CONFIRMED_QUADRATIC_0.15 | 0.114 | -0.273 | 0.538 | 0.965 | 185.4 | 402 / 158 | 2 | 7.81% | 13.50% |
| UNIFORM_0.25 | 0.154 | -0.639 | 0.677 | 1.234 | 185.4 | 402 / 158 | 17 | 8.58% | 41.41% |
| DEEP_WEIGHTED_0.25 | 0.144 | -0.634 | 0.670 | 1.210 | 185.4 | 402 / 158 | 12 | 8.58% | 41.86% |
| CONFIRMED_DEEP_0.25 | 0.116 | -0.293 | 0.539 | 0.969 | 185.4 | 402 / 158 | 2 | 7.76% | 16.28% |
| CONFIRMED_MORE_0.25 | 0.115 | -0.333 | 0.538 | 0.967 | 185.4 | 402 / 158 | 2 | 6.66% | 12.16% |
| CONFIRMED_QUADRATIC_0.25 | 0.116 | -0.293 | 0.537 | 0.967 | 185.4 | 402 / 158 | 3 | 6.66% | 17.43% |
| UNIFORM_0.3 | 0.153 | -0.565 | 0.663 | 1.204 | 185.4 | 402 / 158 | 15 | 8.34% | 41.08% |
| DEEP_WEIGHTED_0.3 | 0.145 | -0.562 | 0.656 | 1.182 | 185.4 | 402 / 158 | 12 | 8.34% | 41.81% |
| CONFIRMED_DEEP_0.3 | 0.116 | -0.299 | 0.539 | 0.968 | 185.4 | 402 / 158 | 2 | 7.86% | 16.28% |
| CONFIRMED_MORE_0.3 | 0.115 | -0.293 | 0.536 | 0.965 | 185.4 | 402 / 158 | 2 | 6.66% | 12.16% |
| CONFIRMED_QUADRATIC_0.3 | 0.115 | -0.293 | 0.536 | 0.964 | 185.4 | 402 / 158 | 3 | 6.66% | 17.23% |
| FULL_INITIAL_CONFIRMED_1_0.15 | 0.089 | -0.091 | 0.227 | 0.440 | 185.4 | 402 / 158 | 90 | 12.48% | 45.04% |
| FULL_INITIAL_CONFIRMED_2_0.15 | 0.092 | -0.090 | 0.228 | 0.447 | 185.4 | 402 / 158 | 110 | 12.50% | 44.74% |
| FULL_INITIAL_CONFIRMED_1_0.25 | 0.092 | -0.098 | 0.230 | 0.449 | 185.4 | 402 / 158 | 110 | 12.47% | 48.60% |
| FULL_INITIAL_CONFIRMED_2_0.25 | 0.089 | -0.096 | 0.222 | 0.435 | 185.4 | 402 / 158 | 91 | 12.46% | 44.57% |
| FULL_INITIAL_CONFIRMED_1_0.3 | 0.088 | -0.098 | 0.228 | 0.441 | 185.4 | 402 / 158 | 83 | 12.48% | 47.22% |
| FULL_INITIAL_CONFIRMED_2_0.3 | 0.089 | -0.097 | 0.222 | 0.434 | 185.4 | 402 / 158 | 94 | 12.50% | 44.84% |

*R memakai reserved basket risk. FULL_INITIAL memakai plafon risk fraction; split memakai planned USD baseline. Karena denominator berbeda, R lintas keluarga perlu dibaca bersama USD/PF/DD. MAE/MFE merupakan observasi/bound M1, bukan exact tick. Sharpe/Sortino tidak dihitung karena uniform account-equity time series lengkap tidak disimpan. Session counts, net return, annual reset-$100, seluruh metrik, dan ledger dua konfigurasi utama ada di JSON.

### EURUSD

| Varian | Saldo akhir | PF | DD M1 | WR | Setup | Setup/bulan | Setup dengan tambahan |
|---|---:|---:|---:|---:|---:|---:|---:|
| BASELINE | $11,820.23 | 2.211 | 37.08% | 52.94% | 204 | 1.70 | 0 |
| UNIFORM_0.15 | $4,849.76 | 2.508 | 33.76% | 57.36% | 197 | 1.64 | 163 |
| DEEP_WEIGHTED_0.15 | $3,457.81 | 2.608 | 33.06% | 61.93% | 197 | 1.64 | 162 |
| CONFIRMED_DEEP_0.15 | $221.69 | 2.050 | 9.10% | 53.37% | 193 | 1.61 | 9 |
| CONFIRMED_MORE_0.15 | $221.12 | 2.045 | 9.10% | 53.37% | 193 | 1.61 | 9 |
| CONFIRMED_QUADRATIC_0.15 | $221.03 | 2.083 | 7.36% | 53.37% | 193 | 1.61 | 7 |
| UNIFORM_0.25 | $1,793.89 | 2.344 | 27.99% | 60.10% | 198 | 1.65 | 139 |
| DEEP_WEIGHTED_0.25 | $824.35 | 2.338 | 23.65% | 61.93% | 197 | 1.64 | 137 |
| CONFIRMED_DEEP_0.25 | $221.05 | 2.074 | 7.36% | 53.37% | 193 | 1.61 | 7 |
| CONFIRMED_MORE_0.25 | $221.66 | 2.091 | 7.36% | 53.37% | 193 | 1.61 | 6 |
| CONFIRMED_QUADRATIC_0.25 | $223.30 | 2.126 | 7.36% | 53.37% | 193 | 1.61 | 6 |
| UNIFORM_0.3 | $1,057.36 | 2.296 | 19.76% | 58.88% | 197 | 1.64 | 122 |
| DEEP_WEIGHTED_0.3 | $552.02 | 2.325 | 17.48% | 58.88% | 197 | 1.64 | 118 |
| CONFIRMED_DEEP_0.3 | $219.90 | 2.065 | 7.36% | 53.37% | 193 | 1.61 | 7 |
| CONFIRMED_MORE_0.3 | $221.13 | 2.087 | 7.36% | 53.37% | 193 | 1.61 | 6 |
| CONFIRMED_QUADRATIC_0.3 | $222.15 | 2.117 | 7.36% | 53.37% | 193 | 1.61 | 6 |
| FULL_INITIAL_CONFIRMED_1_0.15 | $11,820.23 | 2.211 | 37.08% | 52.94% | 204 | 1.70 | 0 |
| FULL_INITIAL_CONFIRMED_2_0.15 | $11,820.23 | 2.211 | 37.08% | 52.94% | 204 | 1.70 | 0 |
| FULL_INITIAL_CONFIRMED_1_0.25 | $11,820.23 | 2.211 | 37.08% | 52.94% | 204 | 1.70 | 0 |
| FULL_INITIAL_CONFIRMED_2_0.25 | $11,820.23 | 2.211 | 37.08% | 52.94% | 204 | 1.70 | 0 |
| FULL_INITIAL_CONFIRMED_1_0.3 | $11,820.23 | 2.211 | 37.08% | 52.94% | 204 | 1.70 | 0 |
| FULL_INITIAL_CONFIRMED_2_0.3 | $11,820.23 | 2.211 | 37.08% | 52.94% | 204 | 1.70 | 0 |

Seluruh varian aktif ditolak untuk tujuan meningkatkan saldo akhir: tidak mengalahkan baseline. FULL_INITIAL EUR yang identik bukan alpha baru. Penurunan DD pada split-layer tetap dicatat sebagai trade-off exposure, tanpa promosi production.

| Varian | Expectancy R* | Median R* | MAE R* | MFE R* | Holding menit | Long / Short | Max anak | Max planned risk | Max margin |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BASELINE | 0.273 | 0.077 | 0.616 | 0.999 | 200.5 | 114 / 90 | 264 | 25.87% | 59.99% |
| UNIFORM_0.15 | 0.223 | 0.100 | 0.398 | 0.733 | 201.9 | 109 / 88 | 251 | 19.21% | 59.62% |
| DEEP_WEIGHTED_0.15 | 0.212 | 0.074 | 0.340 | 0.664 | 201.9 | 109 / 88 | 214 | 17.35% | 59.76% |
| CONFIRMED_DEEP_0.15 | 0.017 | 0.009 | 0.172 | 0.221 | 201.2 | 105 / 88 | 6 | 5.33% | 32.97% |
| CONFIRMED_MORE_0.15 | 0.017 | 0.009 | 0.172 | 0.221 | 201.2 | 105 / 88 | 6 | 5.17% | 33.13% |
| CONFIRMED_QUADRATIC_0.15 | 0.015 | 0.009 | 0.170 | 0.218 | 201.2 | 105 / 88 | 6 | 5.41% | 33.42% |
| UNIFORM_0.25 | 0.172 | 0.066 | 0.302 | 0.563 | 202.1 | 110 / 88 | 105 | 12.24% | 59.62% |
| DEEP_WEIGHTED_0.25 | 0.122 | 0.045 | 0.246 | 0.444 | 201.9 | 109 / 88 | 47 | 8.74% | 59.22% |
| CONFIRMED_DEEP_0.25 | 0.016 | 0.009 | 0.169 | 0.217 | 201.2 | 105 / 88 | 6 | 5.35% | 33.07% |
| CONFIRMED_MORE_0.25 | 0.017 | 0.009 | 0.168 | 0.216 | 201.2 | 105 / 88 | 6 | 5.16% | 33.04% |
| CONFIRMED_QUADRATIC_0.25 | 0.018 | 0.009 | 0.167 | 0.216 | 201.2 | 105 / 88 | 6 | 5.34% | 33.04% |
| UNIFORM_0.3 | 0.136 | 0.071 | 0.288 | 0.505 | 201.9 | 109 / 88 | 62 | 10.15% | 58.80% |
| DEEP_WEIGHTED_0.3 | 0.100 | 0.043 | 0.225 | 0.391 | 201.9 | 109 / 88 | 32 | 6.33% | 59.24% |
| CONFIRMED_DEEP_0.3 | 0.016 | 0.009 | 0.169 | 0.217 | 201.2 | 105 / 88 | 4 | 4.23% | 22.04% |
| CONFIRMED_MORE_0.3 | 0.017 | 0.009 | 0.168 | 0.217 | 201.2 | 105 / 88 | 5 | 4.26% | 27.52% |
| CONFIRMED_QUADRATIC_0.3 | 0.017 | 0.009 | 0.167 | 0.216 | 201.2 | 105 / 88 | 4 | 4.23% | 22.01% |
| FULL_INITIAL_CONFIRMED_1_0.15 | 0.104 | 0.041 | 0.210 | 0.351 | 200.5 | 114 / 90 | 264 | 25.87% | 59.99% |
| FULL_INITIAL_CONFIRMED_2_0.15 | 0.104 | 0.041 | 0.210 | 0.351 | 200.5 | 114 / 90 | 264 | 25.87% | 59.99% |
| FULL_INITIAL_CONFIRMED_1_0.25 | 0.104 | 0.041 | 0.210 | 0.351 | 200.5 | 114 / 90 | 264 | 25.87% | 59.99% |
| FULL_INITIAL_CONFIRMED_2_0.25 | 0.104 | 0.041 | 0.210 | 0.351 | 200.5 | 114 / 90 | 264 | 25.87% | 59.99% |
| FULL_INITIAL_CONFIRMED_1_0.3 | 0.104 | 0.041 | 0.210 | 0.351 | 200.5 | 114 / 90 | 264 | 25.87% | 59.99% |
| FULL_INITIAL_CONFIRMED_2_0.3 | 0.104 | 0.041 | 0.210 | 0.351 | 200.5 | 114 / 90 | 264 | 25.87% | 59.99% |

*R memakai reserved basket risk. FULL_INITIAL memakai plafon risk fraction; split memakai planned USD baseline. Karena denominator berbeda, R lintas keluarga perlu dibaca bersama USD/PF/DD. MAE/MFE merupakan observasi/bound M1, bukan exact tick. Sharpe/Sortino tidak dihitung karena uniform account-equity time series lengkap tidak disimpan. Session counts, net return, annual reset-$100, seluruh metrik, dan ledger dua konfigurasi utama ada di JSON.

## Walk-forward / validasi temporal

Pilihan memakai train-prefix sampai tahun sebelumnya: DD terendah dengan PF dan expectancy minimal 95% baseline, frekuensi minimal 75%, minimum 30 setup. Saldo awal validation sama untuk baseline/kandidat, memakai saldo baseline yang diketahui pada awal tahun. Ini fold terpisah; bukan kurva gabungan portfolio switching. Annual reset-$100 di JSON hanyalah statistik tambahan.

Baseline pernah dioptimasi pada 2016–2025 dan sejarah ini sudah terlihat. Enam FULL_INITIAL ditentukan setelah melihat hasil awal split-layer. Karena itu 2025 adalah validasi temporal retrospektif, **bukan fresh/blinded OOS**. Tidak ada claim robust prospective alpha.

### XAUUSD validation

| Tahun test | Dipilih dari train | Modal awal bersama | Kandidat akhir | Baseline akhir | DD kandidat | DD baseline |
|---|---|---:|---:|---:|---:|---:|
| 2019 | BASELINE | $131.44 | $192.06 | $192.06 | 21.47% | 21.47% |
| 2020 | BASELINE | $192.06 | $180.74 | $180.74 | 37.32% | 37.32% |
| 2021 | CONFIRMED_MORE_0.15 | $180.74 | $265.43 | $293.88 | 15.03% | 25.91% |
| 2022 | UNIFORM_0.25 | $293.88 | $283.37 | $322.60 | 21.38% | 34.75% |
| 2023 | BASELINE | $322.60 | $333.28 | $333.28 | 34.29% | 34.29% |
| 2024 | UNIFORM_0.3 | $333.28 | $458.71 | $508.20 | 34.20% | 45.57% |
| 2025 | UNIFORM_0.3 | $508.20 | $2,234.70 | $11,106.24 | 29.97% | 41.73% |

### EURUSD validation

| Tahun test | Dipilih dari train | Modal awal bersama | Kandidat akhir | Baseline akhir | DD kandidat | DD baseline |
|---|---|---:|---:|---:|---:|---:|
| 2019 | BASELINE | $158.58 | $433.69 | $433.69 | 21.30% | 21.30% |
| 2020 | BASELINE | $433.69 | $815.70 | $815.70 | 18.66% | 18.66% |
| 2021 | BASELINE | $815.70 | $981.53 | $981.53 | 30.08% | 30.08% |
| 2022 | BASELINE | $981.53 | $3,158.75 | $3,158.75 | 35.34% | 35.34% |
| 2023 | BASELINE | $3,158.75 | $5,081.37 | $5,081.37 | 31.42% | 31.42% |
| 2024 | BASELINE | $5,081.37 | $6,927.02 | $6,927.02 | 20.79% | 20.79% |
| 2025 | BASELINE | $6,927.02 | $11,820.23 | $11,820.23 | 18.98% | 18.98% |

Pilihan train untuk 2025: XAU UNIFORM_0.3 mengurangi DD tahun itu menjadi 29.97% dari 41.73%, tetapi saldo akhir validation hanya $2,234.70 dibanding $11,106.24 dengan modal awal sama $508.20. EUR selalu memilih BASELINE. Ini tidak memenuhi tujuan peningkatan saldo akhir.

## Robustness / biaya / delay

Stress dijalankan pada kandidat train, CONFIRMED_MORE_0.25 dan FULL_INITIAL_CONFIRMED_1_0.25; bukan pada setiap kombinasi grid. Delay pada kandidat UNIFORM/BASELINE tidak mempunyai efek karena keduanya tidak menunggu konfirmasi. Delay konfigurasi confirmed diuji terpisah.

### XAUUSD stress

| Perturbasi | Kandidat akhir | DD kandidat | Baseline akhir | DD baseline |
|---|---:|---:|---:|---:|
| COST_X1_5 | $1,246.99 | 64.08% | $7,024.68 | 64.08% |
| COST_X2 | $792.77 | 83.13% | $2,344.54 | 83.13% |
| COST_X3 | $23.08 | 84.32% | $23.08 | 84.32% |
| CONFIRM_DELAY_1M | $1,600.78 | 44.45% | $11,106.24 | 45.57% |
| CONFIRM_DELAY_5M | $1,600.78 | 44.45% | $11,106.24 | 45.57% |
| CONFIRM_DELAY_10M | $1,600.78 | 44.45% | $11,106.24 | 45.57% |
| REQUESTED_DEEP_MORE_COST_X1.5 | $719.39 | 64.08% | $7,024.68 | 64.08% |
| REQUESTED_DEEP_MORE_COST_X2.0 | $617.58 | 83.13% | $2,344.54 | 83.13% |
| REQUESTED_DEEP_MORE_COST_X3.0 | $23.08 | 84.32% | $23.08 | 84.32% |
| REQUESTED_CONFIRM_DELAY_1M | $819.21 | 44.45% | $11,106.24 | 45.57% |
| REQUESTED_CONFIRM_DELAY_5M | $843.50 | 44.45% | $11,106.24 | 45.57% |
| REQUESTED_CONFIRM_DELAY_10M | $814.96 | 44.45% | $11,106.24 | 45.57% |
| RANDOM_OPPORTUNITY_REMOVAL_10PCT | $839.35 | 40.12% | $14,871.73 | 47.12% |
| MISSING_EXECUTION_QUOTES_1PCT | $812.39 | 44.71% | $10,917.02 | 45.28% |
| FULL_INITIAL_COST_X1_5 | $3,786.27 | 69.38% | $7,024.68 | 64.08% |
| FULL_INITIAL_COST_X2 | $2,314.50 | 78.16% | $2,344.54 | 83.13% |
| FULL_INITIAL_COST_X3 | $23.61 | 83.95% | $23.08 | 84.32% |
| FULL_INITIAL_DELAY_1M | $9,055.64 | 56.08% | $11,106.24 | 45.57% |
| FULL_INITIAL_DELAY_5M | $10,479.16 | 58.68% | $11,106.24 | 45.57% |
| FULL_INITIAL_DELAY_10M | $8,855.34 | 51.98% | $11,106.24 | 45.57% |

Bootstrap 500 draw blok 5 trade, expectancy CI dan Monte Carlo fixed-percent-return ordering tercantum di JSON. Ordering bukan full replay/resizing ulang. Missing 1% execution quote tetap memakai offline features; bukan simulasi seluruh feed failure. Removal 10% opportunity dapat membuka kesempatan berikutnya dan bukan sekadar mengurangi ledger profit.

### EURUSD stress

| Perturbasi | Kandidat akhir | DD kandidat | Baseline akhir | DD baseline |
|---|---:|---:|---:|---:|
| COST_X1_5 | $8,838.51 | 42.17% | $8,838.51 | 42.17% |
| COST_X2 | $4,304.15 | 44.06% | $4,304.15 | 44.06% |
| COST_X3 | $917.60 | 51.85% | $917.60 | 51.85% |
| CONFIRM_DELAY_1M | $11,820.23 | 37.08% | $11,820.23 | 37.08% |
| CONFIRM_DELAY_5M | $11,820.23 | 37.08% | $11,820.23 | 37.08% |
| CONFIRM_DELAY_10M | $11,820.23 | 37.08% | $11,820.23 | 37.08% |
| REQUESTED_DEEP_MORE_COST_X1.5 | $207.23 | 7.58% | $8,838.51 | 42.17% |
| REQUESTED_DEEP_MORE_COST_X2.0 | $197.36 | 7.81% | $4,304.15 | 44.06% |
| REQUESTED_DEEP_MORE_COST_X3.0 | $175.14 | 12.67% | $917.60 | 51.85% |
| REQUESTED_CONFIRM_DELAY_1M | $222.12 | 7.36% | $11,820.23 | 37.08% |
| REQUESTED_CONFIRM_DELAY_5M | $224.64 | 7.36% | $11,820.23 | 37.08% |
| REQUESTED_CONFIRM_DELAY_10M | $224.49 | 7.36% | $11,820.23 | 37.08% |
| RANDOM_OPPORTUNITY_REMOVAL_10PCT | $220.79 | 6.23% | $11,949.10 | 36.37% |
| MISSING_EXECUTION_QUOTES_1PCT | $221.66 | 7.36% | $11,820.23 | 37.08% |
| FULL_INITIAL_COST_X1_5 | $8,838.51 | 42.17% | $8,838.51 | 42.17% |
| FULL_INITIAL_COST_X2 | $4,304.15 | 44.06% | $4,304.15 | 44.06% |
| FULL_INITIAL_COST_X3 | $917.60 | 51.85% | $917.60 | 51.85% |
| FULL_INITIAL_DELAY_1M | $11,820.23 | 37.08% | $11,820.23 | 37.08% |
| FULL_INITIAL_DELAY_5M | $11,820.23 | 37.08% | $11,820.23 | 37.08% |
| FULL_INITIAL_DELAY_10M | $11,820.23 | 37.08% | $11,820.23 | 37.08% |

Bootstrap 500 draw blok 5 trade, expectancy CI dan Monte Carlo fixed-percent-return ordering tercantum di JSON. Ordering bukan full replay/resizing ulang. Missing 1% execution quote tetap memakai offline features; bukan simulasi seluruh feed failure. Removal 10% opportunity dapat membuka kesempatan berikutnya dan bukan sekadar mengurangi ledger profit.

Biaya tambahan juga memperlihatkan sensitivitas baseline frozen; hasil riset ini tidak membuktikan baseline kebal biaya atau layak live. Tidak ada peningkatan saldo stabil dari layering yang diuji.

## Pemeriksaan software dan status

- 2,167 test passed, 6 warning; tidak ada skipped/failed test pada pemeriksaan final.
- 27 safety/reversal tests baru; 34 dashboard/Streamlit smoke tests passed (juga tercakup dalam suite).
- Ruff lint, syntax compile dan import check passed.
- Kedua file engine frozen identik dengan HEAD/main awal; tidak ada config, scanner, dashboard, database atau broker code yang dimodifikasi.
- Baseline reconciliation, hash implementasi/input, serta semua 44 skenario risk/margin bounds passed.
- Runtime/Turso/broker connectivity tidak diperiksa ulang untuk riset offline ini. Tidak ada deployment, live order atau perubahan demo execution.

**PRODUCTION STATUS: RESEARCH ONLY — LAYERING TIDAK DIPROMOSIKAN.**

Kode dan hasil disimpan pada branch `research/distributed-reversal-layering`, base main `d082675060c1871516dde88a56ed6009dd67a5bd`. Metodologi reproduksi: `research/reports/FROZEN_LAYERING_REPLAY.md`.

## Provenance arsip

- EUR raw archive: `RIZAN_CROSS_ASSET_DATA_2016_2025.zip`, Library file `libfile_36dccec8e138819195d815f9a12da6cd`.
- XAU checkpoint: `RIZAN_XAUUSD_Pencarian10Tahun_Checkpoint_20261009.zip`, `libfile_7783af1e1d148191aca0c787cb497982`, version 2.
- XAU independent proof: `RIZAN_XAUUSD_DD50_BuySell_Bukti_20261009.zip`, `libfile_badc958c963c8191bafcee36edb94e8e`.
- XAU original ledger: `RIZAN_XAUUSD_DD50_BuySell_Ledger_20261009.csv`, `libfile_eda020c7b8888191b297cbe65f72323d`.
- XAU original result: `RIZAN_XAUUSD_DD50_BuySell_Hasil_20261009.json`, `libfile_7bed808297f0819180951ffade155d1f`.

Bukti eksperimen melampirkan kode, JSON penuh, test log, input sinyal/calendar/macro kecil dan hash arsip; raw harga lengkap tetap berada di arsip sumber di atas.
