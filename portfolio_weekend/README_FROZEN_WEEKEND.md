# RIZAN XAU–EUR–BTC Frozen Weekend V1.2.1

Source strategi dibekukan. XAU/EUR tidak diubah dan BTC tetap memakai profil 7844/2269; tidak ada optimasi ulang entry, TP, SL atau risiko. Cap risiko portofolio dikunci pada 20,75%, margin entry 50%, model leverage BTC 10× dan XAU/EUR 200×. Kirim order default OFF. Tidak ada deployment live.

**Batas DD 56% tidak lagi terpenuhi dalam replay versi ini.** Hasil lama $24,54–24,80 juta tidak boleh dipakai sebagai hasil versi dengan aturan akhir pekan. Lihat laporan dan WEEKEND_FINAL_METRICS.csv untuk angka baru.

BTC berhenti entry 60 menit sebelum penutupan mingguan dan mulai ditutup 30 menit sebelumnya. Jadwal berasal dari MarketHours simbol broker, disegarkan setiap lima menit. Sabtu/Minggu UTC selalu memblokir entry. Hold efektif dibatasi cutoff mingguan. Jika hari libur tercermin di API, penutupan maju ke sesi terakhir yang tersedia.

Penutupan diperiksa oleh timer satu detik dan tick, sebelum pekerjaan entry/bridge. Intent exit disimpan sebelum request. Penolakan close tidak dianggap sukses; request dicoba ulang setiap detik saat pasar terbuka dan Kirim order ON. Pending exit diproses kembali setelah restart. Posisi XAU/EUR/manual tidak ditutup oleh pengaman BTC.

Bot harus aktif dan broker terhubung. Jika runtime offline, pasar sudah tutup, atau broker terus menolak close, software tidak dapat menjamin fill. Intent dan log EXIT_WAIT/CLOSE_RETRY dipertahankan; penutupan dicoba pada kesempatan pertama saat pasar terbuka. Server-side SL/TP tetap ada.

WIB = UTC+7. Contoh close Jumat 22 UTC berarti Sabtu 05 WIB; flatten dimulai Sabtu 04.30 WIB. Native tidak meng-hardcode contoh jam ini: ia memakai API broker aktual.

Replay mengasumsikan Senin 00 UTC–Jumat 22 UTC, dengan bar BTC sesi tertutup dibuang dari indikator. Histori jadwal/DST broker belum disertifikasi. Model OHLC bukan tick broker atau FULL_PARITY, dan bukan bukti performa masa depan.

File baru ini tidak mengganti atau me-restart instance live. Jangan menjalankan versi lama dan baru bersamaan pada satu akun. Jika posisi atau intent lama masih ada, periksa recovery sebelum pergantian.
