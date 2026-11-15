# RIZAN BOOTSTRAP125 V1 — rilis1.0.1

Strategi dibekukan14November2026; perbaikan ekspor dan audit15November2026 WIB. **Unduh ulang `.algo` versi1.0.1 untuk mengganti1.0.0.** Nama cBot tetap `RizanBootstrap125V1`.

## Yang sudah selesai

| Bagian | Bukti |
|---|---|
| Paket `.algo` | SDK build lulus; native cTrader Console5.10.1.0 kini melaporkan **Type=cBot** |
| Keaslian unduhan | File yang dikirim persis file uji native, SHA256 cocok |
| Alur C# | **86 assertion lulus**, termasuk startup empat engine, signal→protected order pada broker simulasi, minlot/risk, exit/cooldown, intent/ACK, Cloud dan restart |
| Bridge | **9 test lulus**, termasuk SQLite CAS, lost ACK, lease, timestamp dan seluruh schema checkpoint C# |
| VPS terbaru |15November2026 **18:31WIB**: Bootstrap125 dan BUY050 running, NRestarts0; WSS autentikasi/ACK/reconnect/heartbeat lulus |
| Feed VPS | BTC ready, snapshot macro tersedia; health baru sekitar2,6detik saat audit |
| Order nyata dari uji rilis | **0** |

Pemeriksaan sebelumnya belum menangkap paket1.0.0 yang dilaporkan Indicator oleh Console. Rilis1.0.1 menggunakan satu kelas Robot publik dan paket biner tanpa source tertanam; source lengkap tersedia dalam ZIP. Rumus/isi fungsi entry, SL/TP, sizing, basket, Guard47 dan handoff125 dibandingkan dengan rilis awal dan tetap sama. Kontrak checkpoint/label tetap kompatibel.

## Perpindahan otomatis

**SEED:** EURUSD BUY breakout M5 + trend H4. Risiko rencana8%, margin maksimal50%; volume dibulatkan ke bawah dan minimum lot yang tidak terjangkau dilewati.

**GROWTH:** inti V1 XAUUSD/EURUSD/BTCUSD + Guard47. Perpindahan terjadi saat **balance dan equity sama-sama ≥$125**, seluruh posisi/pending kosong dan transaksi seed selesai dicatat. Bot menunggu ACK penyimpanan fase di VPS sebelum mengizinkan order pertumbuhan. Profit mengambang saja tidak cukup.

Fase GROWTH tidak kembali menjadi SEED ketika saldo turun atau bot restart. $125 adalah ambang perpindahan, bukan jaminan semua basket terjangkau. Guard47 bukan jaminan DD live selalu di bawah60%.

## Memasang satu instance

1. Impor `RizanBootstrap125V1.algo` versi1.0.1. Pada Android, ketuk file lalu pilih cTrader atau gunakan Upload dalam menu Algo bila tersedia; alternatifnya impor lewat Windows/Mac dengan sinkronisasi cTID.
2. Gunakan akun USD hedging, dengan simbol EURUSD/XAUUSD/BTCUSD tersedia. Isi **Nomor akun penuh** dan **Token bridge BUY050 yang sudah digunakan**. Token tidak disertakan dalam unduhan. Akun di luar allowlist VPS perlu ditambahkan oleh admin.
3. URL utama default: `wss://rizan-bridge.duckdns.org:25345/bootstrap125/`; BTC: `wss://rizan-bridge.duckdns.org:25345/bootstrap125/btc`. Token BTC boleh kosong untuk menyalin token utama.
4. Jalankan awal dengan **Kirim order=false**, tunggu Journal menunjukkan checkpoint/feed siap serta history broker selesai dimuat. Untuk mulai trading, atur **Kirim order=true** pada satu instance itu. Tidak perlu mengganti bot ketika mencapai125.
5. Bot lama harus flat dan dihentikan sebelum memakai V1 pada akun yang sama. Jangan membuat satu instance untuk setiap pair dan jangan menjalankan V1 berdampingan dengan BUY050 lama.

**Status akun saat audit:** connected0 dan belum ada checkpoint trading Bootstrap125 sebelum probe diagnostik. Jadi bridge tersedia, tetapi cBot ini belum terkonfirmasi aktif pada akun Anda. Tidak ada order broker nyata yang dijalankan untuk pengujian; pemeriksaan demo broker masih diperlukan untuk memastikan fill/biaya/margin aktual.

## Status replay dan klaim robust

**Replay tick broker penuh tiga pair2019–2026 belum selesai dan belum tersertifikasi.** Inventaris VPS2026 baru memuat XAU Januari–Maret, EUR Januari–April, dan tidak memiliki folder tick BTC. Adapter point-in-time terisolasi juga diperlukan; jangan mengarahkan backtest historis ke bridge/checkpoint live.

Hasil arsip V1 menggunakan simulasi sintetis M1 sampai13November2026 10:00WIB. Kenaikan annual reset yang pernah dilaporkan tidak berlaku untuk semua skenario biaya: arsip biaya lebih tinggi juga memuat tahun rugi. Rilis ini tidak mengklaim angka profit, saldo, DD atau trade bulanan baru dari replay native.

ZIP memuat source lengkap, bridge/deployment, tests, manifest SHA256, `STRATEGY_V1_FROZEN.md`, `PANDUAN_CTRADER.md`, `CHANGELOG_1_0_1.md`, `NATIVE_REPLAY_STATUS.md`, dan bukti audit. Pembacaan metadata native tidak sama dengan pengujian order live.

Petunjuk resmi impor: https://help.ctrader.com/cbots/how-tos/install-a-cbot/
