# RIZAN — Zone + Actual Order Flow Challenger V2

20 Oktober 2026 · `RZ-ZONE-FLOW-CHALLENGER-V2-20261020`

**Hasil: ada indikasi perbaikan timing entry pada zona H1, tetapi belum ada konfigurasi yang layak dinyatakan tervalidasi atau tahan stress biaya.** Beberapa hasil normal positif hanya berasal dari 3–6 transaksi holdout. Modul ini riset terpisah; tidak ada order, perubahan cBot beku, bridge, risk live, dashboard produksi, atau merge main.

## Data aktual dan lingkup

- Venue/instrumen: **Bybit linear BTCUSDT perpetual**, bukan BTCUSD CFD FP Markets, bukan XAUUSD/EURUSD.
- Tape transaksi: **6.651.971 transaksi unik** pada **1 Februari, 1 Maret, 1 April, dan 1 Mei 2024 UTC**. Ini empat tanggal, **bukan empat bulan penuh**. Sampel publik hari pertama bulan dari Tardis; bukan sampel acak.
- Order book: **13.822.973 pesan** dari 16 arsip harian, mencakup tiga hari pemanasan sebelum setiap tanggal tersebut. Total input tervalidasi **4.431.845.966 byte**. Seluruh anggota ZIP dibaca sampai akhir untuk CRC, seluruh tape gzip dibaca dan SHA256 input dicatat di `INPUT_MANIFEST.json`.
- Kedalaman direkonstruksi setiap delta dan disampel satu detik. Ada 61 detik tanpa quote valid pada seluruh 16 hari; tidak diimputasi. Regresi timestamp teramati nol. Bukan sertifikasi semua paket exchange tertangkap sempurna.
- Semua trade memiliki sisi aggressor yang dikenal; duplikat ID nol dan timestamp arrival negatif nol. Median keterlambatan capture sekitar 40–46 ms, p99 bervariasi hingga sekitar 1,14 detik.

Sumber: [Tardis Bybit historical data](https://docs.tardis.dev/historical-data-details/bybit), [schema trade aggressor dan arrival timestamp](https://docs.tardis.dev/downloadable-csv-files/data-types), serta arsip orderbook Bybit dengan URL per berkas di manifest. Tidak ada pembelian/langganan atau akun Bookmap resmi yang dihubungkan. Akses publik transaksi yang sebelumnya gagal pada public.bybit.com tidak dianggap data; tape baru berhasil diakses melalui dataset Tardis untuk venue yang sama.

## Source dan eksperimen

Paket `RIZAN_RLFE_V2_RESEARCH_ONLY.zip` aktual dibaca: isinya modul ordinal dan 10 tes sintetis, tanpa bukti replay atau feed aktif. Bobot support index tersebut tidak diperlakukan sebagai probabilitas dan tidak dioptimasi di sini.

Geometri zona utama menjalankan **`manual_reversal_map.py::detect` asli**, byte-identik dengan repository commit `e357272fec03411a6e7c4d2397faf742d1a11047`, Git blob `f955bd5e8e7c78f0b920567ed073489fa32b68af`. Source SHA256 `dcd8b9e54074eb596da153f201d1a57d5c4374d9a826b419d143330f0d1eb3b7`. Detektor dipanggil pada prefix H1 yang tumbuh untuk mencatat zona saat tersedia. **Zona yang akhirnya jebol tetap dipertahankan dalam sejarah**, bukan diseleksi dari daftar survivor pada akhir replay.

Ini adaptasi geometri pada BTC dengan risk/timing challenger baru, bukan reproduksi penuh Candidate A dashboard atau strategi cBot. H4 diberi konteks HH/HL, LL/LH, atau RANGE dari dua candle H4 closed; konteks dicatat, **tidak menjadi filter wajib**. H1 sebagai anchor. Kontrol terpisah memakai ekstrem 16 M15 sebelumnya. Tidak ada macro vintage yang ditambahkan.

- `H1_SD`: zona base/departure asli, first touch dalam12 jam ketersediaan efektif; sentuhan selama warmup ikut diperiksa agar retest tidak diklaim fresh.
- `M15_EXTREME_CONTROL`: high/low empat jam sebelumnya sudah ditetapkan sebelum candle sentuhan; band kontrol dan SL terpisah dari H1.
- 97 peluang zona: **16 H1**, **81 kontrol M15**. H1 development7 dan holdout9. Tidak ada pencarian ulang jutaan konfigurasi.

## Konfigurasi yang dapat diulang

`LOCKED_PROTOCOL.json` dan `IMPLEMENTATION_NOTES.json` dibuat sebelum outcome awal. Development 1Feb/1Mar; holdout diagnostik 1Apr/1Mei. M15→M5 ditambahkan secara eksplisit **setelah** hasil tiga varian awal diperiksa untuk melengkapi alur timeframe yang diminta; `M15_M5_EXTENSION.json` menyatakan ini eksploratif. Hasil tiga varian awal dipertahankan dan diperiksa identik di `OUTCOME_STABILITY.json`. Jangan menganggap tambahan M15→M5 sebagai preregistered blind holdout.

Tiga timing awal:

1. `baseline_first_touch`: quote pertama setelah sentuhan.
2. `absorption_early`: setelah sweep ekstrem 15 menit yang telah diketahui, muncul pola volume agresif lawan besar tetapi kemajuan harga kecil dekat zona.
3. `absorption_reclaim`: setelah pola itu, menunggu reclaim **M1 closed**; ini eksperimen timing cepat, terpisah dari validasi M15/M5.

Dua pembanding tambahan:

4. `baseline_M15_M5`: menjalankan fungsi asli `reversal_phase` pada prefix candle closed: M15 kontak/reclaim, lalu M5 break tiga candle sebelumnya. Tidak mensyaratkan absorption.
5. `absorption_M15_M5`: urutan yang sama, dengan M5 confirmation harus closed setelah bukti absorption. Entry diamati dalam60 menit sejak first touch. Ini mengisolasi tambahan bukti flow dari konfirmasi struktur.

Pola absorption yang diuji adalah **proxy operasional**, bukan bukti identitas institusi atau iceberg: counter-side taker notional15s ≥ percentile75 dari counter-side15s sepanjang30 menit sebelumnya; proporsi counter-side ≥60%; adverse progress15s ≤0,1 ATR H1; sekurangnya10 quote valid; ada transaksi lawan di sekitar zona ±0,1ATR; signal masih dekat zona ±0,25ATR; dan ditemukan dalam10 menit sentuhan. Depth imbalance dan retention di radius5bp dicatat sebagai evidence, tidak menjadi syarat baru. Retention ini mengikuti band dekat mid, **bukan pengukuran refill pada satu harga tetap**. Tidak ada klaim deteksi spoofing, replenishment per-order, atau iceberg.

Semua timing memakai stop harga yang sama untuk satu zona: distal ±0,1ATR H1. Stop tidak dipindah memakai ekstrem masa depan. Breach saat menunggu membatalkan entry. Risk distance0,15–4ATR, TP1R dari entry, horizon **30/60/120 menit** (satuan diuji). Entry model minimal1 detik setelah keputusan; BUY ask, SELL bid; exit sisi executable yang berlawanan. Quote gap tersensor, akhir dataset tersensor tanpa forced close.

Tape tersedia pada `max(exchange_timestamp, local_timestamp)` dan baru masuk bucket setelah arrival; transaksi terlambat tidak dibocorkan pada exchange timestamp yang lebih awal. Arsip orderbook tidak memiliki arrival timestamp sehingga diasumsikan publikasi exchange +1detik; ini asumsi penelitian, bukan latency broker yang diukur. Quote/fill satu detik bukan native/full parity.

Biaya model: commission5,5bp/sisi, slippage debit1bp/sisi, financing debit3bp notional/hari proporsional durasi. Spread aktual bid/ask sudah terkandung dalam entry/exit. Stress1,5× dan2× mengalikan debit fee/slippage/financing pada fill yang sama, **spread tidak dikalikan**. Ini bukan tarif FP atau funding settlement Bybit aktual yang disertifikasi, dan bukan stress market impact. Tidak ada simulasi leverage atau compounding.

## Hasil H1 holdout — satu posisi per varian

Seluruh horizon ditampilkan; tidak ada satu hasil dipromosikan sebagai pemenang. `absorption_reclaim` berarti M1. Nol loss menyebabkan PF tidak terdefinisi, bukan bukti PF tak terbatas.

| horizon_min | variant | n | wins | win_pct | mean_net_R | PF_R |
| --- | --- | --- | --- | --- | --- | --- |
| 30 | absorption_M15_M5 | 2 | 1 | 50.000 | -0.010 | 0.947 |
| 30 | absorption_early | 6 | 3 | 50.000 | 0.103 | 1.700 |
| 30 | absorption_reclaim | 3 | 3 | 100.000 | 0.354 | — |
| 30 | baseline_M15_M5 | 3 | 2 | 66.667 | 0.099 | 1.765 |
| 30 | baseline_first_touch | 9 | 4 | 44.444 | 0.006 | 1.037 |
| 60 | absorption_M15_M5 | 2 | 1 | 50.000 | -0.117 | 0.534 |
| 60 | absorption_early | 6 | 3 | 50.000 | 0.073 | 1.210 |
| 60 | absorption_reclaim | 3 | 2 | 66.667 | 0.237 | 2.937 |
| 60 | baseline_M15_M5 | 3 | 2 | 66.667 | 0.045 | 1.271 |
| 60 | baseline_first_touch | 9 | 3 | 33.333 | -0.056 | 0.804 |
| 120 | absorption_M15_M5 | 2 | 0 | 0.000 | -0.303 | 0.000 |
| 120 | absorption_early | 6 | 4 | 66.667 | 0.021 | 1.048 |
| 120 | absorption_reclaim | 3 | 1 | 33.333 | -0.146 | 0.671 |
| 120 | baseline_M15_M5 | 3 | 0 | 0.000 | -0.357 | 0.000 |
| 120 | baseline_first_touch | 9 | 6 | 66.667 | -0.155 | 0.632 |

Horizon60menit memberikan contoh paling relevan untuk dibahas, **bukan konfigurasi final**: baseline9 transaksi, WR33,3%, mean−0,056R, PF0,804. Absorption awal6 transaksi, WR50%, mean+0,073R, PF1,210. Pada development, varian awal60menit juga positif (+0,146R, PF2,374,6 transaksi), tetapi win rate development sama dengan baseline66,7%: peningkatan win rate belum konsisten.

M1 reclaim60menit holdout2/3 win, mean+0,237R danPF2,937; development hanya+0,013R danPF1,086. Pada30menit3/3win semuanya timeout, bukan3 TP1R. **Jangan menyebut100% itu win rate yang dapat diandalkan.** Pada120menit varian M1 justru negatif.

Konfirmasi penuh M15→M5 ditambah absorption belum mendukung perbaikan:60menit holdout1/2win, mean−0,117R; pembanding M15→M5 tanpa absorption2/3win, mean+0,045R. Development kedua varian struktur tersebut0/2win dan negatif. Tidak ada dasar untuk menyatakan penumpukan konfirmasi otomatis lebih akurat.

Kontrol M15 tetap negatif pada seluruh varian/horizon holdout yang diuji dengan biaya normal. Hasil ini mendukung prioritas meneliti **lokasi zona H1 dan timing reaksi**, tetapi empat tanggal tidak membuktikan keunggulan umum atau kausalitas H4. Detail kontrol/development ada di `COMPARISON.csv`.

## Memisahkan efek seleksi dan timing

Perbandingan di bawah memakai baseline pada **event zona yang sama** dengan transaksi challenger terpilih, supaya perbaikan tidak hanya karena membuang zona rugi. Ini counterfactual paired event study; bukan dua portfolio yang serentak diperdagangkan.

| horizon_min | variant | matched_n | baseline_same_zones_mean_R | challenger_same_zones_mean_R | mean_timing_delta_R |
| --- | --- | --- | --- | --- | --- |
| 30 | absorption_M15_M5 | 2 | 0.538 | -0.010 | -0.548 |
| 30 | absorption_early | 6 | 0.028 | 0.103 | 0.076 |
| 30 | absorption_reclaim | 3 | 0.373 | 0.354 | -0.019 |
| 30 | baseline_M15_M5 | 3 | 0.248 | 0.099 | -0.149 |
| 30 | baseline_first_touch | 9 | 0.006 | 0.006 | 0.000 |
| 60 | absorption_M15_M5 | 2 | 0.335 | -0.117 | -0.452 |
| 60 | absorption_early | 6 | -0.090 | 0.073 | 0.163 |
| 60 | absorption_reclaim | 3 | 0.513 | 0.237 | -0.276 |
| 60 | baseline_M15_M5 | 3 | 0.320 | 0.045 | -0.274 |
| 60 | baseline_first_touch | 9 | -0.056 | -0.056 | 0.000 |
| 120 | absorption_M15_M5 | 2 | 0.481 | -0.303 | -0.783 |
| 120 | absorption_early | 6 | -0.089 | 0.021 | 0.109 |
| 120 | absorption_reclaim | 3 | 0.610 | -0.146 | -0.755 |
| 120 | baseline_M15_M5 | 3 | 0.332 | -0.357 | -0.689 |
| 120 | baseline_first_touch | 9 | -0.155 | -0.155 | 0.000 |

Untuk absorption awal60menit, enam zona yang sama menghasilkan baseline−0,090R versus challenger+0,073R, selisih+0,163R perkejadian. Ini indikasi perbaikan timing pada sampel tersebut. M1 reclaim60menit justru lebih rendah daripada entry pertama pada tiga zona yang dipilih (+0,237R vs+0,513R), sehingga PF kelompok kecil yang tampak bagus tidak otomatis berarti entry lebih baik. Pemilihan dan timing harus tetap dipisahkan.

## Stress biaya H1 horizon60menit

| variant | cost_multiple | n | win_pct | mean_net_R | PF_R |
| --- | --- | --- | --- | --- | --- |
| absorption_M15_M5 | 1.000 | 2 | 50.000 | -0.117 | 0.534 |
| absorption_M15_M5 | 1.500 | 2 | 50.000 | -0.171 | 0.392 |
| absorption_M15_M5 | 2.000 | 2 | 50.000 | -0.225 | 0.278 |
| absorption_early | 1.000 | 6 | 50.000 | 0.073 | 1.210 |
| absorption_early | 1.500 | 6 | 50.000 | -0.016 | 0.959 |
| absorption_early | 2.000 | 6 | 50.000 | -0.106 | 0.761 |
| absorption_reclaim | 1.000 | 3 | 66.667 | 0.237 | 2.937 |
| absorption_reclaim | 1.500 | 3 | 66.667 | 0.165 | 2.095 |
| absorption_reclaim | 2.000 | 3 | 66.667 | 0.094 | 1.522 |
| baseline_M15_M5 | 1.000 | 3 | 66.667 | 0.045 | 1.271 |
| baseline_M15_M5 | 1.500 | 3 | 66.667 | -0.008 | 0.958 |
| baseline_M15_M5 | 2.000 | 3 | 66.667 | -0.061 | 0.705 |
| baseline_first_touch | 1.000 | 9 | 33.333 | -0.056 | 0.804 |
| baseline_first_touch | 1.500 | 9 | 33.333 | -0.143 | 0.594 |
| baseline_first_touch | 2.000 | 9 | 33.333 | -0.229 | 0.450 |

Absorption awal60menit berubah menjadi−0,016R pada biaya1,5× dan−0,106R pada2× di holdout; development2× juga negatif. M1 reclaim holdout tetap positif pada2× tetapi hanya3 transaksi dan developmentstress negatif. Tidak ada varian yang dapat dinyatakan robust dari sampel ini.

## Audit dan batas statistik

`EVENT_LEDGER.csv` memuat97zona ×5timing ×3horizon =1.455 baris skenario, **bukan1.455 transaksi independen**. Terdapat933 outcome lengkap,507 tanpa sinyal entry,15 tersensor ujung data. Biaya alternatif adalah kolom counterfactual pada fill yang sama. `ONE_POSITION_LEDGER.csv` menyimpan transaksi yang benar-benar masuk per varian, keluarga dan horizon; keluarga berbeda **tidak** berbagi account/margin dalam penelitian ini.

Peluang baseline lengkap dengan tape tersedia menjadi denominator matched; event study dan satu-posisi dilaporkan terpisah. Hasil tidak boleh dijumlahkan antarhorizon/varian sebagai saldo portfolio. DD yang dicatat adalah drawdown kumulatif unitR, bukan floating equity DD persentase akun.

12 tes lulus: prefix causal source asli, menghindari survivor bias, H4 unfinished bar, arrival trade terlambat, no-tape, M1closed, stop saat menunggu, M15→M5closed, snapshot wajib, gap/censor, satuan30/120menit, dan biaya dengan spread tetap. `LEDGER_RECONCILIATION.json` memeriksa identitas cash gross/netR, urutan keputusan-entry dan zona tersedia sebelum touch. Tidak ada klaim CI baru atau replay native.

Ini convenience sample empat hari pertama bulan dengan dua hari diagnostik holdout, bukan2019–2026 dan bukan walk-forward tahunan. Banyak varian diperiksa; sampel terlalu kecil untuk mengklaim signifikansi atau probabilitas terkalibrasi. XAU/EUR memerlukan L2/trades yang sesuai atau GC/6E dengan basis/roll/capture yang diaudit. Data BTC ini tidak menggantikan kebutuhan tersebut. Asumsi biaya, clock1detik, horizon dan risk model memengaruhi hasil; optimasi historis bukan jaminan performa mendatang.

## Keputusan riset dan rekonstruksi

**Belum layak dipromosikan ke cBot atau live.** Jalur penelitian yang terlihat lebih menjanjikan di sini adalah zona H1 dengan absorption awal, terutama pembahasan60menit; itu tetap kandidat eksploratif, bukan freeze baru. Wajib diuji pada periode lebih panjang dan berurutan, spread/fee broker yang benar, serta data XAU/EUR sebelum klaim peningkatan pada engine forex.

```bash
python3 -m pip install -r requirements.txt
python3 download_inputs.py
python3 prepare_inputs.py
python3 -m unittest test_challenger -v
python3 challenger.py
python3 audit_ledgers.py
MPLBACKEND=Agg python3 flow_chart.py
```

Paket menyertakan derived quote/tapeNPZ agar replay dapat diulang tanpa download mentah lagi. Arsip mentah tetap dipertahankan di folder riset; URL dan checksum ada di manifest. Source/hasil teks disimpan pada branch riset tersendiri. Paket RLFE V2 asal dan source upstream tetap disertakan untuk provenance; tidak ada modifikasi pada paket lama.
