# Deliverable4 — Reproducible Research Package

Status:paket partial dapat diaudit; penelitian keseluruhan belum complete.

- research_r1/:source akuisisi, audit, feature/signal, tick replay, metrics, bootstrap, walk-forward, sensitivitas, kurva, laporan, tests, dependency versions dan protocol.
- audit/:VPS inventory asli, SHA256 perfile, integrity audit, seluruh execution logs, runtime versions, kegagalan primary crosscheck dan manifest XML resmi.
- macro_raw/:daily Treasury XML yang benar-benar dipakai untuk deskripsi.
- derived/xau_m5.parquet:bar turunan dari arsip yang diuji; bukan data broker FP.
- results/:CSV setiap kandidat/tahun/periode/sesi/jam, log transaksi terkompresi, state/rejections, sensitivity, cost/sizing, dan curve CSV.
- figures/:equity dan floating drawdown OOS serta hourly range.
- baseline_identity/:identitas/checksum/aturan V1 yang relevan untuk audit; tidak memuat credential atau runtimeLIVE.
- reports/:kelima deliverable serta ringkasan utama.

Raw tick2,8GB tidak didistribusikan ulang. Audit mencatat URL arsip pihak ketiga dan checksum exact-bytes yang digunakan. Dataset card pihak ketiga menyatakan lisensi unknown; tidak diberikan klaim lisensi distribusi komersial. Pengguna dapat mereproduksi dengan salinan dataset yang telah dimilikinya. Source Dukascopy resmi menyediakan bid/ask export, tetapi parity tiap file arsip ini belum diverifikasi independen akibatHTTP429.

Ikuti research_r1/README.md. Semua hasil numerik berasal dari perintah yang benar-benar selesai; log tersimpan. Script remote_inventory.py hanya membaca folder tick dan manifest. Analisis berjalan offline di workspace terpisah. Tidak ada import mesinorder, APIbroker, websocketLIVE, restart service atau penulisan databaseLIVE. Branch riset:[research/xau-yield-asia-r1-20261115](https://github.com/rizanrizan93/Forex-scanner/tree/research/xau-yield-asia-r1-20261115). Main dipin saat audit pada7b6f5095d42fe20df37d262e440643ca867a19e7.

AttachmentSHA256:7f58f6839c21785cdcce2c629acd5a2b009593f47dabb6effd8a1b0225a22619. ZIPV1SHA256:0bd93f3f8ad3d64c3171a3fdd49d536b65fd9cfbf69d71e7740d685ac826488c. Seluruh29source file cocok manifest. Source release1.0.1 mengharuskan balance DAN equity≥125, akun flat, seed tercatat dan ACK fase tersimpan sebelum GROWTH; equity mengambang saja tidak cukup. Source file tidak membuktikan instanceLIVE yang sedang aktif atau parity hasil broker.

Untuk menyelesaikan penelitian dibutuhkan:(1)XAUbid/ask April–November2026 dan auditgap yang lebih kuat;(2)histori intraday nominal2Y/10Y/TIPS, actual availability dan licensed ICE DXY atau proxy enamFX lengkap;(3)arsip release/first-vintage/surprise ekonomi;(4)baseline adapter Frozen point-in-time dan data lintasXAU/EUR/BTC beserta kontrak/biaya/margin historis. Tidak perlu mengubahLIVE untuk menambah data tersebut.
