# RizanBootstrap125V1 — pemasangan

Gunakan `RizanBootstrap125V1.algo`. Satu instance menangani EURUSD, XAUUSD, BTCUSD. Source lengkap dan pengujian disertakan dalam ZIP.

1. Impor file `.algo` versi1.0.1 di cTrader Mobile/Windows/Mac. Pilih akun USD hedging yang benar, dengan nama simbol tepat EURUSD, XAUUSD, BTCUSD. Kontrak broker dan leverage menentukan keterjangkauan ukuran minimum.
2. Hentikan bot lama pada akun tersebut setelah semua posisi dan pending order selesai. Jalankan hanya satu instance V1. Bridge versi lama memakai namespace berbeda; bot ini tidak mengambil alih posisi atau checkpoint BUY050 lama.
3. Isi parameter **Nomor akun penuh**, bukan hanya empat digit terakhir. Biarkan XAU/EUR/BTC aktif dan parameter beku sesuai default.
4. **Bridge WSS :25345**: `wss://rizan-bridge.duckdns.org:25345/bootstrap125/`.
5. **BTC 7D WSS :25345**: `wss://rizan-bridge.duckdns.org:25345/bootstrap125/btc`.
6. Isi **Token bridge** dengan token bridge BUY050 yang sudah Anda gunakan. Token BTC boleh kosong; bot menyalin Token bridge secara otomatis. Token tidak disertakan di file unduhan. VPS menerima akun yang sudah ada pada allowlist bridge BUY050; akun lain perlu ditambahkan oleh admin VPS.
7. Default **Kirim order = false**. Jalankan untuk memeriksa koneksi/Journal. Seluruh engine perlu ready, feed BTC lengkap/fresh, dan history broker selesai dimuat. Proses warmup dapat memerlukan beberapa menit. Tidak ada order saat Kirim order=false. Checkpoint fase tetap dapat diperbarui mengikuti saldo akun.
8. Untuk mulai trading, atur **Kirim order=true** dan jalankan satu instance itu. Tidak perlu mengganti bot ketika mencapai $125. Pada akun baru dengan saldo dan equity sudah ≥125 serta flat, bot langsung menyimpan fase GROWTH.

## Membaca Journal

- `BOOT125 phase=SEED ready=True`: seed siap dari sisi checkpoint; entry tetap menunggu sinyal dan semua engine/feed siap.
- `BOOT125_PHASE growth_pending_ack=True`: ambang tercapai, menunggu penyimpanan VPS. Sesudah ACK, fase GROWTH mengizinkan inti tiga pair.
- `BOOT125_MINLOT_SKIP`: saldo tidak cukup untuk volume minimum sesuai risiko; tidak dipaksa.
- `BOOTSTRAP_BRIDGE_OFFLINE`: bot akan reconnect dengan jeda bertahap; entry baru diblokir. SL/TP broker tetap ada.
- `BOOT125_FAULT ... SUBMISSION...UNCERTAIN`: bot sengaja tidak mengirim ulang permintaan yang hasilnya belum diketahui. Periksa posisi/history dan checkpoint sebelum pemulihan; jangan menghapus state untuk memaksa order baru.
- `history_busy=True`: sedang mengambil history broker secara asinkron.
- `feed_unavailable`, `BRIDGE_OFFLINE`, atau gate yield/news: kondisi data belum memenuhi persyaratan. Koneksi WSS yang hidup saja tidak berarti entry boleh dilakukan.

Perubahan Kirim order menjadi false juga menghentikan tindakan penutupan terjadwal oleh bot; SL/TP yang sudah dipasang tetap berada di broker. Jangan menghentikan bot saat posisi aktif jika mengandalkan exit waktu/basket.

## Pemulihan dan operasi VPS

Bridge menyimpan checkpoint SQLite WAL dengan synchronous FULL, revision CAS, lease eksklusif, autentikasi token, identitas akun/kontrak dan trigger fase satu arah. Cloud menggunakan bridge sebagai sumber state persisten. Desktop juga mempunyai cache LocalStorage yang diverifikasi.

Tidak ada API order atau kredensial trading broker dalam service bridge. Service baru `rizan-bootstrap125-bridge.service`, backend loopback25356, route WSS25345 `/bootstrap125/`; state `/var/lib/rizan-bootstrap125-bridge`. Token berada pada `/etc/rizan-bootstrap125-bridge.env` milik root. Jangan kirim token ke log atau ZIP.

Cadangkan seluruh direktori state secara konsisten (gunakan SQLite backup untuk database aktif). Jangan memindahkan checkpoint antar akun atau menghapus checkpoint fase GROWTH. Setelah restart, tunggu lease lama kedaluwarsa sekitar45detik sejak heartbeat terakhir, ditambah backoff reconnect sampai30detik, bila proses sebelumnya belum melepaskannya.

Perintah pemeriksaan admin:

```bash
sudo systemctl status rizan-bootstrap125-bridge.service
sudo journalctl -u rizan-bootstrap125-bridge.service -n 80 --no-pager
sudo cat /var/lib/rizan-bootstrap125-bridge/deployment-verification.json
```

File verifikasi deployment dan hasil pengujian pada ZIP mencatat pemeriksaan yang benar-benar dilakukan. Belum ada order broker nyata yang dikirim dari pengujian rilis ini. Mulai dari demo dengan kontrak broker yang sama untuk memverifikasi fill, biaya, margin, dan heartbeat saat bot benar-benar dijalankan di cTrader.


## Android dan Cloud

Unduh file `.algo` terbaru, ketuk file dan pilih cTrader; atau gunakan Upload pada menu Algo bila tersedia. Pilih `RizanBootstrap125V1`, akun yang benar dan satu instance Cloud. Isi nomor akun penuh serta token bridge yang sudah digunakan. Mulai dengan Kirim order=false, periksa Journal, kemudian untuk trading atur Kirim order=true. Jika fitur impor tidak tersedia pada build aplikasi broker Anda, impor melalui Windows/Mac dengan sinkronisasi cTID aktif.

Petunjuk resmi: https://help.ctrader.com/cbots/how-tos/install-a-cbot/ dan https://help.ctrader.com/cbots/how-tos/start-a-cbot/ .

## Status pengujian

Rilis1.0.1 dikenali sebagai cBot oleh cTrader Console; 86 assertion C# dan 9 test Python lulus. Default order tetapfalse. Bukti native merupakan pembacaan metadata, sementara pengujian alur order menggunakan broker simulasi. Belum ada order broker nyata dari pengujian rilis.

Audit15November2026 18:31WIB: bridge Bootstrap125 dan BUY050 running/NRestarts0, WSS autentikasi/ACK/reconnect/heartbeat lulus. Sebelum probe, connected0 dan belum ada checkpoint trading Bootstrap125. Jadi bridge tersedia, tetapi cBot belum terkonfirmasi berjalan pada akun.

Jangan menggunakan route/checkpoint live untuk backtest historis. Lihat `NATIVE_REPLAY_STATUS.md` untuk data dan adapter yang masih diperlukan. Tidak ada klaim replay native2019–2026 sudah selesai.
