# XAU: breakout gagal dengan trailing stop

25 Oktober 2026. **Status: BELUM LOLOS; tidak diterapkan ke dashboard atau cBot.**

Metode BUY dan SELL telah diuji tanpa TP tetap. Dua tahap mengevaluasi 25.344
konfigurasi, mencakup 21.504 kombinasi unik (tahap kedua mengulang kontrol tahap
pertama). Tidak ada yang memenuhi seluruh kriteria latihan yang ditetapkan.
Ini tidak membuktikan semua strategi reversal atau trailing pasti gagal.

## Metode dan exit

Level yang sudah diketahui: high/low hari UTC sebelumnya atau minggu UTC
sebelumnya. Sweep harus kembali menutup di dalam level dalam 1/3 candle M5/M15.
Bandingkan pemicu reclaim langsung dengan close menembus struktur tiga candle
sebelum sweep. Entry pada open M1 berikutnya atau retest pertama dalam 60 menit.
SL awal di luar ekstrem sweep dengan buffer 0,1 ATR timeframe sinyal; maksimum
jarak risiko harga 10/15/20 dolar, minimum 1 dolar. Semua sinyal memakai candle
yang sudah selesai; level bukan pivot yang baru dapat diketahui di masa depan.

Tidak ada fixed TP. SL awal tetap aktif, trailing hanya memperketat stop.
Jarak diuji:5/10/15 dolar,1/2 ATR H1 yang sudah diketahui saat sinyal, atau
0,75/1,5/2,5 kali risiko awal. Pemicu diuji: langsung, setelah 5/10/25 dolar,
atau 0,5/1/2 kali risiko awal. ATR distance dibekukan saat sinyal; level stop
mengikuti ekstrem harga yang sudah teramati. Maksimum hold 24/72 jam adalah
time exit, bukan target profit. Satu posisi FIFO, tanpa compounding/layer.

Trailing dihitung setelah candle M1 selesai dan baru berlaku pada candle
berikutnya. Stop lama diperiksa terlebih dahulu, gap merugikan dibebankan.
Fill limit tidak diberi kredit pergerakan menguntungkan pada menit fill,
karena urutan high/low tidak diketahui. Metode ini tidak mengklaim hasil tick.

## Pemilihan dan hasil

Kandidat diurutkan berdasarkan PF sisi BUY/SELL yang lebih lemah pada 2019–2022,
kemudian PF total dan sampel. Ada batas minimum sampel dan kriteriaPF/win rate;
karena tidak ada yang lolos, kandidat berikut hanyalah pembanding deskriptif.
Ranking dibekukan sebelum evaluasi 2023–2025, tanpa menggantinya dengan kandidat
yang kebetulan menang di review. Tahap kedua eksploratif ditambahkan setelah
melihat kegagalan tahap pertama. Seluruh data pernah diamati sebelumnya.

PF_R adalah rasio total profit/loss dalam satuan risiko awal masing-masing
transaksi. PF lot tetap menggunakan profit/loss dolar per ons dengan eksposur
ons sama. Keduanya sesudah asumsi biaya; tidak ada simulasi ekuitas akun.

| Tahap / periode | Transaksi | Win rate | PF_R | PF lot tetap | Bersih R |
|---|---:|---:|---:|---:|---:|
| Tahap 1 latihan 2019–2022 |135|34,81%|1,387|1,506|+35,07|
| Tahap 1 review 2023–2025 |83|22,89%|0,667|0,663|−21,38|
| Tahap 2 latihan 2019–2022 |123|34,15%|1,404|1,581|+33,99|
| Tahap 2 review 2023–2025 |71|23,94%|0,857|0,974|−7,87|

Pembanding tahap 2: high/low minggu sebelumnya, M15, reclaim 1 candle, konfirmasi
struktur; entry market pada open M1 berikutnya. SL struktural maksimal 10 dolar,
rata-rata 4,91 dolar pada review. Trailing aktif setelah gerak menguntungkan 25 dolar,
jarak 2,5 R awal, maksimum hold 24 jam, tanpa filter arah harian. Ini adalah pilihan
aturan ranking latihan dari ruang uji yang diperluas, bukan rekomendasi.

| Pembanding tahap 2, review 2023–2025 | Transaksi | Win rate | PF_R | PF lot tetap |
|---|---:|---:|---:|---:|
| BUY |26|42,31%|1,548|1,852|
| SELL |45|13,33%|0,578|0,640|
| Gabungan |71|23,94%|0,857|0,974|
| Kondisi bearish harian, kedua arah |18|33,33%|0,890|0,803|

Regime bearish: close harian terakhir di bawah EMA20 dan EMA20 di bawah
nilainya lima candle harian sebelumnya. Bullish kebalikannya; sisanya sideways.
Penentuan regime menggunakan informasi yang tersedia saat sinyal.

Pada 71 transaksi review tahap 2, hanya 2 keluar dengan profit bersih sedikitnya
25 dolar/ons; perhitungan MFE konservatif juga hanya mencatat 2 mencapai 25 dolar.
MFE mengabaikan excursion menguntungkan pada bar stop yang urutannya ambigu.
Terdapat 10 kerugian beruntun pada urutan gabungan dan drawdown 22,43 R. Ini bukan
persentase drawdown akun. Q1 2026 tidak menghasilkan transaksi pada konfigurasi
beku tahap 2, sehingga kinerja periode tersebut tidak dapat dinilai.

| Sensitivitas tahap 2, review | Transaksi | PF_R | PF lot tetap |
|---|---:|---:|---:|
| Biaya dasar |71|0,857|0,974|
| Biaya dua kali |71|0,717|0,822|
| Publikasi terlambat 60 detik |72|0,790|0,907|
| Publikasi terlambat 300 detik |66|0,709|0,705|

Untuk entry market, delay mengubah harga dan kelayakan entry; jumlah transaksi
bisa bertambah atau berkurang. Untuk limit, first touch sebelum publikasi
dinyatakan terlewat permanen, tidak dialihkan ke retouch selanjutnya.

## Apa yang dipelajari

Dalam ruang uji ini, sweep/reclaim dan perubahan struktur kecil belum cukup
untuk menyaring reversal besar dua arah. SELL tetap menjadi kelemahan utama.
Trailing yang lebih cepat/adaptif juga tersedia dalam pencarian, tetapi tidak
menghasilkan konfigurasi yang memenuhi seluruh kriteria. Mengubah exit saja
belum mengatasi kelemahan entry pada metode ini. Hasil BUY terpisah yang positif
tidak digunakan untuk mempromosikan model dua arah yang gagal.

Riset selanjutnya perlu menguji informasi tambahan yang dapat membedakan
perubahan tren dari breakout yang hanya tertunda: misalnya perubahan reaksi
emas terhadap berita/yield/dolar dan data transaksi berarah yang benar. Klaim
macro/orderflow belum dapat diuji dalam run ini: arsip hanya menyediakan harga
dan spread proxy, tanpa data macro vintage intraday atau COMEX orderflow yang
terverifikasi. Pola harga tidak diperlakukan sebagai bukti aktivitas institusi.

## Data, biaya, dan verifikasi

2.557.244 BID M1 dari 1Januari 2019 hingga 31Maret 2026, SHA256:
`967a84f61e248143d1dd3d92db132e137441d30445a236827d9b6579593e262b`.
Asumsi ASK dari spread rata-rata menit; bukan arsip bid/ask tick FP Markets.
Fee/slippage proxy 0,17 dolar/ons ditambah carry merugikan 0,10 dolar/ons/hari,
bukan tarif swap broker. Cost 2 menggandakan spread serta fee/slippage.

Referensi harian memerlukan 500 observasi M1, mingguan 2000. Candle sinyal dan
tiga candle pendahulunya harus lengkap. Warmup 24.000 observasi setelah awal
data atau gap>72 jam, ditambah 40 observasi harian untuk regime. Transaksi yang
horizon maksimumnya melintasi gap>72 jam dikeluarkan secara retrospektif sebagai
penyaringan kualitas data; ini bukan fitur yang dapat diketahui saat live.
Embargo 72 jam sebelum batas tahun 2023/2026; horizon melewati akhir tape dibuang.
Periode 2023–2025 adalah review historis yang telah dilihat, bukan holdout baru.

Tujuh pemeriksaan adversarial lulus, termasuk stop sebelum high menguntungkan,
gap, ASK SELL, limit-fill sequencing, delay first touch, warmup gap, dan trailing
berbasisR. Rekonstruksi Python terpisah terhadap 219 transaksi tahap 1 dan 194 tahap 2
lulus: level historis, sweep/reclaim/struktur, SL awal, trailing, biaya, dan FIFO.
Selisih maksimum harga/PnL/MFE di bawah 7 e−13. Audit hanya merekonstruksi sinyal
yang diterima, bukan enumerasi independen penuh terhadap semua sinyal ditolak.
Tidak ada uji broker tick atau verifikasi aba-aba live.

## Reproduksi

Python dengan numpy, pandas dan numba; lingkungan penelitian ini menggunakan
numba 0.68.0. Jalankan dari root repository:

```bash
python3 docs/research/xau_failed_breakout_trailing_20261025/run_study.py /path/to/XAUUSD_m1.csv
python3 docs/research/xau_failed_breakout_trailing_20261025/run_study.py /path/to/XAUUSD_m1.csv --phase 2
python3 docs/research/xau_failed_breakout_trailing_20261025/test_engine.py
python3 docs/research/xau_failed_breakout_trailing_20261025/audit_independent.py /path/to/XAUUSD_m1.csv
python3 docs/research/xau_failed_breakout_trailing_20261025/audit_independent.py /path/to/XAUUSD_m1.csv --phase2
```

PROTOCOL.md memuat kriteria sebelum perhitungan masing-masing tahap.
FROZEN_CONFIG/RESULTS/LEDGER dan TOP10_REVIEW ada untuk masing-masing tahap.
TRAIN_GRIDS.zip memuat kedua CSV grid lengkap; tidak memuat arsip harga mentah.
Tidak ada kode runtime, workflow, bridge, order, atau cBot yang diubah.
