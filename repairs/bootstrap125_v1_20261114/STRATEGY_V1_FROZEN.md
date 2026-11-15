# RIZAN BOOTSTRAP125 V1 — frozen 14 November 2026

Identitas rilis: `RIZAN_BOOTSTRAP125_V1_FROZEN_20261114`.
Kontrak rilis: `b6014ae7d456b10f88671f1e58e605509a20771386c72f3ca7ae8b210bde0128`.
Inti pertumbuhan berasal dari konfigurasi Guard47/BUY050 penelitian V1; varian recovery, BTC-only growth, dan hasil pencarian tambahan tidak dimasukkan.

## Fase SEED — akun kecil

- Akun USD hedging; target kondisi awal penelitian $100, leverage penelitian 1:200.
- Hanya EURUSD BUY. Candle M5 yang sudah selesai harus bullish dan close melampaui high 64 candle sebelumnya + 0,05 ATR14 RMA. EMA20 H4 harus di atas EMA80 H4, menggunakan candle H4 selesai.
- Tidak memakai candle berjalan atau data masa depan. Warmup minimal 512 M5 dan 1.024 H4 tertutup; candle penentu diperiksa terhadap M1 broker.
- Hari Senin–Jumat, waktu sinyal sebelum 20:00 UTC / 03:00 WIB hari berikutnya.
- Risiko rencana 8% dari nilai lebih kecil antara balance dan equity; memasukkan biaya perencanaan. Ukuran lot dibulatkan ke bawah. Margin masuk maksimal 50% equity. Jika minimum broker terlalu besar, sinyal dilewati.
- SL: jarak terbesar antara 1,25 ATR, jarak entry ke low candle sinyal − 0,05 ATR, dan 0,00005. TP 4R. Perlindungan SL/TP dikirim ke broker dan dipasang ulang dalam harga absolut setelah fill.
- Satu posisi seed; maksimum dua upaya order sehari UTC. Tunggu 5 menit setelah close, atau 60 menit setelah hasil rugi. Tutup setelah 120 menit atau 20:00 UTC, mana yang lebih awal.
- Sinyal masuk kedaluwarsa setelah 60 detik. Persiapan dan persetujuan pengiriman harus tersimpan di VPS sebelum satu permintaan order dikirim. Jika hasil permintaan tidak pasti, bot berhenti membuka order dan mempertahankan intent untuk rekonsiliasi.
- Guard seed menghentikan entry baru setelah DD tercatat ≥60% dan posisi selesai; ini bukan jaminan batas DD keras pada gap/slippage.

## Perpindahan dan fase GROWTH

Perpindahan satu arah terjadi ketika **balance ≥$125 dan equity ≥$125**, posisi seed sudah selesai dan history volume sudah lengkap, serta seluruh posisi/pending order akun kosong. Bot menyimpan fase GROWTH ke VPS dan menunggu ACK penyimpanan. Barulah entry EUR/XAU/BTC dari inti pertumbuhan dibolehkan. Equity mengambang saja tidak cukup.

Setelah GROWTH, penurunan saldo di bawah $125 tidak mengaktifkan seed lagi, termasuk setelah restart. Checkpoint tidak boleh dihapus untuk mereset fase. Satu instance per akun/kontrak; jangan mengoperasikan dua cBot pada akun yang sama.

Inti pertumbuhan memakai file source beku yang disertakan: XAU compression/displacement, EUR, dan BTC original + break40, dengan weekend policy BTC asli. Batas nominal risiko terbuka gabungan 20,75%; Guard47 memakai cushion terhadap 47% peak, cadangan risiko minimum 3%, dan penyesuaian margin. Ini tetap konfigurasi agresif dan bukan batas DD maksimum 60% yang dijamin.

Pengali/parameter utama: XAU risk 1,65, SL 2,4 ATR, TP 4,5R; EUR risk 0,8, stop 0,845, target 10, BE3; BTC risk1, BUY target12/stop2, SELL target2/stop1,5, batch32 selama180detik, risk batch0,025, margin batch0,1, zone0,5, BUY128jam/SELL8jam. Rincian lengkap ada dalam `source/FrozenR3.cs` dan engine masing-masing.

Arah macro tambahan Mode off sesuai V1. Filter eksternal yield/news bawaan XAU tetap dipertahankan dan menggunakan sumber nyata dari bridge; snapshot palsu penelitian tidak dikirim di live. Feed BTC mempertahankan kontrak 7D dan batas freshness entry 5 detik asli. Data tidak lengkap/terlambat memblokir entry baru; exit dan perlindungan broker tetap berjalan.

## Bukti historis dan batasnya

Hasil penelitian arsip V1 (bukan replay broker baru pada rilis ini): continuous synthetic M1 2019–13 November 2026 03:00 UTC / 10:00 WIB berakhir **$1.662.133.293,08**, max equity DD **56,6721%**. Belum sampai 30 November karena tanggal tersebut belum terjadi pada tanggal rilis.

Annual reset $100, skenario biaya B dalam arsip:

| Tahun | Saldo akhir USD |
|---|---:|
| 2019 | 2.884,62 |
| 2020 | 2.863,72 |
| 2021 | 244,34 |
| 2022 | 1.698,48 |
| 2023 | 2.198,01 |
| 2024 | 1.650,28 |
| 2025 | 162,13 |
| 2026 sampai cutoff | 110,99 |

Hasil ini tidak cukup untuk menyebut strategi robust di semua biaya. Arsip pengujian biaya lebih tinggi mencatat 2024 skenario A saldo $41,60/DD61,565%, dan 2022 skenario B saldo $47,97/DD60,743%. Mesin penelitian memakai jalur harga sintetis M1; asal sebagian flag XAU dan snapshot macro penelitian belum dapat diverifikasi. Karena itu tidak ada klaim kesetaraan hasil tersebut dengan live cTrader.

Rilis ini memverifikasi kompilasi cTrader dan alur fungsi, bukan menjalankan ulang seluruh 2019–2026 pada tick FP Markets. Perbedaan data broker, spread, komisi, swap, margin bertingkat, likuiditas, fill dan waktu bridge dapat mengubah entry/hasil. $125 adalah ambang fase, bukan jumlah modal yang menjamin semua basket bisa dibuka.


## Pembekuan dan perbaikan teknis1.0.1

Aturan di atas tetap dibekukan pada profil yang sama. Rilis15November memperbaiki struktur ekspor/paket `.algo` sehingga native cTrader Console mengenalinya sebagai cBot. Source berada di ZIP, bukan tertanam dalam biner. Pengujian mencakup startup seluruh empat engine, schema checkpoint, Cloud tanpa LocalStorage persisten, kegagalan storage desktop, intent tidak pasti, exit selama bridge offline, history parsial/terlambat dan cooldown rugi. Total86 assertion C# dan9 test bridge lulus. Ini verifikasi fungsi; bukan bukti keuntungan native/live.
