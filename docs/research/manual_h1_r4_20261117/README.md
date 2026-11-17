# RIZAN H1 Trend Capture R4

Buka Laporan_H1_R4.html untuk aturan, hasil, gambar dan keterbatasan.
Status EXPERIMENTAL_MANUAL_AID_NOT_LIVE_APPROVED. Tidak mengubah scanner/cBot.

Reproduksi menggunakan arsip sumber pengguna yang tersedia pada folder research_manual_r1/frozen-inputs/data, dengan source_manifest.json dan input_loader.py yang disertakan. SHA256 setiap input tercatat di evidence/input_metadata.json. Tidak ada data/kredensial broker di paket ini.

1. Python3.12+numpy+pandas+matplotlib. Jalankan prepare.py /ABS/SCRATCH (arsip CSV harus berada di research_manual_r1/frozen-inputs/data di dalamnya).
2. Kompilasi engine.cpp dengan g++ -O3 -fopenmp -std=c++17. Kerja di research_manual_h1_r4, jalankan engine screen lalu engine validate.
3. Untuk extended, tambah -DEXTENDED_HOLD; buat folder extended dengan inputs menunjuk ke inputs induk. Jalankan screen, validate, select.py /ABS/extended, baru engine final results/frozen.csv. Jangan menyeleksi memakai2025.
4. engine audit, kemudian audit.py /ABS/extended --extended memeriksa600 replay independen. Tanpa --extended untuk intraday. Tambah -DGAP_STRESS untuk sensitivitas gap yang sangat konservatif.
5. prepare.py /ABS/SCRATCH 2024-06-18T12:06:00Z research_manual_h1_r4_prefix membentuk audit prefix.

Perhitungan PF adalah net-R, target adalah USD per ons (jarak harga), bukan nominal profit akun. Carry dan spread sintetis; FP native belum diverifikasi.
