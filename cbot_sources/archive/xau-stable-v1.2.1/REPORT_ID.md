# Konfigurasi XAU: pencarian kembali target $24.000

Kandidat penelitian v1.2.1. Core sinyal tetap identik, profil risiko/eksekusi berbeda. Tidak dipasang ke VPS/cTrader live. EUR tidak berubah. Hasil berikut dari modal awal $100, leverage 1:100, periode 2016–2025, 3.550.992 bar M1 termasuk warmup.

## Mengapa saldo sebelumnya turun

Versi stabil v1.2.0 menurunkan maksimum risiko basket dari 12,5% ke 10%, menambahkan jeda rugi 3 hari, serta mengubah cadangan biaya dan referensi harga pengiriman. Ukuran posisi berbasis equity dan pembulatan minimum volume mengubah jalur compounding. Angka $24.000 bukan konstanta yang bisa dipertahankan setelah profil eksekusi berubah.

Perbandingan dengan v1.2.0 mengisolasi kenaikan batas risiko saja: kandidat ini memakai 12,1%, sementara cooldown, cadangan biaya, referensi pengiriman dan core sinyal tetap sama. Penurunan margin dari 50% ke 47,5%/45% pada risiko 12,5% masih menghasilkan satu DD delay2 >50%; tidak dipilih.

## Konfigurasi kandidat

- Risiko maksimum per basket 12,1%, bukan per child/order; quantity mengikuti min(balance,equity), free margin dan budget basket.
- Margin sizing maksimum 50%; bukan jaminan floating margin selalu di bawah 50%.
- Jeda entry baru 3 hari kalender setelah basket selesai dengan net loss.
- Batch 1 request/detik; referensi pengiriman boleh bergeser maksimal 0,20R sebelum first fill. Setelah first fill, geometry SL/TP basket tetap.
- Cadangan slippage $0,10/oz/sisi dan komisi $0,06/oz/sisi untuk sizing.
- Signal core, ATR/structural stop, target dan tahap equity tetap dari versi stable sebelumnya. File config.json adalah dokumentasi profil tertanam, bukan preset yang bisa diimpor lewat Parameters.

## Semua skenario kandidat

| Biaya aktual | ACK detik | Jalur OHLC | Saldo akhir | DD sintetis | Basket | Order | Basket/bulan |
|---|---:|---|---:|---:|---:|---:|---:|
| 1× | 0 | ADVERSE_FIRST | $27,648.13 | 49.52% | 406 | 417 | 3.38 |
| 1× | 0 | FAVORABLE_FIRST | $27,621.76 | 49.51% | 406 | 417 | 3.38 |
| 1× | 2 | ADVERSE_FIRST | $31,305.62 | 48.66% | 406 | 416 | 3.38 |
| 1× | 2 | FAVORABLE_FIRST | $25,831.45 | 48.56% | 406 | 418 | 3.38 |
| 1× | 5 | ADVERSE_FIRST | $62,199.48 | 49.00% | 406 | 415 | 3.38 |
| 1× | 5 | FAVORABLE_FIRST | $12,508.21 | 44.93% | 403 | 413 | 3.36 |
| 2× | 0 | ADVERSE_FIRST | $6,946.30 | 47.50% | 406 | 417 | 3.38 |
| 2× | 0 | FAVORABLE_FIRST | $6,949.17 | 46.57% | 406 | 417 | 3.38 |
| 2× | 2 | ADVERSE_FIRST | $10,361.21 | 43.72% | 406 | 416 | 3.38 |
| 2× | 2 | FAVORABLE_FIRST | $6,517.11 | 46.16% | 406 | 417 | 3.38 |
| 2× | 5 | ADVERSE_FIRST | $19,971.73 | 46.92% | 406 | 414 | 3.38 |
| 2× | 5 | FAVORABLE_FIRST | $4,627.72 | 46.33% | 402 | 411 | 3.35 |

## Makna dan batas hasil

Target nominal $24.000 dan DD≤50% tercapai pada biaya normal, tanpa delay tambahan dan ACK2 detik, untuk dua jalur OHLC yang diuji. Angka delay menunjukkan toleransi yang disimulasikan, bukan pengukuran latency live. ACK5 detik dan biaya2× adalah stress test; target $24.000 tidak berlaku pada semua stress test. DD adalah maksimum yang diamati dalam replay, bukan hard stop atau batas yang dijamin.

Pemilihan memakai periode 2016–2025 yang sama dengan penilaian. Risiko 12,1% adalah kandidat hasil pencarian, belum divalidasi out of sample. Perbedaan kecil risiko dapat melintasi batas integer volume dan mengubah jalur transaksi. Tidak ada jaminan hasil atau DD live sama.

Replay menjalankan source RizanRobot melalui API broker simulasi, adapter boundary M1, signal/confirmation causal precompute, dan dua lintasan OHLC 1 detik. Ini bukan tick replay atau backtest di host native cTrader. 12 pemeriksaan signal parity causal; 33 fixture recovery/ACK/budget/protection lulus. PDB build cocok dengan seluruh source yang dikirim; seluruh report dan ledger delay2 dari source final cocok dengan riset mutable.

Proxy biaya RAW: spread max($0,11, rawspread−$0,14), slippage $0,05/oz dan komisi $0,03/oz/sisi pada faktor1. Faktor2 menggandakan spread, slippage, komisi dan swap aktual, sementara reserve sizing tetap. Ini bukan bukti biaya akun broker Standard/aktual. Makro/event memakai archive dan flag eligibility dari input sebelumnya; snapshot bridge sintetis dianggap fresh, sehingga latency data macro/live tidak diuji.

## Berkas dan penggunaan

File .algo sudah dikompilasi dari source kandidat. Default Kirim order=False; account/WSS/token kosong. Belum ada tindakan di akun live. Patch transport bridge dari sesi koneksi sebelumnya belum digabung: error WebSocket/lease/timestamp tidak diklaim selesai oleh versi ini. Kandidat membutuhkan integrasi patch tersebut serta pemeriksaan host native sebelum menggantikan cBot live.

Paket memuat source, source replay, fixture, JSON report/ledger dan bulan lengkap120, hasil pencarian risiko/margin, stress pembanding, checksum input dan manifest SHA256. Dataset history.csv 266MB tidak diduplikasi; input_prepare.py dan proof hash disertakan. Build .NET6/cTrader.Automate1.0.21; replay/fixture .NET8 dengan API simulasi.
