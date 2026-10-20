# RIZAN — Riset keluarga baru titik reversal, XAUUSD dan EURUSD

**Tanggal riset:** 20 Oktober 2026. **Harga historis:** 1 Januari 2019–31 Maret 2026, Dukascopy BID M1 yang diturunkan dari arsip tick; bukan replay tick native broker FP Markets. **Tujuan:** mencari metode **baru**, bukan sekadar memperketat filter Kandidat A.

## 1. Hipotesis yang benar-benar diuji

- **Liquidity sweep / failed auction**: candle M15 menyapu ekstrem 4/8/16/24 jam lalu menutup kembali di dalam ekstrem; variasi jarak sweep dan rasio wick.
- **Mean-reversion reentry**: harga keluar jauh dari mean/standar deviasi historis 8/16/32 jam lalu menutup kembali mendekati mean (z-score recovery), tanpa menggunakan candle masa depan.
- **Exhaustion reversal**: harga telah mengalami deviasi besar dari EMA M15, lalu muncul candle perlawanan kuat.
- **Previous-day sweep & reclaim**: candle M15 melampaui high/low hari sebelumnya dan menutup kembali di dalamnya.
- **Ex-ante previous-day levels**: sebelum sesi dimulai, tempatkan level BUY/SELL di sekitar high/low hari trading sebelumnya (0/0,05/0,10/0,20 ATR harian); backtest harga tersentuh pada M1 pertama dan evaluasi dengan SL dan TP, **tanpa menunggu sinyal setelah mencapai level**.

## 2. Pengujian dan hasil

Total 5.018 baris konfigurasi dievaluasi pada dua pasangan: **405 awal + 1.944 variasi stop/horizon + 160 resting levels = 2.509 per instrumen**. Seluruhnya *exploratory search* pada rekaman historis sama. Pemilihan berdasarkan PF normalisasi risiko *development* 2019–2023; hasil 2024–2025 dan Jan–Mar 2026 dibandingkan tanpa optimasi tambahan atas periode tersebut, tetapi arsip tersebut sebelumnya telah sering dianalisis, sehingga tidak dapat dianggap untouched holdout global.

| Keluarga uji / setelan terbaik BERDASARKAN PF periode 2019–2023 | XAU PF 2019–23 | XAU PF 2024–25 | EUR PF 2019–23 | EUR PF 2024–25 |
|---|---:|---:|---:|---:|
| Empat keluarga M15 + SL pada ekstrem candle dan TP 0,75–2R | 0,798 | 0,702 | 0,677 | 0,505 |
| Empat keluarga M15 + minimal SL 0,75/1,25/2 ATR (TP 0,5–1,5R, holding 12/24h) | 0,854 | 0,709 | 0,733 | 0,527 |
| Level harian **sebelum sentuhan** (limit pada prior-day high/low ± offset) | 0,915 | 0,821 | 0,981 | 0,829 |

**Tidak ada keluarga yang mencetak PF > 1 pada periode pengembangan**, dalam ruang konfigurasi yang diuji. Angka tabel adalah **puncak PF train dari tiap blok eksperimen**, bukan satu aturan universal yang dibuktikan menguntungkan. Tidak ada hasil yang dapat dipromosikan sebagai strategi trading.

**Contoh titik balik vs PF:** XAU prior-day extreme dengan offset 0,10 ATR, SL 0,40 ATR harian, TP 0,5R, holding 24h, mencatat **62,8% menang train** (897 posisi) dan **60,8% menang 2024–2025** (372 posisi), tetapi PF hanya **0,737 train** dan **0,685 validation**. EUR varian offset 0,05 ATR, SL 0,25 ATR, TP 0,5R: **67,7% menang train** (1.033 posisi), **59,7% validation** (407 posisi), dengan PF **0,858/0,606**. Persentase pantulan tinggi bisa tetap merugi akibat ukuran rata-rata kekalahan dan biaya.

**Perbandingan dengan Kandidat A sebelumnya:** A-TP1R XAU PF R satu-posisi historis sekitar 1,163, tetapi bootstrap 95% termasuk di bawah PF 1. Ini **tidak** berarti Kandidat A sudah layak live. Empat keluarga baru tidak mengalahkan A menurut uji ini.

## 3. Asumsi penting dan batas validitas

- OHLC M1 BID dari agregasi arsip Dukascopy. Menurut arsip sebelumnya ada 2.557.244 bar XAU dan 2.696.972 EUR. Bukan bid/ask tick, FP Markets spread, antrian order limit, atau hasil cTrader backtester.
- Komisi: XAU 0,07 USD/oz roundtrip, EUR 0,00007 USD/EUR roundtrip; slippage XAU 0,05 USD/oz per sisi, EUR 0,000005 USD/EUR per sisi. Spread historis M1 ditambahkan sebagai perkiraan; estimasi bukan angka persis broker.
- Entry candle M15 selesai → pembukaan M1 berikutnya untuk empat keluarga M15. Prior-day levels adalah limit sintetis di level yang diketahui sebelumnya, penanganan ambiguitas candle M1 konservatif: **STOP_FIRST** dan TP hanya boleh dihitung mulai candle M1 berikutnya sesudah fill.
- Maksimal satu posisi aktif per instrumen; risiko dinormalkan dalam satuan R; stop/target diproses M1 dan waktu kedaluwarsa posisi dihitung wall-clock 8/12/24h tergantung tes; jeda pasar tidak ditutup secara fiktif pada candle terakhir.
- Tidak ada pemodelan tick-path asli, FIFO, swap, margin, true order queue, delay nyata, volatilitas berita titik-demi-titik, atau portofolio margin gabungan. Kualitas data dan gap tape belum diaudit ulang secara menyeluruh dalam putaran ini.
- **Belum ada pengujian macro point-in-time** untuk keluarga baru: data DXY/US2Y/US10Y historis dengan timestamp rilis, revisi, dan vintage belum tersedia dalam paket ini. Menambah macro modern retrospectively akan menimbulkan look-ahead/data revision bias.

## 4. Rekomendasi mesin baru: RIZAN REVERSAL HAZARD MAP (konsep riset, BELUM tervalidasi)

Bukan lagi kumpulan syarat `WATCH` lebih ketat. Mesin baru harus **mencari dan memprioritaskan level harga sebelum disentuh**:

1. **Liquidity destination** (H4/H1 dan prior-session high/low, equal highs/lows, volume profile jika volume terpercaya ada), bukan zona base semata.
2. **Adaptive band**: proximal/distal dihitung dari ATR harga, realized spread dan volatilitas, dengan posisi penetration depth yang meningkatkan risiko breakdown secara kontinu.
3. **Two-sided competing-risk model**: pada setiap level hitung peluang `pantul >=0,5 ATR`, `pantul >=1 ATR`, `break distal`, dan `belum selesai dalam N jam`. Jangan menjumlahkan probabilitas dengan outcome tersensor tanpa benar.
4. **Entry plan**: pilih referensi pasif di level vs reclaim setelah sweep; nilai nilai harapan bersih, bukan hanya win rate. Jangan otomatis menyebut “reversal” ketika harga baru menyentuh level.
5. **Macro context optional**: DXY, US2Y, US10Y, yield real/TIPS, perubahan probabilitas Fed, shock CPI/NFP/FOMC; gunakan snapshot tepat pada waktu diketahui (as-of), bukan nilai akhir harian yang baru diketahui sesudah sesi. Kondisi makro dapat meningkatkan maupun menurunkan peluang breakout: bukan larangan mutlak.
6. **Evaluasi produksi**: harness causal event-driven, probabilitas terkalibrasi, perhatikan regime drift; nilai tambah baseline first-touch, Candidate A, dan harga tanpa zona. Kandidat dibekukan hanya setelah multi-year holdout baru, uji biaya FP Markets, dan forward paper-trading.

**Referensi publik untuk metodologi macro:** Federal Reserve Bank of Chicago, *What Drives Gold Prices?* (2021) https://www.chicagofed.org/publications/chicago-fed-letter/2021/464 ; CME Group, *Through the lens of gold* (2024) https://www.cmegroup.com/articles/2024/through-the-lens-of-gold.html ; FRED/ALFRED real-time vintage information https://fred.stlouisfed.org/docs/api/fred/realtime_period.html . CME mencatat bahwa korelasi dolar–emas tidak selalu tetap; macro harus dievaluasi sebagai state berubah, bukan koefisien pasti.

## 5. Keputusan

**Tidak menerapkan hasil negatif ke scanner, tidak mengubah cBot, bridge, akun live, risiko, atau order.** Pertahankan zona manual existing dan Kandidat A sebagai pembanding; riset berikutnya adalah mekanisme pengukuran bahaya penetrasi dan area likuiditas sebelum sentuhan + macro point-in-time, bukan menjanjikan pembalikan pada level apa pun.

## 6. Artefak

- `run_research.py`, `second_pass.py`, `exante_level_research.py`: skrip lengkap dan dapat direproduksi dengan CSV sumber M1.
- `XAUUSD_all_family_results.csv`, `EURUSD_all_family_results.csv`: 405 konfigurasi masing-masing.
- `XAUUSD_wide_stop_all.csv`, `EURUSD_wide_stop_all.csv`: 1.944 konfigurasi masing-masing.
- `XAUUSD_exante_prior_day_levels.csv`, `EURUSD_exante_prior_day_levels.csv`: 160 konfigurasi masing-masing.
- Dataset BID M1 500+MB **tidak dikemas**; gunakan arsip asli yang sudah tersedia jika hendak reproduksi.
