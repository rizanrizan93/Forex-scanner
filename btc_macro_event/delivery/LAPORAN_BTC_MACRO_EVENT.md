# Uji BTC Macro dan Event — 20 Oktober 2026

Konfigurasi entry, SL/TP, risiko, leverage dan weekend tetap. Hanya kelayakan entry BTC berubah. XAU/EUR tidak diubah. Modal $100 tanpa top-up, 2019–9 Oktober 2026. Delapan replay aktual: 4 varian × 2 lintasan OHLC.

| Varian | Saldo akhir | Floating DD | PF | Basket BTC BUY/SELL | Net BTC |
|---|---:|---:|---:|---:|---:|
| BASE_PATH_A | $14,168,707.28 | 62.95% | 2.447 | 41/55 | $580,360.40 |
| BASE_PATH_B | $18,043,274.23 | 63.78% | 2.399 | 40/55 | $1,372,484.86 |
| MACRO_PATH_A | $9,171,084.22 | 63.32% | 2.283 | 27/41 | $-21,048.18 |
| MACRO_PATH_B | $13,826,273.67 | 64.46% | 2.378 | 27/41 | $112,839.68 |
| EVENT_PATH_A | $14,079,654.97 | 62.95% | 2.427 | 36/51 | $441,013.23 |
| EVENT_PATH_B | $17,589,698.43 | 63.78% | 2.380 | 36/51 | $1,230,507.07 |
| BOTH_PATH_A | $5,791,510.64 | 63.32% | 2.024 | 24/38 | $-70,635.02 |
| BOTH_PATH_B | $15,472,497.73 | 64.46% | 2.406 | 24/38 | $286,814.53 |

## Perubahan terhadap baseline

| Varian | Perubahan saldo Path A | Perubahan saldo Path B | Perubahan DD A/B (poin persentase) |
|---|---:|---:|---:|
| MACRO | -35.27% | -23.37% | +0.372 / +0.684 |
| EVENT | -0.63% | -2.51% | +0.000 / +0.000 |
| BOTH | -59.12% | -14.25% | +0.372 / +0.684 |

Keputusan: tetap pertahankan baseline frozen. Peningkatan pada satu lintasan saja bukan bukti ketahanan; data makro current-vintage tetap memerlukan validasi point-in-time sebelum pertimbangan penerapan.


## Aturan terkunci

BASE: tanpa filter tambahan. MACRO: BUY hanya jika perubahan yield riil DFII10 selama 20 observasi terakhir <=0; SELL >=0. Observasi tersedia setelah lag dua hari kerja federal AS, batas stale 10 hari. EVENT: tidak entry dari 1 menit setelah pengumuman suku bunga FOMC sampai 24 jam sesudahnya. BOTH: kedua syarat. Filter tidak menutup posisi yang sudah ada. Tidak memakai surprise, hasil rapat, kalender kejadian mendadak sebelum publikasi, atau kalender hasil PnL.

## Interpretasi

Hasil ini eksperimen awal dari aturan tetap, bukan pencarian threshold terbaik. Bandingkan saldo dan DD kedua path, serta kontribusi BTC; perubahan saldo portfolio juga melibatkan compounding dan peluang XAU/EUR yang bergeser. PnL BTC yang ditampilkan berasal dari akun gabungan, bukan hasil BTC standalone. Semua periode sudah pernah dipakai memilih strategi BTC asli, sehingga bukan out-of-sample murni.

## Batas validasi

DFII10 berasal dari historical current-vintage FRED, bukan ALFRED point-in-time. Lag mencegah akses observasi hari yang sama, tetapi tidak membuktikan bebas revisi atau seluruh keterlambatan publikasi. Filter ini belum layak dipromosikan atas dasar hasil historis saja. Event hanya 63 keputusan suku bunga FOMC reguler dan dua pemotongan darurat 2020; belum CPI/NFP dan bukan seluruh pernyataan Fed. Kalender DST menggunakan America/New_York. XAU masih menggunakan adapter macro rekonstruksi lama yang belum tersertifikasi. Dua lintasan harga adalah diagnostik OHLC, bukan tick broker atau batas konservatif seluruh lintasan M1. Jadwal BTC replay asumsi Senin00–Jumat22UTC; native memakai MarketHours. Biaya dasar saja, belum stress filter baru. Frozen V1.2.1 dan live tidak diubah.

## Audit

Baseline kedua path wajib identik seluruh fill ledger dengan artefak frozen sebelumnya. Semua saldo direkonsiliasi dari gross PnL + komisi + swap; balance DD dihitung ulang dari cash events. Semua posisi BTC diperiksa terhadap weekend dan cutoff Jumat21:30UTC. Hash source strategi harus sama dengan frozen manifest. Lihat AUDIT.json, data checksums PROTOCOL.json, SIGNAL_ELIGIBILITY.csv, FILL_LEDGER.csv, ANNUAL.csv dan MONTHLY.csv.
