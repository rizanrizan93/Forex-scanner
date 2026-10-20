# RIZAN — L2 Heatmap + Zone Reversal Pilot

20 Oktober 2026 · ID `RZ-ZONE-L2-PILOT-20261020-V0.1`

**Status: prototipe riset selesai dan diuji; belum terbukti meningkatkan win rate secara konsisten atau menghasilkan expectancy positif setelah biaya.** Ini peta kedalaman pasar buatan sendiri untuk riset, bukan aplikasi Bookmap resmi. Akun, lisensi, atau terminal Bookmap pengguna belum dihubungkan. Tidak ada perubahan cBot beku, scanner produksi, bridge, atau order live.

## Yang benar-benar dikerjakan

- Membaca paket riset reversal terdahulu dari arsip aktual, tiga script simulasi, dan source repository.
- Mengunduh delapan ZIP order book asli Bybit BTCUSDT perpetual, 1–8 Januari 2024 UTC: **6.911.831 pesan**, total **2.096.153.499 byte** ZIP. Semua anggota dibaca sampai akhir sehingga pemeriksaan CRC ZIP dijalankan; SHA256 setiap ZIP tercatat di `DATA_AUDIT.json`.
- Merekonstruksi snapshot dan setiap delta sebelum sampling, termasuk penghapusan ukuran nol dan reset snapshot; memblokir data silang/stale dan regresi urutan. Tidak menggunakan OHLC untuk mengarang kedalaman pasar.
- Menghasilkan 691.200 grid detik. Ada 16 detik tanpa quote valid, dua pada awal setiap hari; tidak diisi secara sintetis. Regresi timestamp teramati nol. Dataset tidak disertifikasi sebagai rekaman semua paket exchange tanpa kehilangan.
- Membuat heatmap kuantitas limit yang terlihat, adapter filter zona, ledger kejadian, uji biaya, dan viewer replay lokal. Heatmap memakai snapshot tiap 30 detik dan bin harga $10; perhitungan kejadian menggunakan quote sampel 1 detik.

Sumber: [arsip historis Bybit](https://www.bybit.com/en/derivative-activity/history-data), [aturan resmi snapshot/delta](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook). URL berkas yang benar-benar dibaca ada di audit input. Percobaan akses `public.bybit.com` untuk transaksi menghasilkan HTML “Site Unavailable” meskipun HTTP 200. Tidak dihitung sebagai data transaksi. Karena tidak ada transaksi yang dapat dipakai, prototipe **tidak menghitung CVD, aggressive buy/sell, absorption, iceberg, atau spoofing**. Pembatalan order tidak dianggap transaksi.

## Hubungan dengan engine yang sudah ada

1. `repo_h1_m5`: menjalankan fungsi asli `closed_features`, `base_events`, dan `thin_events` dari `src/fx_scanner/reversal_zones.py`, byte-identik dengan commit `e357272fec03411a6e7c4d2397faf742d1a11047`. Dipilih satu geometri riset: H1 lookback 6, half-width 0,1 ATR, wick M5 minimal 0,3, dua arah, thinning 4 jam per arah. Zona H1 dias-of sebelum M5 dimulai, lalu konfirmasi M5 closed. Ini adaptasi pada quote BTC, bukan validasi strategi XAU.
2. `sweep_reclaim`: formula keluarga liquidity-sweep dari paket riset lama: M15, 16 candle sebelumnya, penetrasi >0, reclaim level, wick minimal 0,3; ATR rerata 56 TR sebelumnya. Jika sinyal berlawanan bersamaan, dibuang. SL ekstrem candle plus 0,1 ATR.
3. `exante_touch`: eksperimen baru untuk menguji pemetaan sebelum konfirmasi. High/low 16 candle M15 sebelumnya diumumkan saat candle berikutnya dibuka; ambil sentuhan pertama salah satu level dalam window tersebut. SL level minus arah × 0,75 ATR. Tidak menunggu reclaim atau mengetahui titik balik masa depan.

`zone_overlay.py` menerima zona yang sudah tersedia dan menambahkan bukti L2 tanpa memindahkan batasnya. Penjagaan venue/instrumen mencegah GC/CME disamakan langsung dengan XAUUSD/FP, atau BTCUSDT/Bybit dengan BTCUSD broker. File V225 supply/demand juga dibaca dan diarsipkan untuk audit, tetapi engine supply/demand V225 lengkap **belum** diuji ulang dengan L2 XAU. Integrasi yang benar-benar dijalankan adalah engine H1/M5 standalone di atas dan dua cohort pembanding.

Source upstream dan Git blob diverifikasi di `REPO_SOURCE_PROVENANCE.json`. Tidak ada pencarian ulang jutaan konfigurasi.

## Protokol, waktu, dan eksekusi

`LOCKED_CONFIG.json` dibuat sebelum outcome dihitung. `PROTOCOL_EXTENSION.json` menambah cohort sentuhan sebelum perhitungan outcome pertama. `REPO_ENGINE_PROTOCOL.json` ditambahkan setelah perhitungan awal dua cohort selesai, sebelum hasilnya diperiksa, saat source H1/M5 ditemukan dalam audit repository. Seluruh riset ini eksploratif; tiga hari berikut bukan holdout sertifikasi yang panjang atau independen dari seluruh riwayat riset.

- Jan 1 warmup; Jan 2–5 pengamatan development; Jan 6–8 holdout diagnostik kronologis. Engine H1/M5 menunggu ATR/EMA cukup sehingga sebagian awal periode belum menghasilkan sinyal.
- Masuk pada quote pertama minimal satu detik setelah event/konfirmasi, maksimal menunggu lima detik. BUY memakai ask dan SELL bid. Bukti L2 selalu bertimestamp lebih awal dari keputusan.
- TP 1R, hold maksimum **1.800 detik / 30 menit**, risk distance 0,15–4 ATR. Stop/target diamati pada quote executable sisi sebaliknya; sampel yang melewati level memakai quote aktual sampel, termasuk gap. Bukan jaminan fill intrasekon.
- Fee asumsi 5,5 bp per sisi, slippage debit 1 bp per sisi, financing model 3 bp notional/hari proporsional durasi. Ini asumsi eksperimen, bukan kutipan biaya FP Markets atau tarif historis Bybit yang tersertifikasi. Funding settlement aktual tidak direkonstruksi.
- Spread berasal dari bid/ask yang direkonstruksi. Stress 1,5× dan 2× hanya mengalikan fee/slippage/financing pada fill yang sama; spread tidak dikalikan. Ini stress debit biaya, bukan simulasi market impact dan perubahan fill.
- Semua kejadian boleh overlap agar perbandingan filter memakai cohort identik. Hasil R adalah event study, bukan return portfolio atau trade count cBot yang dapat dijumlahkan dengan bebas.

Filter dikunci: **imbalance** arah × (notional bid − ask)/(bid + ask) ≥0,2 dalam radius 5 bp dari mid; **persistent** sekurangnya 60% dari 60 detik sebelumnya memenuhi batas itu, dengan minimal 55 sampel valid; **both** memenuhi keduanya. Baseline menerima semua kejadian eligible. Ketiganya diuji dan dilaporkan; bukan memilih pemenang diam-diam.

Total **189 kandidat**: 181 outcome lengkap, 7 risk tidak sah, 1 tersensor karena quote gap. Bukti fitur valid untuk 189 kandidat. Ringkasan memakai hanya outcome lengkap dengan bukti valid, sehingga baseline dan filter dapat dibandingkan pada denominator yang sama. Ada overlap pada exante_touch (11 development, 15 holdout) dan sweep_reclaim (masing-masing 1); repo_h1_m5 tidak overlap. Detik yang hilang tidak dianggap win atau loss.

## Hasil holdout yang benar-benar dihitung

Win rate net = proporsi kejadian dengan P/L positif setelah seluruh debit model. Target-first adalah mencapai TP sebelum stop/horizon dan dibedakan dari win rate; timeout dapat untung atau rugi.

| Cohort | Filter | N | Win net % | Target-first % | Cakupan % | Mean net R | PF R |
| --- | --- | --- | --- | --- | --- | --- | --- |
| exante_touch | baseline | 57 | 50.877 | 50.877 | 100.000 | -0.617 | 0.219 |
| exante_touch | imbalance | 11 | 63.636 | 63.636 | 19.298 | -0.289 | 0.461 |
| repo_h1_m5 | baseline | 10 | 20.000 | 0.000 | 100.000 | -0.430 | 0.029 |
| repo_h1_m5 | imbalance | 2 | 0.000 | 0.000 | 20.000 | -0.297 | 0.000 |
| sweep_reclaim | baseline | 25 | 44.000 | 36.000 | 100.000 | -0.634 | 0.131 |
| sweep_reclaim | imbalance | 2 | 0.000 | 0.000 | 8.000 | -0.953 | 0.000 |

Pada exante_touch, imbalance menerima 11 dari 57 kejadian (19,3%), dengan 7 win dan 4 loss net. Win rate naik dari 50,9% menjadi 63,6%, tetapi mean **−0,289R** dan PF **0,461** masih merugi. Mean gross kelompok ini +0,320R, sedangkan mean debit biaya 0,610R; selisihnya menjelaskan hasil net negatif secara langsung dari ledger. Empat dari 11 kejadian tidak untung setelah biaya. Ini bukan bukti strategi sudah berhasil.

Hasil development justru berlawanan: win exante_touch baseline 46,4% (56 kejadian), filter imbalance 37,5% (8 kejadian). Interval Wilson win filtered holdout kira-kira 35,4–84,8%; itu hanya ukuran ketidakpastian deskriptif dan asumsi independennya terganggu oleh overlap. Hasil belum stabil.

Pada engine H1/M5 repository, baseline holdout 2/10 win, filter 0/2. Pada sweep/reclaim, baseline 11/25 win, filter 0/2. Angka kecil ini tidak membuktikan engine tidak mungkin diperbaiki; ia menunjukkan filter yang diuji belum memberikan bukti peningkatan. H1/M5 juga mempunyai 8 timeout dan nol target-first dalam horizon 30 menit, sehingga hasil harus dibaca bersama horizon baru ini.

Filter persistent dan both menerima nol exante_touch dan nol H1/M5 holdout; masing-masing hanya satu sweep/reclaim holdout yang rugi. **Tidak trading bukan win rate 100%.** Semua kombinasi development/holdout dan biaya tersedia di `COMPARISON.csv`.

## Stress biaya

| Filter exante holdout | Biaya × | N | Win net % | Mean net R | PF R |
| --- | --- | --- | --- | --- | --- |
| baseline | 1.000 | 57 | 50.877 | -0.617 | 0.219 |
| baseline | 1.500 | 57 | 21.053 | -0.954 | 0.048 |
| baseline | 2.000 | 57 | 8.772 | -1.290 | 0.008 |
| imbalance | 1.000 | 11 | 63.636 | -0.289 | 0.461 |
| imbalance | 1.500 | 11 | 27.273 | -0.594 | 0.124 |
| imbalance | 2.000 | 11 | 18.182 | -0.899 | 0.032 |

Perhitungan biaya normal, 1,5× dan 2× sudah dijalankan untuk seluruh cohort/filter. Tidak ada simulasi leverage atau compounding portfolio pada studi ini. Stress ini tidak boleh dipindahkan sebagai hasil stress cBot beku.

## Temuan audit durasi riset terdahulu

`run_research.py::sim_one` mengalikan argumen holding dengan 60 detik. `second_pass.py` menamainya `hold_h` dan memberikan 12 atau 24, sehingga uji tersebut menggunakan deadline menit, bukan jam. Reproduksi fungsi asli tanpa decorator Numba menunjukkan timeout pada open menit ke-13 dan ke-25 (quote berikut setelah deadline). Hasil lama tidak diubah atau dihitung ulang dalam proyek ini. `exante_level_research.py` menggunakan ×3.600 detik sehingga temuan ini tidak boleh digeneralisasi ke seluruh file. Lihat `UPSTREAM_HORIZON_AUDIT.json`. Studi baru menyatakan horizon 1.800 detik secara eksplisit.

## Batas kesimpulan dan jalur XAU/EUR

Data ini BTCUSDT perpetual Bybit Januari 2024, bukan BTCUSD broker dan bukan XAUUSD/EURUSD. Quote satu detik bisa melewatkan urutan intrasekon. Timestamp arsip adalah publikasi exchange, bukan arrival terminal; delay satu detik adalah asumsi. Tidak ada validasi limit queue, iceberg/MBO, biaya aktual tier, funding settlement, latensi terminal, atau transfer venue. Heatmap menunjukkan likuiditas yang dipasang dan bisa dibatalkan; ia tidak menjamin harga akan berbalik.

Untuk XAU/EUR, M1/tick lama tidak mengandung order book historis. Perlu rekaman L2 broker yang relevan, atau GC dan 6E futures sebagai **proxy terpisah** dengan basis, roll, kontrak, sesi dan sinkronisasi waktu yang diaudit. [CME menyediakan market-depth/MBO historis](https://www.cmegroup.com/market-data/real-time-and-historical-data.html), tetapi akses dataset dan lisensi belum tersedia di eksperimen ini. Tidak ada pembelian atau langganan yang dibuat.

[Bookmap resmi menyediakan koneksi exchange yang didukung](https://bookmap.com/learning-center/connectivity/crypto-data/connecting-to-crypto). Prototipe ini dapat menjadi alat replay/penelitian tersendiri, bukan klaim sudah tersambung pada terminal Bookmap pengguna. Langkah riset berikut yang masuk akal adalah memperpanjang rekaman order flow dan menguji fitur transaksi asli bersama zona yang dikunci. Jangan memperlonggar threshold berdasarkan tiga hari ini lalu menyebut hasilnya out-of-sample.

## Rekonstruksi dan berkas

```bash
python3 -m pip install -r requirements.txt
python3 download.py
python3 prepare_books.py
python3 -m unittest test_research -v
python3 evaluate.py
MPLBACKEND=Agg python3 visualize.py
# Replay interaktif lokal, membutuhkan desktop Python/Matplotlib:
python3 visualize.py --interactive --day 2024-01-06
```

Paket menyertakan delapan input turunan `.npz` (quote 1 detik dan heatmap 30 detik) sehingga `evaluate.py` dan viewer bisa dijalankan tanpa mengunduh ulang arsip mentah sekitar 2,1 GB. Download mentah + `prepare_books.py` diperlukan untuk mengulang rekonstruksi dari setiap delta. Source mentah tidak dihapus.

12 regression test lulus: snapshot/delta/reset/delete, stale/crossed/reorder, bukti fitur strictly pre-decision, fitur hilang, censor gap, stress dengan spread tetap, prefix causality engine asli, serta penjagaan venue/availability zona. `tests.log` menyimpan output lokal; tidak ada klaim job CI baru dijalankan.

Berkas penting: `EVENT_LEDGER.csv`, `COMPARISON.csv`, `EVENT_AUDIT.json`, `DATA_AUDIT.json`, `HEATMAP_ZONE_REPLAY.png`, `HOLDOUT_COMPARISON.png`, konfigurasi, source dan environment. Heatmap contoh adalah kejadian exante pertama pada holdout secara kronologis, bukan contoh terbaik yang dipilih setelah profit diketahui. Source/hasil teks disimpan pada branch riset tersendiri; tidak merge ke main.
