# R3 Frozen — file cTrader dan bridge

**cBot:** `RizanPortfolioR3Frozen.algo`.
**Profil:** R3_I100_W060; strategi R3 yang dibekukan, DD historis terburuk71,6217%.

File `.algo` dibuat ulang dengan SDK resmi cTrader.Automate1.0.21, target net6.0. Seluruh18 source C# sama hash dengan native port R3 yang sebelumnya diuji. Build0 error/0 warning; metadata berisi satu Robot `cAlgo.Robots.RizanPortfolioR3Frozen`, UTC. Paket bukan replay DLL yang diganti ekstensi. Tidak perlu menempel seluruh source ke editor satu per satu.

1. Impor/buka `.algo` dalam cTrader Algo, lalu buat **satu instance portofolio**, bukan satu instance per instrumen. Ia mengelola XAUUSD/EURUSD/BTCUSD bersama.
2. Pasang bridge R3 mengikuti `bridge/README_ID.md`. Backend khusus, token baru, database baru dan rute WSS R3 harus aktif terlebih dahulu. Bridge pada paket ini belum dipasang atau diverifikasi pada VPS publik.
3. Isi nomor akun penuh, dua URL WSS R3 dan dua parameter token menggunakan token R3 yang sama. Akun USD hedged, simbol persis XAUUSD/EURUSD/BTCUSD; ketiga strategi aktif. XAU0,01 lot=1oz dan EUR0,01 lot=1.000unit wajib cocok dengan kontrak broker.
4. Mulai dengan **Kirim order=false**; pastikan log profil cocok, handshake, heartbeat, BTC feed dan `RIZAN_PORTFOLIO ready=True`. Periksa snapshot makro valid sebelum mengharapkan entry XAU. Lakukan uji eksekusi demo sebelum akun real.

**Kirim order=false juga mencegah close oleh cBot.** SL/TP broker tetap berlaku. Jangan menggunakannya sebagai perintah menutup posisi yang sedang berjalan. Hindari dua instance pada akun yang sama; jangan menghapus checkpoint untuk mengatasi safety block.

## Hasil pemeriksaan

- Bukti lama:1.247 regresi+474 batch+447 native=2.168 pemeriksaan lulus.
- Setelah pemulihan:447 pemeriksaan native dijalankan ulang dan lulus.
- Bridge baru:24 tes lulus, mencakup WebSocket nyata, WSS/TLS lokal, kontrak/namespace, autentikasi, lease, durable ACK/CAS, BTC seed/gap/staleness dan checkpoint asli dari C# native.
- Header paket resmi `algo`, satu Robot, semua18 hash source cocok.
- Belum dilakukan:impor melalui GUI cTrader, eksekusi broker nyata, koneksi bridge publik/VPS, atau penyelesaian replay pembanding historis yang terputus pada sesi sebelumnya. Tidak ada klaim bebas kendala deploy atau identik dengan hasil simulasi pada broker nyata.

Source dan bukti tersedia dalam `source/`, `validation/`, `FROZEN_R3_LOCK.json`. Untuk build ulang: `dotnet build source/RizanPortfolioR3Frozen.csproj -c Release`; SDK menamai file keluaran berdasarkan folder induk proyek, sehingga nama output dapat berbeda dari nama Robot. File kiriman sudah dinamai `RizanPortfolioR3Frozen.algo`. Tidak ada API stub/replay pada proyek produksi. `AlgoPublish=false` mencegah pemasangan otomatis di mesin build.

R4 dihentikan. BUFFER V1, R2, branch main, dashboard, bridge produksi dan sistem LIVE tidak dimodifikasi. Tidak ada order nyata yang dikirim dari pembuatan paket ini.
