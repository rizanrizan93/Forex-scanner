# Bridge R3 aktif — 28 Oktober 2026

Deploy melalui GitHub berhasil. Service khusus `rizan-r3-bridge.service`, database/checkpoint R3 terpisah, backend loopback25347. Uji publik TLS/WSS, autentikasi, heartbeat dan data XAU/EUR/BTC lulus. Service bridge lama tetap aktif dengan PID yang sama. Tidak ada order broker dari deployment.

| Parameter cTrader | Nilai |
|---|---|
| Bridge WSS :25345 | `wss://rizan-bridge.duckdns.org:25345/r3/` |
| BTC7D WSS :25345 | `wss://rizan-bridge.duckdns.org:25345/r3/btc` |
| Token bridge dan Token BTC7D | Token bridge lama yang sama; dipakai secara privat pada service R3 |
| Nomor akun penuh | Nomor akun cTrader yang sesuai; dua akun yang sebelumnya terdaftar di bridge telah diizinkan tanpa mencetak nomornya |

Tunggu minimal60 detik sesudah probe diagnostik, lalu gunakan satu instance cBot portofolio, tiga strategi aktif dan akun USD hedged. Pastikan ready=True sebelum mengaktifkan Kirim order. R3 memakai namespace baru; tidak mengambil alih posisi cBot lama. Build SDK dan tes lokal lulus; penggunaan pada broker LIVE belum diuji.

Bukti: https://github.com/rizanrizan93/Forex-scanner/actions/runs/40684387460

Instruksi di paket ZIP lama mencatat kondisi sebelum deployment. Hasil deployment ini menggantikannya untuk status VPS dan token: service sudah aktif, dan token lama dipertahankan secara privat, bukan token baru.
