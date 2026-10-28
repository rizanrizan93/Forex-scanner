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

---

# Bridge khusus R3

Kode ini kompatibel dengan `RizanPortfolioR3Frozen.algo`, profil `R3_I100_W060`. Ia tidak memegang kredensial broker dan tidak memiliki API order. Layanan ini terpisah dari bridge LIVE: database sendiri, akun yang diizinkan sendiri, token sendiri dan backend127.0.0.1:25347. Namespace lama LIVE/R2 ditolak. Protokol hello/ready/save/ack/ping/pong sama dengan source cBot; hash R3 dan intent BTC dipertahankan utuh.

**Status saat ini:** service R3 dan rute publik sudah aktif; lihat hasil deploy di awal dokumen. Bagian instalasi berikut adalah referensi untuk pemasangan baru, bukan perintah menjalankan ulang instalasi pada VPS yang sudah aktif.

## Instalasi VPS

Dari folder `bridge/`, administrator VPS menjalankan:

```bash
sudo bash deploy/install.sh NOMOR_AKUN_PENUH
```

Memerlukan Python3.11+ beserta modul venv, systemd, akses internet HTTPS, dan port backend25347 yang belum dipakai. Script hanya membuat instalasi R3 baru; berhenti bila instalasi R3 sudah ada. Script tidak menyentuh service/database/token bridge lama. Token R3 dibuat otomatis dan disimpan dengan izin600 pada `/etc/rizan-r3-bridge.env`; gunakan token ini pada **kedua** parameter token cBot. Jangan kirim isi token di chat atau memasukkannya ke git.

Untuk cTrader Cloud, public WSS harus memakai TLS valid dan TCP25345. Administrator menambahkan isi `deploy/nginx-r3-locations.conf` **di dalam server TLS25345 yang benar**, lalu memeriksa `sudo nginx -t` dan melakukan graceful reload `sudo systemctl reload nginx`. Jangan menimpa nginx.conf atau location lama. `/` dan `/btc7d130` tetap menuju upstream lama; hanya `/r3` dan `/r3/…` menuju R3. Perubahan routing ini belum dijalankan dari paket ini.

Jika menggunakan hostname yang sebelumnya dipakai proyek, nilai parameter setelah route diaktifkan adalah:

| Parameter cBot | Nilai |
|---|---|
| Bridge WSS :25345 | `wss://rizan-bridge.duckdns.org:25345/r3/` |
| BTC7D WSS :25345 | `wss://rizan-bridge.duckdns.org:25345/r3/btc` |
| Token bridge dan Token BTC7D | Token R3 dari file konfigurasi VPS, bukan token yang disertakan paket |
| Nomor akun penuh | Sama dengan R3_ALLOWED_ACCOUNTS |

Hostname tersebut berasal dari konfigurasi proyek sebelumnya; ketersediaan/routing publiknya belum diverifikasi pada pembuatan paket ini. Gunakan hostname TLS valid milik VPS yang benar bila berbeda. Jangan arahkan native R3 ke root bridge lama karena namespace baru tidak kompatibel dengan validator lama.

## Data otomatis dan pemulihan

Bridge mengambil makro/news melalui adapter yang sama dengan source bridge proyek: FRED DGS10/DFII10, ForexFactory dan kalender BLS. Ia mempertahankan aturan availability makro; sumber hilang tidak diubah menjadi kondisi lolos. BTC memverifikasi seed Bitstamp yang dipatok hash lalu mengambil M1 asli dari Bitstamp untuk memperpanjang jam yang sudah selesai. Cache SQLite bertahan saat restart. Setiap jam tambahan harus berisi tepat60 M1; celah tidak diisi dan timestamp tidak dimajukan secara palsu. Backfill awal bisa memerlukan beberapa polling. Kegagalan sumber ditandai feed_unavailable; entry BTC baru diblokir oleh cBot.

Checkpoint menggunakan SQLite WAL+synchronous FULL, CAS revision dan receipt untuk ACK yang hilang. Lease eksklusif45 detik per akun/simbol; heartbeat memperpanjang lease. Dua instance untuk key sama ditolak. Restart bridge tidak memindahkan checkpoint R2/LIVE. Hanya satu instance cBot portofolio boleh dipasang untuk akun ini.

## Pemeriksaan sebelum menyalakan order

1. Periksa `sudo systemctl status rizan-r3-bridge` dan `/var/lib/rizan-r3-bridge/health.json`.
2. Dari sesi server pribadi, muat konfigurasi tanpa mencetak token, lalu jalankan probe:

```bash
sudo bash -c 'set -a; source /etc/rizan-r3-bridge.env; set +a; export R3_PUBLIC_URL="wss://rizan-bridge.duckdns.org:25345/r3"; export R3_PROBE_ACCOUNT="NOMOR_AKUN_PENUH"; /opt/rizan-r3-bridge/.venv/bin/python /opt/rizan-r3-bridge/probe.py'
```

Probe tidak mengirim order atau save checkpoint. Ia memegang lease diagnostik sebentar; tunggu60 detik setelah probe selesai sebelum memulai cBot. LEASE_BUSY berarti ada instance aktif atau lease belum kedaluwarsa; jangan menghapus database untuk mengatasinya. Hasil PASS memeriksa koneksi/data saat itu, bukan persetujuan strategi atau jaminan hasil broker.

3. Mulai cBot dengan Kirim order=false, tiga strategi aktif, akun USD hedged, simbol persis XAUUSD/EURUSD/BTCUSD. Pastikan handshake/heartbeat/feed valid dan portofolio ready. OFF juga mencegah close oleh cBot; broker tetap memegang SL/TP yang sudah dipasang. Lakukan pengujian eksekusi di demo sebelum menjalankan akun real.

## Uji ulang lokal

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s . -p 'test_*.py' -v
```

Tes memakai server WebSocket nyata di loopback dan satu tes WSS dengan sertifikat lokal yang dipercaya khusus oleh klien tes. Tidak menghubungi server LIVE atau mengirim order. Tes seed memakai data asli yang dipatok; tes ekstensi memakai respons sintetis secara eksplisit sebagai fixture, tidak sebagai feed produksi.
