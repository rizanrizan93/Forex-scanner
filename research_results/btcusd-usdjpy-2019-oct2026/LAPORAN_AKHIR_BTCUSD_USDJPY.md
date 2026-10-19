# Hasil akhir pencarian BTCUSD dan USDJPY — $100 menuju $100.000

Status: **TARGET TERCAPAI PADA MODEL M1 DENGAN PARAMETER BERBEDA; BUKTI BROKER/TICK BELUM TERSEDIA.**

Periode akun: 1 Januari 2019 sampai 15 Oktober 2026. Akun USD100 terpisah per instrumen, tanpa top-up. Angka di bawah bukan hasil portofolio gabungan dan bukan replikasi frozen XAU–EUR $90 juta.

## Hasil yang direkonsiliasi

| Metrik | BTCUSD POSITION 792291 + goal lock | USDJPY AGGRESSIVE 823347 + goal lock |
|---|---:|---:|
| Modal awal | $100 | $100 |
| Saldo akhir | **$105.967,79** | **$107.199,61** |
| Target kas pertama tercapai (UTC) | 2025-08-11 00:00 | 2025-02-20 17:00 |
| Floating DD model | **58,44%** | **90,89%** |
| Balance DD | 54,99% | 86,54% |
| Profit factor | 2,2033 | 3,0634 |
| Basket tertutup | 67 | 102 |
| Basket menang | 22 | 50 |
| Win rate | 32,84% | 49,02% |
| Penambahan stage | 0 | 0 |
| Stop-out model | 0 | 0 |
| Saldo jika terus trading tanpa goal lock | $85.424,59 | $69.856,61 |

Aturan goal lock sama untuk kedua akun: **sesudah satu basket benar-benar ditutup dan komisi serta financing model diselesaikan, jika saldo kas ≥ $100.000, jangan buka transaksi lagi.** Kas tetap utuh sampai akhir periode, tanpa bunga, penarikan, clipping saldo, atau memilih tanggal puncak. Floating equity tidak dipakai untuk memicu penghentian.

Ambang100k berasal dari tujuan pengguna. Aturan varian dinyatakan sebelum replay varian, tetapi dipertimbangkan setelah melihat hasil pencarian historis. Karena itu, ini tetap penelitian eksploratif dalam sampel, bukan strategi yang dibekukan sebelum periode uji atau hasil out-of-sample murni.

## Konfigurasi tepat

| Parameter | BTCUSD 792291 | USDJPY 823347 |
|---|---|---|
| Family | structure_break | break_retest |
| Timeframe sinyal | D1 | H1 |
| Lookback | 16 bar | 16 bar |
| Threshold index | 0 (padding0ATR) | 2 (padding0,2ATR) |
| Filter tren | H4 EMA20/80 searah | H4 EMA20/80 searah |
| Arah | BUY saja | BUY dan SELL |
| Sesi UTC | Semua | 00:00–07:59 |
| ATR | Wilder14 pada timeframe sinyal | Wilder14 pada timeframe sinyal |
| Stop awal | 0,75ATR | 1,5ATR |
| Target | 12R | 8R |
| Batas durasi | 32 bar D1 | 16 bar H1 |
| Risiko nominal/basket | 8% equity | 30% equity |
| Anggaran margin | 50% equity | 75% equity |
| Layering | Tidak ada | Tidak ada |
| Break-even | Tidak ada | Trigger1R; perubahan berlaku bar berikutnya |
| Leverage model | 1:10, **belum dibuktikan** | 1:200 |
| Minimum/step volume | 0,01BTC | 1.000USD base units |
| Maksimum volume | 100BTC | 2.000.000USD base units |
| Penghentian akun | Kas tertutup ≥ $100.000 | Kas tertutup ≥ $100.000 |

BTC: close D1 melewati high tertinggi16 bar sebelumnya, dengan tren H4 naik yang sudah closed. USDJPY: break pada bar sebelumnya diikuti retest dan penutupan kembali melewati level, arah candle dan tren memenuhi kondisi source; SELL simetris. Rumus yang berwenang adalah C++ dalam masing-masing ZIP, bukan ringkasan teks ini.

Entry setelah candle sinyal closed memakai open M1 berikutnya yang tersedia. Spread/slippage dikenakan menurut sisi BUY/SELL; SL/TP ambigu dalam satu M1 memakai STOP_FIRST. Gap stop memakai open yang lebih buruk. Batas volume, margin, komisi dan biaya financing masuk perhitungan sizing. Pemeriksaan goal hanya dilakukan setelah pencatatan transaksi tertutup.

## Ketahanan terhadap asumsi

Saldo akhir dengan parameter dan ambang kas sama:

| Skenario | BTCUSD792291 | USDJPY823347 |
|---|---:|---:|
| Biaya model normal | $105.967,79 | $107.199,61 |
| Biaya1,5× | $43.635,14 | $38.613,56 |
| Biaya2× | $31.025,15 | $7.388,33 |
| Delay ke M1 berikutnya, minimum1menit | $106.424,91 | $461,67 |
| BTC leverage1:2 | $623,14 | Tidak berlaku |

Biaya1,5×/2× mengalikan komisi, slippage dan financing, **bukan spread**. Delay ini bukan simulasi2detik karena data M1 tidak menyediakan urutan tick.

Asumsi BTC: spread5bp, slip1bp/sisi, fee5bp/sisi, financing debit3bp notional/hari prorata. USDJPY: spread0,01JPY, slip0,001JPY/sisi, komisiUSD0,00003/baseunit/sisi, financing debit0,01%notional/hari prorata. Spesifikasi dan sejarah kontrak broker belum dibuktikan; tidak boleh disebut hasil akun RAW yang tervalidasi.

Temuan material: **target tidak bertahan pada biaya1,5× untuk kedua konfigurasi tersebut.** USDJPY memerlukan toleransi drawdown model sekitar91%; dengan delay minimum1menit hasilnya jauh lebih rendah. BTC sangat bergantung pada asumsi leverage1:10. Hasil ini belum membuktikan setup yang kuat untuk penggunaan live.

## Cakupan pencarian

Empat universe × satu juta konfigurasi per instrumen dievaluasi pada periode penuh: GENERIC, SESSIONS, POSITION, dan AGGRESSIVE. Total8juta baris hasil penuh. Setiap universe memakai1juta tuple aktif unik, terdiri dari5shard disjoint200ribu. Ada tumpang tindih kecil antar-universe; jumlah ini bukan8juta keluarga independen. Tiga universe awal memiliki2.998.022 tuple unik gabungan per instrumen.

Pencarian awal: tidak ada saldo akhir100k tanpa penghentian akun. Pencarian agresif tambahan:26 konfigurasi BTC berakhir≥100k, nol USDJPY. BTC terbaik tanpa goal lock mencapai **$463.448,59**, floating DD89,22%, PF1,3761,66basket; biaya1,5× turun menjadi$266.665, biaya2×$37.315, leverage1:2$1.099,81.

Parameter identik dipasangkan lintas instrumen pada satu juta konfigurasi agresif: **nol mencapai100k di kedua instrumen tanpa goal lock**. Kandidat di tabel utama memakai konfigurasi dan family berbeda. Belum ada klaim satu konfigurasi identik memenuhi target kedua market.

Goal lock diperiksa pada seluruh ledger kandidat terpilih yang tersedia, bukan seluruh8juta lintasan:167 kandidat per instrumen pada tiga universe awal, ditambah61 per instrumen pada universe agresif. Ditemukan6 crossing BTC awal,21 crossing BTC agresif, dan1 crossing USDJPY agresif. Seluruh crossing tersebut direplay; sampel ini bukan estimasi jumlah seluruh konfigurasi yang pernah menyentuh100k.

## Data dan batas validitas

BTC berasal dari candle M1 resmi Bitstamp melalui API; seluruh input dibangun ulang setelah perbedaan dengan arsip sekunder ditemukan. Candlestick tanpa volume yang diterbitkan provider dipertahankan sebagai data provider, bukan interpolasi lokal. USDJPY berasal dari HistData M1, konversi fixedEST+5jam keUTC. Kualitas kalender/gap USDJPY masih PARTIAL. Rentang berakhir15Oktober2026, bukan31Desember2026.

Hash input CSV kanonik:

- BTCUSD: c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504
- USDJPY: aa92c0d449860f86026df7840be9ab583be99aa017c7cac5abe546cfd84845b5

Ini **OHLC M1, bukan tick bid/ask broker**. Spread adalah model; tidak tersedia verifikasi ACK, partial fill, rejection/recovery, kedalaman likuiditas, margin bertingkat, pembulatan grid/stop minimum, atau swap broker historis. DD adalah statistik urutan/envelope OHLC pilihan engine, bukan batas atas matematis atas semua urutan tick. Tidak ada feed makro pada strategi baru ini.

Ada kebijakan capital-floor setelah basket tertutup yang menonaktifkan akun jika kas tidak mencukupi ambang model. Kebijakan ini bukan jaminan broker dan tidak menguji reaktivasi akun jika harga BTC kemudian turun. Nol stop-out model tidak membuktikan nol margin call broker.

Seleksi memakai periode penuh sehingga risiko overfit besar. Segmen restart$100 setelah pemilihan bukan OOS yang tidak tersentuh. USDJPY823347 yang dimulai ulang pada2025 berakhir hanya$7,94; BTC792291 pada segmen itu tidak trading karena batas minimum/margin. Angka tersebut tidak disembunyikan dan tersedia di tabel stres.

## Rekonsiliasi dan regresi

- Semua parameter pemimpin direkonstruksi dari source dan dibandingkan dengan tabel million-row.
- Setiap transaksi goal-lock BASE identik dengan prefix ledger baseline: harga, volume, waktu, komisi, financing, PnL dan kas.
- Tidak ada transaksi setelah crossing kas pertama; overshoot target dipertahankan.
- PnL dan kas dihitung ulang independen; bukti per kandidat di EXACT_PREFIX_AND_CASH_PROOF.json.
- Regresi perubahan harga masa depan:500konfigurasi per universe/instrumen; hasil sebelum cutoff sama persis. Ini cakupan pengujian, bukan bukti formal setiap jalur broker.
- Fixture memeriksa sisi bid/ask model, STOP_FIRST, gap SL, volume minimum, delay, penambahan stage dan rekonsiliasi.
- Beberapa percobaan workflow gagal pada pemilihan/nama paket, lalu diperbaiki. Satu run goal agresif berhasil menghitung keuangan, menyimpan VPS dan memverifikasi checksum, tetapi publikasi file kecil ke branch terkena konflik409 akibat perubahan branch bersamaan. Pipeline delivery akhir memeriksa tiga tahap sukses tersebut dan merekonsiliasi kembali kedua ledger. Kegagalan publikasi tidak dinyatakan sebagai kegagalan finansial atau disembunyikan; checksum paket dan bukti delivery menjadi rujukan.

Tidak ada perubahan cBot live, order broker, bridge, env produksi, risk live, dataset tick asli, atau merge ke main.

## Artefak dan reproduksi

Branch: [research/btcusd-usdjpy-million-2019-2026](https://github.com/rizanrizan93/Forex-scanner/tree/research/btcusd-usdjpy-million-2019-2026).

- [Paket lengkap pencarian awal dan rekonsiliasi](https://github.com/rizanrizan93/Forex-scanner/actions/runs/39217369074)
- [Paket portabel awal, seluruh tabel3juta/instrumen](https://github.com/rizanrizan93/Forex-scanner/actions/runs/39218690359)
- [Audit2juta konfigurasi agresif dan parameter identik](https://github.com/rizanrizan93/Forex-scanner/actions/runs/39220603070)
- [Goal lock awal dan prefix proof](https://github.com/rizanrizan93/Forex-scanner/actions/runs/39220176510)
- [Goal lock agresif dan prefix proof final](https://github.com/rizanrizan93/Forex-scanner/actions/runs/39230334699)
- [Commit pipeline goal lock final](https://github.com/rizanrizan93/Forex-scanner/commit/addf60c1a8aa809ada0c8773a37c47fe542716fd)

Folder VPS:
 /home/Rizanrizan/rizan-ticks/REPLAY_RESULTS/btcusd-usdjpy-million-2019-oct2026/

Subfolder final-39217369074/portable, aggressive-million, settled-goal-100k, dan aggressive-settled-goal-100k menyimpan laporan/paket penelitian terpisah dan checksum. Dataset asli tetap dipertahankan.
