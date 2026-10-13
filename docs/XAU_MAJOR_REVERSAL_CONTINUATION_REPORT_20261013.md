# Lanjutan riset reversal utama harian XAU
13 Oktober 2026, WIB

**Tujuan menemukan konfigurasi yang lebih profit untuk zona utama harian belum tercapai.** Tiga keluarga tambahan selesai diuji, masing-masing 10.000.000 kombinasi pada replay 2016–2025. Semuanya berstatus RESEARCH_ONLY. Tidak ada entry, TP, SL, atau jam terbaik yang dipromosikan.

## Hasil seleksi

Jumlah berikut kumulatif; sudah mensyaratkan minimal 180 trade training dan 60 trade validation.

| Keluarga | Kombinasi diuji | Training net positif | PF training ≥1,15 | PF validation ≥1,20 |
|---|---:|---:|---:|---:|
| Sweep D1/sesi |10.000.000|4.623|317|**0**|
| Stop struktural ATR M5 |10.000.000|514|20|**0**|
| Filter volatilitas/biaya |10.000.000|2.498|345|**0**|

Total 30 juta evaluasi kombinasi tambahan, di luar studi V6 sebelumnya. Kombinasi dapat berbagi keputusan; bukan 30 juta strategi independen. Filter volatilitas memperbaiki jumlah yang lolos training, tetapi tidak mempertahankan PF validation. Ini tidak membuktikan semua pola reversal pasti rugi.

Seluruh fold walk-forward 2020–2025 juga tidak memilih kandidat. Pipeline ledger/verify Januari–September 2026 selesai, tetapi **tidak ada kandidat terkunci dan tidak ada trade kandidat 2026 yang diuji**. Tidak ada bukti validasi trading 2026.

## Hipotesis, TP, SL, dan waktu

**Sweep/reclaim daily dan sesi:** anchor high/low D1 sebelumnya, dua D1 terakhir, rentang UTC 00–06, rentang UTC 06–12, atau enam H4 tertutup. Anchor diketahui sebelum M5 membuka. Harga menyapu level lalu close kembali di dalam minimal 0,025 ATR H1 dengan body ke arah reversal. SL di luar ekstrem sweep ditambah 0,05–0,50 ATR H1; target 25/35/50/75/100% ADR20. Konteks trend memakai slope EMA50 H1.

**Stop struktural M5:** re-entry regression channel 24/32/48/64 bar dan sweep24 dengan konfirmasi 1–3 M5 bar; konteks strict H1/M15 dari modul penelitian V6. Anchor stop adalah ekstrem trigger atau seed. Jarak stop=max(0,50 XAUUSD, ATR14 M5 × multiplier, jarak fill cautious ke anchor). Multiplier:1/1,65/2,15/2,65/3,25. Target:1,5/2/3/4/6,6 nominal R, tetap minimal 25% ADR20.

**Filter volatilitas/biaya:** pola dan stop struktural, half-width tetap 0,5 ATR H1; minimum ATR14 M5/spread cautious0,50:0/0,5/1/1,5/2. Nol adalah baseline tanpa filter. ATR harus sudah diketahui pada close trigger, tanpa range atau outcome masa depan.

ATR H1 memakai20 bar; M5 memakai14 bar. ADR20 dari hari UTC lengkap dengan minimal900 bar M1. Sesi diuji pada WIB07–13,13–19,19–01,01–07; holding dibatasi20:55UTC dan waktu tersisa minimal120menit. Nama Asia/Eropa hanya rentang UTC tetap, bukan jam resmi pasar/DST.

Target R bukan target ATR H1. TP3R dengan stop1,65ATR M5 tidak berarti TP3ATR H1. Tidak mengklaim top/bottom absolut setiap hari atau adanya reversal setiap hari.

## Data dan biaya

Bid M1 HistData:3.492.721 bar dalam2016–2025, ditambah warm-up/buffer. Hash SHA256 dan rentang UTC tiap sumber tersimpan dalam JSON hasil.

| Skenario | Spread XAUUSD | Slippage tiap sisi |
|---|---:|---:|
| Reference |0,25|0,05|
| Cautious, ranking utama |0,50|0,10|
| Stress |1,00|0,20|

Unit harga XAUUSD, bukan persentase akun. Synthetic spread/slippage bukan historical bid/ask broker. Komisi nol proxy Standard, bukan biaya akun pengguna yang diverifikasi. Tidak overnight atau swap; lot, leverage, equity scaling, compounding, layering, dan batch cBot tidak dimodelkan. R adalah nominal risk penelitian, bukan return atau drawdown akun.

Entry next-M1 open. Bila TP/SL tersentuh dalam M1 yang sama, SL diprioritaskan. Stop gap di harga lebih buruk dapat loss>1R. Timeout memakai open tepat di deadline. Gap data>300detik/deadline hilang dicensor.

First eligible trigger per konfigurasi, hari UTC, sesi, dan arah dipilih setelah semua filter known-at-entry. Trigger censored tetap mengklaim hari itu, tanpa mengganti memakai pengetahuan outcome belakangan. BUY/SELL diteliti terpisah, bukan portfolio gabungan.

Event/macro tidak dipakai karena historical initial-publication availability belum diverifikasi. Studi biaya/volatilitas bukan bukti bahwa biaya adalah satu-satunya penyebab loss.

## Syarat kelulusan tetap

Training2016–2021: n≥180, netR positif, PF≥1,15, minimal5/6tahun positif dengan≥15trade/tahun, censor≤2%.
Validation2022–2025: n≥60, PF≥1,20, stressmean positif, descriptive mean lower bound positif, minimal3/4tahun positif dengan≥15trade/tahun, censor≤2%.

Riwayat2016–2025 telah dilihat dalam keluarga penelitian lain. Confidence historis bersifat deskriptif, bukan multiple-test corrected confidence atau pristine holdout.

Parameter harus dikunci sebelum outcome kandidat Jan–Sep2026. Data2026 sudah ada di cache; tidak mengklaim pertama diunduh setelah lock. Qualification2026:n≥30, meanNetR>0, PF≥1,20, stressmean>0, lower95%monthly block bootstrap meanR>0, censor≤2%. Tidak ada kandidat mencapai tahap tersebut. Ambang tidak diturunkan setelah hasil.

Protokol sebelum outcome:
- [Daily/sesi](XAU_DAILY_ANCHOR_RESEARCH_PROTOCOL_20261013.md)
- [Stop struktural M5](XAU_STRUCTURAL_M5_RESEARCH_PROTOCOL_20261013.md)
- [Volatilitas/biaya](XAU_VOLATILITY_COST_RESEARCH_PROTOCOL_20261013.md)

## Contoh yang ditolak

Dipilih setelah melihat validation untuk diagnosis, bukan rekomendasi atau prediksi periode berikutnya.

| Arah/sumber | Sesi WIB penelitian | N training | PF training | Mean netR training | N validation | PF validation | Mean netR validation |
|---|---|---:|---:|---:|---:|---:|---:|
| BUY channel48 |07–13|184|0,375|−0,566R|101|1,793|+0,493R|
| SELL channel24 |19–01|223|0,587|−0,274R|109|1,706|+0,296R|

BUY:trend ALIGNED, wick minimum0, approach0, volatility floor0, stop1,65ATR M5, target3R, horizon480menit, minimum netRR1,5. Tidak ada tahun training yang memenuhi syarat positif dan15trade; validation hanya dua tahun positif; censoring nol.

SELL:trend ALIGNED, wick≥0,2, approach≥1ATR H1, volatility floor0, stop2,65ATR M5, target3R, horizon480menit, minimum netRR1,5. Training tidak memiliki tahun positif sesuai syarat; validation empat tahun positif tetapi censor6/(109+6)=5,217%.

PF terbaru yang tinggi tidak menutupi kerugian periode lama. Contoh hanya runner-up diagnostik berdasarkan validation lower bound per arah dengan trade mencukupi. **Belum ada probabilitas reversal, jam terbaik, atau harga TP/SL live yang tervalidasi.** Net-positive win rate berbeda dari target-hit rate; probabilitas tidak diturunkan dari PF.

## File dan patch

Modul baru daily_reversal.py, structural_reversal.py, volatility_reversal.py di src/fx_scanner; masing-masing memiliki script research/audit, tests, dua workflow, protokol, dan JSON hasil/diagnostik.

Patch utama: anchor causal D1/sesi; stop ATR M5 dan structural extreme; target R dengan guard25%ADR20; known volatility/cost filter sebelum first eligible; dashboard status dan alasan penolakan tanpa execution. main.py memakai panel terbaru dan mempertahankan arsip. Perubahan daily dashboard/laporan yang masuk bersamaan pada6422de28 dipertahankan.

## Tes, CI, dan scope

- Lokal: **69 tes PASS** dalam13,83detik, seluruh lima file tes.
- CI daily:44PASS; structural:56PASS; volatility:57PASS. CI volatility tidak menyertakan file structural secara terpisah; local69 mencakupnya.
- Tes:prefix causality, prior-day/completed-session guards, RR/ADR, spread/slippage, stop-first/gap, deadline open, first eligible per hari, censored-day claim.
- Tiga replay dan audit PASS. Ledger kosong bukan bukti profit atau execution broker.
- Sweep D1/sesi: [replay](https://github.com/rizanrizan93/Forex-scanner/actions/runs/38384475679), [audit](https://github.com/rizanrizan93/Forex-scanner/actions/runs/38385049724).
- Stop struktural M5: [replay](https://github.com/rizanrizan93/Forex-scanner/actions/runs/38385608189), [audit](https://github.com/rizanrizan93/Forex-scanner/actions/runs/38386017283).
- Filter volatilitas/biaya: [replay](https://github.com/rizanrizan93/Forex-scanner/actions/runs/38386687428), [audit](https://github.com/rizanrizan93/Forex-scanner/actions/runs/38386903716).
- Scope XAU/EUR PASS:17/24method tetap. Contract XAU7ab0cd24eb2e46480d0ba371ba2cd713c5d6bd30747aee71f91ced5a57fce8bf; EUR4b4ef3cbe83c26b0752c11d05c866a7345b5db93b8011af091d9e8ad68d77976.
- Protected paths tidak berubah:cbot_sources,cbot_connectivity,cbot_bridge,src/fx_scanner/execution,config/frozen.
- CI umum masih gagal collection:import OrderSide dari fx_scanner.execution.models. File tersebut tidak disentuh. PASS riset bukan seluruh repository CI green.
- Audit publikasi memeriksa JSON parity terhadap artifact, syntax main/dashboard, dan scope cBot.

## Runtime, deployment, rollback

Hasil dipush ke main; Streamlit mengikuti branch itu. Panel penelitian terbaru telah teramati saat replay berjalan. Setelah publikasi akhir, periksa status RESEARCH_ONLY,10juta kombinasi keluarga terakhir,0konfigurasi lolos, dan alasan penolakan. Ini hasil penelitian negatif, bukan validasi live order/cBot.

Tidak ada order atau perubahan VPS bridge/cTrader. Tidak perlu restart VPS/cBot untuk penelitian scanner. Publisher market-data read-only sebelumnya tetap; model baru yang gagal tidak dipromosikan lewat feed.

Rollback UI:buat commit baru yang memulihkan hanya main.py dan module dashboard dari f5541def, sebelum kelanjutan ini. Simpan hasil/protokol untuk audit dan perubahan lain yang masuk bersamaan. Jangan reset seluruh repo atau mengubah frozen strategy, account binding, checkpoint.

Ruang konfigurasi yang diuji belum memberi kandidat utama dengan profit stabil; bukan bukti semua pendekatan reversal pasti rugi.

