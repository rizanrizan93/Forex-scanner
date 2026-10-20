# RIZAN XAU–EUR–BTC Frozen Weekend V1.2.1

Strategi baseline dibekukan; tidak ada pencarian ulang entry/SL/TP/risk. XAU/EUR tidak diubah. Portfolio cap20.75% tetap dan dikunci pada startup. Batas margin50%, model BTC10x, XAU/EUR200x. Pengiriman order defaultOFF. Tidak ada perubahan/deployment live.

BTC: larang entry60menit sebelum penutupan mingguan; force-exit30menit sebelumnya. Jadwal dihitung dari MarketHours broker di UTC, disegarkan5menit. Sabtu/Minggu UTC selalu blok entry dan flat-intent. Hari libur yang tercermin pada API memajukan penutupan ke sesi terakhir yang tersedia. Entry tidak diulang pada Senin: hanya sinyal closed baru yang boleh masuk. Expiry=min(hold asli,cutoff flat mingguan).

Penutupan berjalan pada timer1detik dan tick, sebelum pekerjaan entry/bridge host. Intent exit disimpan sebelum request; posisi belum dianggap flat bila broker menolak. Retry1detik selama pasar terbuka dan Kirim orderON. Pending exit tetap diproses setelah restart. Bot tidak menutup posisi XAU/EUR/manual. Bila pasar sudah tutup, runtime/offline, koneksi putus, atau broker menolak sampai cutoff lewat, tidak ada software yang dapat menjamin fill; log EXIT_WAIT/RETRY dan intent dipertahankan, posisi ditutup pada kesempatan pertama saat pasar terbuka. Server-side SL/TP tetap ada.

WIB=UTC+7: contoh close Jumat22UTC berarti Sabtu05WIB, flatten mulaiSabtu04:30WIB; close21UTC berarti Sabtu04WIB, flattenSabtu03:30WIB. Ini contoh, bukan hardcode jam broker Anda. Native memakai API jadwal simbol aktual. Perubahan5menit mendadak/holiday tidak tercatat API tetap keterbatasan. Sesi diresolusi menit dengan buffer30menit.

Nilai$24.54–24.80juta adalah versi SEBELUM weekend guard, bukan hasil versi ini. Replay baru harus diberi label asumsi jam historis; histori sesi broker/DST belum tersedia. BTC Bitstamp tersedia7hari, sehingga replay baru membuang bar sesi tertutup dari kalkulasi indikator. Hasil model OHLC bukan tick broker/FULL_PARITY dan bukan jaminanmasa depan.
