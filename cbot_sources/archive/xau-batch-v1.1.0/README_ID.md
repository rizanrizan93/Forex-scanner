# RizanXAUBatch v1.1.0 — 12 Oktober 2026

cBot XAU native dengan batch per tahap, menggantikan pengiriman child satu per satu. Jumlah unit mengikuti sizing equity dan batas risiko/margin frozen. Child tetap satuan internal 1 oz (0.01 lot); satu kelompok memakai SL/TP absolut bersama. Maksimum satu permintaan broker per detik; kelompok besar dapat dipecah sesuai batas volume broker. EUR tidak diubah.

## Pemakaian
1. Impor RizanXAUBatch_v1.1.0.algo di cTrader.
2. Pilih XAUUSD, M1, akun XAU yang sesuai. Isi nomor akun penuh, Bridge WSS dan token yang sama dengan konfigurasi sebelumnya. Token tidak disertakan dalam paket.
3. Kirim order default **No**. Validasi konfigurasi dan uji demo dahulu sebelum mengaktifkan.
4. Pergantian hanya saat posisi dan pending lama sudah kosong. Jangan jalankan bersama instance XAU lama. Checkpoint basket aktif versi lama tidak dimigrasikan; checkpoint flat dapat dimigrasikan.

## Validasi yang sudah dilakukan
- Build .algo berhasil. Checksum dokumen portable PDB cocok dengan source yang disertakan.
- 32 fixture runtime: batch, proteksi, ACK, kegagalan, recovery, migrasi dan pembatasan volume.
- 24 fixture ACK dengan waktu buatan; bukan pengukuran latensi live.
- 1000 pemeriksaan sizing dibanding helper simulator sebelumnya.
- Semua hasil Pass. Fixture memakai API stubs; bukan backtest host cTrader.

## Hasil historis: batas bukti
Simulator batch sebelumnya untuk 2016–2025, modal $100 dan leverage 1:100, tanpa delay tambahan menghasilkan saldo $24,243–$24,313, DD sekitar 48.71%, 551 basket (rata-rata 4.59 per bulan). Angka ini adalah hasil **simulator sebelumnya**, bukan hasil replay native file .algo ini. Native backtest historis 10 tahun belum dilakukan; saldo $24,000 tidak dijamin. Batch mengurangi jumlah permintaan broker, tetapi toleransi delay/biaya dari simulator tetap sensitif.

Model eksekusi: XAU_BATCH_STAGE_FIXED_REF_WAL_V1. FrozenCore tetap sama; durable ACK diperlukan sebelum pengiriman. Migrasi atau hasil tidak pasti dikarantina agar tidak mengulang order.

## Source dan fixture
Project cBot: source/RizanXAUBatch/RizanXAUBatch/RizanXAUBatch.csproj (net6.0, cTrader.Automate 1.0.21).
Fixture: dotnet run --project tests/BatchRuntimeTests.csproj; ulangi untuk BatchAckTests dan SizingParityTests (net8.0). VerifyBuild.cs adalah utilitas pembuktian source build; bukti JSON berasal dari build asli.
