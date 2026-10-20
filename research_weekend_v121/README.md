# Audit lanjutan FROZEN WEEKEND V1.2.1

Area ini hanya untuk riset. Tidak ada order broker, perubahan produksi, restart bridge, atau merge main. Binary resmi tetap `EnableTrading=false`. Stress tidak menghasilkan binary trading baru.

Baseline rilis: branch `release/xau-eur-btc-frozen-weekend-v1.2.1`, head `1981615a5e11c21b07a8e7b9900667b3568af4ee`; source native `1d6ad83f285f293b103342073b637fa16e597fb9`. Paket SHA256 `6b5387dbea7c874c60d5479a61ac5f6a29f86c9907a8fdc370a04b72f7c0095f`; binary asli `2384b0526e70ae8a0f3efe2ad26aa99d33627b7a42b8454dbdc44e442b28ec86`.

## Reproduksi

1. Python 3 dengan pandas/matplotlib untuk rekonstruksi input dan laporan; .NET SDK 8.0.426/runtime 8.0.32 untuk replay. Native menggunakan cTrader.Automate 1.0.21 dan Microsoft.NETCore.App.Ref 6.0.36.
2. Tempatkan repo sebagai `repo/` dan SDK sebagai `dotnet/` di bawah satu folder kerja. Simpan tiga input di folder saudara `inputs/`: `xau_2012_2026.csv`, `eur_2012_2026_recovered.csv`, `BTCUSD_M1.csv`. Rekonstruksi EUR menggunakan skrip arsip `portfolio_weekend/...zip/inputs_rebuild/`; jangan memakai suffix EUR lama yang terpotong. Provenance dan checksum input ada di paket beku.
3. `python repo/research_weekend_v121/prepare_runner.py` mengekstrak paket ke work/ dan membuat overlay replay terpisah. Empat belas file source di work/ harus identik dengan manifest beku. legacy_work/ adalah diagnostik yang secara eksplisit memakai BtcEngine lama, dengan adapter kosong untuk kompilasi timer host baru.
4. `python repo/research_weekend_v121/work/run_local.py /absolute/path/dotnet replay`; lakukan juga pada `legacy_work/`.
5. `python repo/research_weekend_v121/run_batch.py`. Path A/B normal wajib identik penuh dengan BrokerHistory asli; assertion juga membandingkan saldo, DD, PF, dan jumlah basket. Ekstrak seluruh ZIP baseline beku ke folder kerja saudara `frozen/`, termasuk dua file `_RAW.json.gz`, CSV dan source, untuk pemeriksaan dan pembuatan laporan ini.
6. `python repo/research_weekend_v121/audit_ledger.py`; `python repo/research_weekend_v121/summarize_results.py`. Semua output riset berada di `research_weekend_v121/`.

Input XAU/EUR mempertahankan bar historis warm-up aslinya. Periode saldo tetap 2019-01-01 sampai bar 2026-10-09 21:58 UTC, cutoff eksklusif 21:59. BTC sampai 15 Oktober hanya menjadi sumber, tidak memperpanjang portfolio.

## Kontrak stress

- NORMAL: biaya 1×, spread asli, broker delay 2 detik, ACK 2 detik.
- COST_15/COST_20: komisi, slippage, financing/swap dikalikan 1,5/2 di seluruh instrumen; spread tetap. Parameter perkiraan biaya dalam strategi tetap beku. EUR virtual-regime tape tetap berasal dari baseline strategi, tidak disetel ulang mengikuti biaya stress.
- NEXT_M1: setiap permintaan entry market (termasuk stage tambahan) ditunda sampai pembukaan menit berikutnya, dengan quote path yang diperbarui tiap detik selama menunggu. ACK tetap 2 detik. Exit SL/TP broker tetap diperiksa setiap detik. ClosePosition/exit mengikuti model baseline tanpa tambahan delay. Ini stress latensi fill entry broker, bukan pengantrean ulang sinyal basi dan bukan perubahan jam sinyal.
- BTC_L2/BTC_L5: hanya leverage estimasi broker BTC menjadi 2×/5×; XAU/EUR tetap 200×. Floor margin konservatif 10× di source tetap utuh; estimasi broker yang lebih mahal membatasi ukuran posisi lewat gate native yang sama.
- Semua kasus mempertahankan modal $100, tanpa top-up; cap risiko entry 20,75%, margin entry 50%, EUR → XAU → BTC. Batas entry bukan hard cap setiap saat atas rasio margin atau floating DD.
- CONTROL: BTC dinonaktifkan hanya pada fake host; data, periode, biaya, path, model ACK dan fill tetap sama.

Runner lama `cfg.Cost` mengalikan spread XAU/EUR. Overlay riset menghapus perkalian itu hanya dari replay adapter; source strategi/baseline ZIP tidak diubah. Diff disertakan di `RUNNER_CHANGE.diff`.

## Perbandingan weekend

Urutan diagnostik yang dilaporkan:

1. LEGACY_7D: BTC tujuh hari dan indikator tujuh hari, memakai engine BTC sebelum pengaman weekend; hanya diagnostik, tidak layak broker weekend-closed.
2. FULL_INDICATORS: pengaman native weekend aktif (blok entry/flat/expiry/lock), tetapi indikator masih membaca bar tujuh hari. Selisih terhadap 1 adalah efek gabungan kebijakan perdagangan weekend, termasuk penutupan, konsumsi sinyal, dan dampak wallet berikutnya; bukan efek penutupan saja.
3. NORMAL: pengaman sama, indikator membuang bar di luar sesi. Selisih terhadap 2 mengukur efek gabungan indikator dan akibat lanjutannya pada sinyal, wallet serta compounding.

`SEQUENTIAL_RESULT_DECOMPOSITION.csv` merekonsiliasi perubahan laba bersih menjadi trade yang hilang/baru, perubahan hasil per unit pada basket yang cocok, dan perubahan kuantitas. Komponen kuantitas juga memuat floor lot, layering dan gate saldo/margin bersama; tidak boleh disebut estimasi murni compounding. Dekomposisi ini bergantung pada urutan eksperimen dan tidak mengklaim alokasi sebab yang unik.

`MATCHED_FRIDAY_EXIT_EFFECT.csv` membandingkan hasil per BTC untuk signal-label yang sama, saat versi kebijakan menutup Jumat 21:30 tetapi diagnostik lama keluar lebih belakangan. Ini subset pasangan yang dapat dibandingkan; tidak mengukur seluruh efek kebijakan weekend.

Semua replay adalah dua path OHLC sintetis, bukan tick bid/ask broker, bukan FULL_PARITY atau bound DD terburuk. Kalender historis/DST dan vintage macro belum disertifikasi. Tidak ada pencarian/optimasi parameter baru di audit ini.
