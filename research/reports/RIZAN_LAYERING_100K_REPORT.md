# RIZAN — 100.000 KONFIGURASI LAYERING PER INSTRUMEN

**Kesimpulan: ada perbaikan historis kecil, tetapi belum robust. Status RESEARCH ONLY; baseline frozen production dipertahankan.**

Scope: hanya setup XAU BUY/SELL DD50 dan EUR DD37 yang sudah dibekukan. Modal $100 sekali untuk replay 2016–2025, dikompaun tanpa deposit. Sinyal, SL/TP awal, holding expiry, daily macro/news gate yang memang sudah menjadi bagian XAU, virtual EUR feedback, serta batas native risk/margin dipertahankan. Tidak melanjutkan penelitian lead–lag atau membuat keluarga sinyal pengganti.

100.000 kombinasi parameter berbeda diuji untuk XAU dan grid yang sama untuk EUR: **200.000 account replay** plus baseline. Semua memakai mark equity M1, integer child sizing dan biaya frozen; bukan screening dengan closed-DD saja. Caching hanya menyimpan jadwal fill kausal dan koefisien quote M1 agar tidak menghitung fitur berulang.

## Perbandingan utama — kandidat seluruh sejarah, bukan pilihan production

| Instrumen / mode | Saldo akhir | PF | DD M1 | WR | Setup | Setup/bulan |
|---|---:|---:|---:|---:|---:|---:|
| XAUUSD baseline | $11,106.24 | 1.892 | 45.57% | 37.14% | 560 | 4.67 |
| XAUUSD kandidat historis terbaik | $11,623.67 | 1.887 | 44.69% | 37.14% | 560 | 4.67 |
| EURUSD baseline | $11,820.23 | 2.211 | 37.08% | 52.94% | 204 | 1.70 |
| EURUSD kandidat historis terbaik | $11,847.49 | 2.388 | 35.15% | 54.90% | 204 | 1.70 |

XAU: +$517.43 (+4.66%) saldo akhir, DD turun 0.87 poin persentase, PF sedikit lebih rendah. EUR: +$27.27 (+0.23%) saldo akhir, DD turun 1.92 poin persentase, PF lebih tinggi. Ini hasil winner yang dipilih setelah melihat keseluruhan 2016–2025; tidak boleh dibaca sebagai alpha yang sudah lolos OOS.

## Ruang pencarian

1.000 jadwal fill × 100 sizing policies. Jadwal: deepest stage 0.15–0.90R (10 nilai), 2–6 tahap, limit atau konfirmasi reversal completed H1/M15/M5, dan TTL 15/30/45/60/90/120/150/180/210/240 menit. Sizing: initial fraction 20/40/60/80/100% child count baseline, bobot kedalaman power 0/0.5/1/1.5/2, budget planned USD baseline atau plafon frozen; optional degear menjadi setengah budget saat CLOSED-equity DD mencapai 10%.

Konfirmasi menggunakan candle M15 selesai yang menembus candle sebelumnya, ditambah M5 selesai dan bias H1 diizinkan (strict M15 untuk XAU). Ini definisi candle-break yang diuji, bukan klaim semua structural reversal terdeteksi. Tahap dicoba maksimal satu kali per konfirmasi baru, termasuk percobaan yang tidak mendapat ukuran lot. BUY ditambah lebih rendah, SELL dicerminkan. Fill market memakai quote saat konfirmasi; harga lembah sebelumnya tidak dipakai sebagai entry retrospektif.

SL/TP absolut sama untuk semua child dalam basket. Invalidating open, time expiry dan gap liquidation membatalkan tambahan. STOP_FIRST dan penanganan limit/TP intrabar ambigu konservatif. Total planned risk tetap maksimal XAU 12.5% / margin 50%, EUR 27.25% dengan multiplier frozen / margin 60% dan hard child cap. Carry dan gap dapat membuat realized loss berbeda dari planned SL risk. Mode plafon frozen boleh menggunakan kapasitas yang sebelumnya belum terpakai, sehingga exposure aktual tidak selalu sama dengan baseline. Optional degear hanya mengurangi plafon.

## Banyak parameter bukan banyak alpha independen

- XAUUSD: 1716 parameter memenuhi filter train; 192 parameter memenuhi saldo↑ dan DD↓ pada seluruh sejarah, mewakili 52 rangkuman prefix tahunan berbeda.
- EURUSD: 145 parameter memenuhi filter train; 150 parameter memenuhi saldo↑ dan DD↓ pada seluruh sejarah, mewakili 8 rangkuman prefix tahunan berbeda.

Lot minimum, rounding dan konfirmasi yang jarang menyebabkan banyak konfigurasi berbagi hasil. Jumlah di atas bukan jumlah bukti statistik independen. Seluruh 100.000 baris metrik dan prefix tahunan tersedia dalam matriks NPZ, dengan hash pada manifest.

## Kandidat diagnostik dan ranking seluruh sejarah

### XAUUSD kandidat #57390

Konfigurasi: 5 tahap; deepest 0.566667R; konfirmasi reversal; TTL 60 menit; posisi awal 100% child count baseline; weight power 1.0; budget FROZEN_RISK_CAP; degear False.

11 setup menerima tambahan; 2740 native child total; long/short 402/158; peak planned risk 12.49%; peak margin 44.68%.

| Rank | ID | Saldo akhir | DD M1 | PF | Train saldo 2016–2024 |
|---|---:|---:|---:|---:|---:|
| 1 | 57490 | $11,623.67 | 44.69% | 1.887 | $545.37 |
| 2 | 67490 | $11,623.65 | 44.70% | 1.887 | $545.35 |
| 3 | 37098 | $11,566.65 | 44.93% | 1.903 | $548.56 |
| 4 | 17098 | $11,566.64 | 44.93% | 1.903 | $548.55 |
| 5 | 49090 | $11,566.07 | 45.28% | 1.903 | $547.98 |
| 6 | 77094 | $11,565.72 | 45.28% | 1.903 | $547.63 |
| 7 | 19090 | $11,565.41 | 45.28% | 1.897 | $545.29 |
| 8 | 72068 | $11,539.15 | 44.45% | 1.977 | $705.79 |
| 9 | 72072 | $11,507.96 | 44.45% | 1.976 | $707.39 |
| 10 | 9894 | $11,493.59 | 44.07% | 1.898 | $548.08 |

### EURUSD kandidat #12946

Konfigurasi: 3 tahap; deepest 0.233333R; limit berpencar; TTL 240 menit; posisi awal 60% child count baseline; weight power 0.5; budget FROZEN_RISK_CAP; degear False.

181 setup menerima tambahan; 18942 native child total; long/short 114/90; peak planned risk 23.31%; peak margin 59.81%.

| Rank | ID | Saldo akhir | DD M1 | PF | Train saldo 2016–2024 |
|---|---:|---:|---:|---:|---:|
| 1 | 12946 | $11,847.49 | 35.15% | 2.388 | $6,811.69 |
| 2 | 12554 | $11,846.45 | 34.74% | 2.448 | $6,701.84 |
| 3 | 12942 | $11,840.57 | 35.18% | 2.388 | $6,804.76 |
| 4 | 12558 | $11,833.92 | 34.55% | 2.447 | $6,689.32 |
| 5 | 80998 | $11,827.10 | 37.03% | 2.212 | $6,933.90 |
| 6 | 70898 | $11,826.67 | 37.03% | 2.212 | $6,933.46 |
| 7 | 12950 | $11,825.73 | 35.18% | 2.389 | $6,788.91 |
| 8 | 90582 | $11,824.65 | 37.08% | 2.212 | $6,931.44 |

Ranking tersebut posthoc/diagnostik. Kandidat yang tidak memenuhi dua tujuan tidak dihilangkan dari matriks; seluruh grid termasuk yang gagal tetap disimpan.

## Walk-forward dan validasi temporal

Seleksi train: saldo 2016–tahun sebelumnya lebih tinggi dan DD M1 lebih rendah dari baseline, PF minimal 95% dan setup minimal 75% baseline; urutkan DD terkecil lalu saldo train terbesar. Rangkuman prefix identik didedup. Validation memakai saldo baseline yang diketahui di awal tahun, sama untuk kandidat dan baseline. Fold adalah percobaan tahun terpisah dengan state cash/peak baru; bukan portfolio switching curve yang disambung. Fitur dan virtual signal history tetap frozen.

Sejarah ini sudah terlihat dan baseline pernah dioptimasi pada periode yang sama. Karena itu 2025 merupakan retrospective temporal validation, **bukan fresh/blinded OOS**. Tidak ada klaim signifikansi yang dikoreksi untuk seluruh 100.000 percobaan.

### XAUUSD train-selected validation

| Tahun | ID dari train | Modal awal bersama | Kandidat akhir | Baseline akhir | DD kandidat | DD baseline |
|---|---:|---:|---:|---:|---:|---:|
| 2019 | 1102 | $131.44 | $207.74 | $192.06 | 24.21% | 21.47% |
| 2020 | 23119 | $192.06 | $208.05 | $180.74 | 26.70% | 37.32% |
| 2021 | 23119 | $180.74 | $262.99 | $293.88 | 17.43% | 25.91% |
| 2022 | 23179 | $293.88 | $312.66 | $322.60 | 20.30% | 34.75% |
| 2023 | 23119 | $322.60 | $318.94 | $333.28 | 17.00% | 34.29% |
| 2024 | 23119 | $333.28 | $409.39 | $508.20 | 15.31% | 45.57% |
| 2025 | 23278 | $508.20 | $6,085.26 | $11,106.24 | 33.53% | 41.73% |

Shortlist dipilih dari train: 50 kandidat; 4 memenuhi kedua tujuan pada test 2025. Memilih lagi berdasarkan test ini akan menjadi data snooping; hasil ini hanya diagnostik.

### EURUSD train-selected validation

| Tahun | ID dari train | Modal awal bersama | Kandidat akhir | Baseline akhir | DD kandidat | DD baseline |
|---|---:|---:|---:|---:|---:|---:|
| 2019 | 96630 | $158.58 | $305.41 | $433.69 | 18.80% | 21.30% |
| 2020 | 100000 | $433.69 | $815.70 | $815.70 | 18.66% | 18.66% |
| 2021 | 100000 | $815.70 | $981.53 | $981.53 | 30.08% | 30.08% |
| 2022 | 100000 | $981.53 | $3,158.75 | $3,158.75 | 35.34% | 35.34% |
| 2023 | 100000 | $3,158.75 | $5,081.37 | $5,081.37 | 31.42% | 31.42% |
| 2024 | 100000 | $5,081.37 | $6,927.02 | $6,927.02 | 20.79% | 20.79% |
| 2025 | 80582 | $6,927.02 | $11,820.23 | $11,820.23 | 18.98% | 18.98% |

Shortlist dipilih dari train: 3 kandidat; 0 memenuhi kedua tujuan pada test 2025. Memilih lagi berdasarkan test ini akan menjadi data snooping; hasil ini hanya diagnostik.

Pada XAU pilihan train utama menghasilkan saldo test 2025 $6,085.26 vs $11,106.24, meski DD turun. Kandidat XAU terbaik seluruh sejarah juga menghasilkan $11,095.13 pada test dengan modal awal sama vs $11,106.24 baseline. Empat konfigurasi shortlist yang tampak lolos 2025 hanya memberi tambahan sekitar $0.14–$0.56. Pada EUR pilihan train utama sama dengan baseline pada 2025, tanpa tambahan layer; nol shortlist mengalahkan kedua tujuan pada tahun test.

## Bootstrap, biaya, delay dan robustness

### XAUUSD

Paired return difference CI 95% per setup: [-0.0893, 0.1434] poin persentase, 560 matched setups. Keduanya mencakup nol. Bootstrap 500 draw blok 5 trade; CI eksploratif setelah pencarian, tanpa koreksi multiple-testing. Monte Carlo 500 permutasi fixed historical percentage returns dan percentile DD ada dalam JSON; ini bukan full re-sizing under reordered trades.

| Perturbasi | Diagnostik akhir | Baseline akhir | DD diagnostik | DD baseline |
|---|---:|---:|---:|---:|
| COST_X1_5 | $6,251.13 | $7,024.68 | 62.27% | 64.08% |
| COST_X2 | $2,766.52 | $2,344.54 | 80.73% | 83.13% |
| COST_X3 | $23.08 | $23.08 | 84.32% | 84.32% |
| CONFIRM_DELAY_1M | $11,458.74 | $11,106.24 | 46.28% | 45.57% |
| CONFIRM_DELAY_5M | $11,045.02 | $11,106.24 | 51.22% | 45.57% |
| CONFIRM_DELAY_10M | $10,810.25 | $11,106.24 | 45.94% | 45.57% |
| EXECUTION_QUOTE_DROP_1PCT | $11,488.68 | $11,101.32 | 44.69% | 45.58% |
| OPPORTUNITY_DROP_10PCT | $10,642.32 | $10,936.40 | 52.93% | 52.66% |

| Neighbor ID | Saldo akhir | DD M1 |
|---|---:|---:|
| 47390 | $11,458.67 | 45.82% |
| 67390 | $11,623.65 | 44.70% |
| 55390 | $10,052.81 | 47.09% |
| 59390 | $11,025.56 | 46.29% |
| 57290 | $11,458.89 | 44.05% |
| 57490 | $11,623.67 | 44.69% |
| 57370 | $5,076.34 | 44.69% |
| 57386 | $11,456.46 | 45.46% |
| 57394 | $11,025.21 | 46.31% |

Neighbor mengubah satu dimensi grid; tidak dipakai untuk memilih ulang winner. Test delay tidak berpengaruh pada limit yang tidak menunggu konfirmasi. Quote removal mempertahankan offline feature/confirmation dan hanya menghapus execution quote, bukan mensimulasikan seluruh feed/bridge outage. Opportunity removal dapat membuka signal berikutnya; bukan hanya menghapus ledger profit.

### EURUSD

Paired return difference CI 95% per setup: [-0.4225, 0.1965] poin persentase, 204 matched setups. Keduanya mencakup nol. Bootstrap 500 draw blok 5 trade; CI eksploratif setelah pencarian, tanpa koreksi multiple-testing. Monte Carlo 500 permutasi fixed historical percentage returns dan percentile DD ada dalam JSON; ini bukan full re-sizing under reordered trades.

| Perturbasi | Diagnostik akhir | Baseline akhir | DD diagnostik | DD baseline |
|---|---:|---:|---:|---:|
| COST_X1_5 | $8,588.33 | $8,838.51 | 39.35% | 42.17% |
| COST_X2 | $4,420.41 | $4,304.15 | 41.27% | 44.06% |
| COST_X3 | $966.32 | $917.60 | 48.01% | 51.85% |
| CONFIRM_DELAY_1M | $11,847.49 | $11,820.23 | 35.15% | 37.08% |
| CONFIRM_DELAY_5M | $11,847.49 | $11,820.23 | 35.15% | 37.08% |
| CONFIRM_DELAY_10M | $11,847.49 | $11,820.23 | 35.15% | 37.08% |
| EXECUTION_QUOTE_DROP_1PCT | $11,639.68 | $11,824.67 | 35.45% | 37.06% |
| OPPORTUNITY_DROP_10PCT | $10,717.72 | $10,669.81 | 36.22% | 39.05% |

| Neighbor ID | Saldo akhir | DD M1 |
|---|---:|---:|
| 2946 | $10,531.21 | 38.73% |
| 22946 | $11,063.85 | 35.11% |
| 10946 | $9,490.96 | 34.52% |
| 14946 | $10,773.98 | 38.32% |
| 12846 | $11,402.17 | 35.82% |
| 12926 | $11,386.18 | 34.79% |
| 12966 | $11,766.01 | 36.26% |
| 12942 | $11,840.57 | 35.18% |
| 12950 | $11,825.73 | 35.18% |

Neighbor mengubah satu dimensi grid; tidak dipakai untuk memilih ulang winner. Test delay tidak berpengaruh pada limit yang tidak menunggu konfirmasi. Quote removal mempertahankan offline feature/confirmation dan hanya menghapus execution quote, bukan mensimulasikan seluruh feed/bridge outage. Opportunity removal dapat membuka signal berikutnya; bukan hanya menghapus ledger profit.

Keunggulan gabungan tidak stabil: XAU biaya ×1.5 menurunkan saldo kandidat menjadi $6,251.13 vs $7,024.68 dan delay 5 menit menaikkan DD kandidat ke 51.22%. EUR biaya ×1.5 menghasilkan $8,588.33 vs $8,838.51; missing execution quote juga menghapus keunggulan saldo. Beberapa stress lain tetap lebih baik; tidak menyatakan semuanya gagal. Kriteria saldo lebih tinggi dan DD lebih rendah **secara konsisten** belum terpenuhi.

## Validitas software/data dan status

- Baseline XAU dan EUR direkonsiliasi tepat untuk saldo akhir, PF, jumlah setup dan DD.
- Lima konfigurasi per simbol dicocokkan dengan scalar accounting independen, position-by-position, untuk 12 metrik; seluruhnya cocok.
- 200.000 konfigurasi memiliki matriks finite dan mematuhi planned risk/margin ceilings frozen.
- 2,178 test passed, 6 warning; tidak ada failed/skipped pada lingkungan riset final. Ini mencakup dashboard smoke dan engine regression.
- Ruff lint, syntax compile dan import passed; dua regression baru memastikan pending limit tidak terisi pada gap/time liquidation.
- Numba hanya dependency riset optional, tidak ditambahkan ke production runtime. Default CI dapat skip test Numba bila dependency riset tidak dipasang; run final ini memasangnya dan menjalankan semua test.
- Kedua file frozen engine tidak berubah. Tidak ada scanner/dashboard/DB/bridge registration atau live order.
- Runtime/Turso/broker connectivity tidak diperiksa ulang untuk riset offline ini; tidak ada deployment.

**PRODUCTION STATUS: RESEARCH ONLY. Baseline frozen dipertahankan.**

Semua biaya adalah asumsi synthetic frozen, leverage referensi 100, bukan actual historical FP Markets ASK/fill. XAU daily macro menggunakan final revised values dan publication-lag proxy, bukan point-in-time vintages. Missing bars tidak diinterpolasi. DD M1 bukan exact tick equity DD. Baseline XAU sendiri sangat bergantung pada laba 2025; pengujian ini tidak membuktikan baseline layak live.

Kode/metode: `research/reports/LAYERING_100K_REPRODUCE.md`. Base branch riset sebelumnya: `6d527ead99b7be47833299d3a91529ad8d934ba3`. New branch: `research/layering-100k`. Matriks NPZ lengkap dan kode/check logs tersimpan dalam `RIZAN_LAYERING_100K_EVIDENCE.zip`; plot seluruh grid dalam `RIZAN_LAYERING_100K_PARETO.png`.

Sumber tetap arsip sebelumnya: `RIZAN_CROSS_ASSET_DATA_2016_2025.zip` (EUR saja), `RIZAN_XAUUSD_Pencarian10Tahun_Checkpoint_20261009.zip` version 2, dan frozen signal/audit inputs dari `RIZAN_FROZEN_LAYERING_EVIDENCE.zip`. Hash per input terdapat pada result JSON.
