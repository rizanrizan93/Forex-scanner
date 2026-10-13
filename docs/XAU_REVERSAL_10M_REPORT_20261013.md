# RIZAN XAU reversal scanner — penelitian 10 juta konfigurasi

Tanggal: 13 Oktober 2026. Engine khusus tampilan scanner; tidak mempunyai otoritas atau pengaruh execution. Source, parameter, hash, checkpoint, risk, SL/TP dan strategi cBots XAU/EUR tidak berubah.

## Hasil

Replay harga XAUUSD 2016–2025: 10.000.000 tuple parameter berbeda dievaluasi tepat dengan histogram kumulatif, bukan sampling acak 10 juta atau klaim 10 juta strategi independen. Tuple berbeda dapat menghasilkan observasi yang sama.

| Arah | Jendela WIB | Pengujian akhir 2024–2025 | Slot 1 jam dipilih hanya dari validasi | Pengujian akhir slot 1 jam |
|---|---|---|---|---|
| BUY | 19:00–01:00 | 111/135 = 82.22% | 22:00–23:00 | 31/40 = 77.50% |
| SELL | 19:00–01:00 | 225/312 = 72.12% | 20:00–21:00 | 53/69 = 76.81% |

Probabilitas mengukur reaksi 0,5 ATR H1 dari close konfirmasi M5, sebelum invalidasi 1 ATR di luar anchor, maksimum 240 menit. Angka ini BUKAN win rate trading atau peluang major reversal. Radius zona 0,5 ATR di sekitar ekstrem 12 candle H1 sebelumnya. BUY mensyaratkan approach minimal 2 ATR; SELL 1 ATR. Candle M5 harus searah; tidak ada minimum wick tambahan. Jam terbaik merupakan jendela observasi, bukan jam pasti reversal.

Jika reaksi ditingkatkan menjadi 1 ATR, keberhasilan OOS kandidat yang sama turun ke 48,9% BUY dan 50,0% SELL. Untuk 2 ATR: 25,9% BUY dan 25,3% SELL. Konfigurasi ini karena itu dipromosikan sebagai peta probabilitas pantulan lokal, tidak sebagai bukti strategi profit atau major reversal andal.

## Validasi dan kausalitas

- Data publik sekunder HistData XAUUSD M1 bid OHLC, commit downloader dikunci 4a3c11b67f97758f6e3f77a3e5905b6aa87367b8. Sumber menggunakan EST tetap UTC−5 tanpa DST; normalisasi ke UTC. Setiap shard memiliki SHA-256 dan daftar bulan berhasil/gagal. Warmup dari Oktober tahun sebelumnya; warmup tidak masuk observasi tahun pengujian.
- Pencarian: 2016–2021. Seleksi berdasarkan Wilson lower bound validasi: 2022–2023. Finalis dikunci sebelum membaca holdout 2024–2025. Pemenang per sisi dipilih dengan aturan validasi yang sama. BUY global awal dipertahankan.
- Support/resistance ekstrem H1 hanya memakai candle yang sudah selesai sebelum candle trigger M5 dibuka. ATR20 H1 dan slope EMA50 H1 juga kausal. Candle M5 harus mempunyai kelima menit OHLC. Histori H1 memerlukan minimal 45 menit tersedia.
- Satu observasi per empat jam per geometri dasar. Tuples antar geometri tetap saling bergantung. Masa resolusi 30/60/120/240 menit, target 0,5/0,75/1/1,5/2 ATR, invalidasi 0,2/0,35/0,5/0,75/1 ATR.
- Resolusi memakai M1 setelah konfirmasi. Apabila target dan invalidasi tersentuh pada menit yang sama: invalidasi dahulu. Gap >5 menit sebelum resolusi dicensor; unresolved valid dihitung sebagai kegagalan, bukan dibuang.
- Parity independen event ledger vs seluruh count/wins/losses train/validation/holdout: PASS untuk BUY dan SELL. Slot per jam dipilih dari validasi saja dengan N minimal 30; angka holdout tidak dipakai memilih jam.
- Bootstrap block bulan holdout 10.000 resample: BUY CI 95% sekitar 77,0–87,2%; SELL 66,8–77,0%. Interval deskriptif, belum mengoreksi seluruh multiple-testing 10 juta konfigurasi atau semua ketergantungan serial.
- Baseline seluruh jam untuk aturan geometri yang sama: BUY 150/190 = 78,9%; SELL 557/823 = 67,7%. Keunggulan jendela waktu bukan klaim signifikansi statistik.
- Tidak memasukkan macro/event yang tidak memiliki provenance point-in-time 10 tahun. Tidak ada biaya broker, spread/commission, P&L, equity scaling, SL/TP order atau backtest cBots yang dioptimasi.

## Engine dan dashboard

- `src/fx_scanner/reversal_zones.py`: fitur bersama dan kontrak 10 juta grid.
- `scripts/research_reversal_10m.py`: replay M1 dan agregasi train/validation/holdout.
- `scripts/profile_reversal_winners.py`: parity event ledger, statistik per jam/tahun dan bootstrap bulan.
- `calibration/reversal_10m_results.json`: hasil, konfigurasi, provenance, sensitivitas besarnya reaksi.
- `src/fx_scanner/reversal_scanner.py`: peta harga BUY/SELL, invalidasi struktural, session, konfirmasi dan fail-closed data stale.
- `scripts/publish_reversal_snapshot.py`: jalur Open API market-data read-only. Allowlist hanya application auth, account discovery/auth, symbols list dan trendbars. Account suffix XAU 4480 tetap diverifikasi. Tidak refresh token, tidak membaca posisi dan tidak mengirim/mengubah/membatalkan order.
- `.github/workflows/reversal-scanner-readonly.yml`: data collector setiap 5 menit hari kerja. Snapshot sanitized dipublikasikan pada branch terpisah `scanner-reversal-snapshots`. GitHub scheduling dapat terlambat; UI menyembunyikan level jika snapshot >420 detik atau data M1 >180 detik. Tidak menggunakan atau restart bridge VPS cBots.
- `src/fx_scanner/reversal_dashboard.py` + `main.py`: panel default XAU → Zona reversal, harga dan waktu WIB, bukti OOS, rincian metode dan unduhan JSON. Jika CDN branch mengembalikan snapshot lama, reader meresolve commit branch lalu membaca URL immutable; timestamp tetap harus fresh.
- `src/fx_scanner/dashboard_frozen_manifest.py` + `frozen_layering_dashboard.py`: metadata tampilan memakai loader hash-verified yang tidak mengimpor execution. Ini mengatasi ImportError tampilan sebelumnya tanpa memperbaiki/mengubah execution/models.py.

Status MAP_READY diverifikasi di broker reader dengan 13.999 bar M1, `execution_authority=False`, lalu di dashboard live. Zona saat verifikasi 13:47 WIB: BUY 4145,30–4156,16; invalidasi 4139,88. SELL 4195,09–4205,95; invalidasi 4211,37. Harga ini adalah contoh snapshot terverifikasi saat itu; baca dashboard untuk pembaruan. Keduanya WAIT_M5_CONFIRMATION dan di luar jendela riset saat verifikasi.

## Pemeriksaan

- 18 automated tests: timestamp aware/reject naive, causal prefix invariance, anchor pre-exists trigger, non-overlap, ambiguous stop-first, censor gap, histogram vs brute-force seluruh 2000 filter, M5 completeness, stale/future/history guards, hash frozen metadata, read-only protocol allowlist.
- Streamlit AppTest: renderer PASS, tabel tampil, exceptions=0.
- GitHub Actions 38357252717 dan 38358459137: seluruh 10 tahun + agregasi 10 juta PASS.
- Profil per tahun run 38358459232: seluruh 10 shard PASS dan parity PASS; tahap save awal gagal karena folder artifact belum dibuat. Diperbaiki, agregasi lokal identik PASS; workflow pengulangan mengonfirmasi fix.
- Reader data live run 38358656994: PASS, MAP_READY. Pagination tidak menganggap halaman 999/1000 sebagai akhir histori.
- CI umum mempunyai failure ImportError OrderSide/ExecutionMode pada execution/models.py yang telah ada sebelum riset ini; source execution tidak diubah.

## Deployment dan rollback

Dashboard Streamlit mengambil main otomatis. Tidak perlu mengganti .algo atau restart cBots/VPS. Runtime scanner baru adalah read-only dan tidak memengaruhi cBots.

Rollback: disable workflow XAU Reversal Scanner Read Only di GitHub Actions, lalu revert commit riset/dashboard bila ingin mengembalikan UI. Branch snapshot dapat dibiarkan; pembaca akan menandainya stale. Jangan reset checkpoint atau database bridge. Konfigurasi frozen dan .algo tidak perlu dirollback karena tidak berubah.
