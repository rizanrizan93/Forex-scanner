# Adaptasi connectivity VPS — kandidat validasi

Source berasal dari main adb5c1c718d3ecef0c36231f48a66eab02dcc6d9:
- XAU v1.0.1: `cbot_sources/archive/migration-20261010/v1.0.1`.
- EUR Batch v1.1.0: `cbot_sources/archive/eur-releases/v1.1.0`.

Salinan kerja ini terpisah dari arsip asli. Tidak ada rebuild .algo, migrasi checkpoint EUR lama, atau perubahan strategi, sizing, layering, SL/TP, batch order, parameter default, kontrak maupun filter macro/event. `provenance.json` mencatat hash source asli dan salinan. File robot yang berubah adalah adaptasi connectivity, sehingga hash seluruh file tersebut memang berbeda; FrozenCore, EurBatchExecution dan project tetap byte-identical.

## Hasil audit dan adaptasi

| Area | Temuan source asli | Adaptasi |
| --- | --- | --- |
| EUR Batch | Bridge hanya menerima RZEU3/schema 1 | RZEU4B/schema 2, ExecutionModel batch yang tepat; XAU RZXA1/schema 1 tetap |
| Heartbeat | Pong terlambat menutup gate order tetapi belum reconnect | Timeout 30 detik, ping 10 detik, reconnect sesudah 15 detik |
| Handshake | Ready tidak memiliki deadline tersendiri | Timeout 10 detik; socket baru per percobaan |
| ACK checkpoint | Save dapat tertahan walau pong masih masuk | Deadline 15 detik, validasi revision ACK, reconnect dan baca checkpoint authoritative |
| Disconnect | Callback socket lama bisa mengubah koneksi baru | Generation fence dan stopping guard |
| Lease | LEASE_BUSY masuk karantina permanen; lease hilang saat server restart | Lease sementara retry; lease 45 detik disimpan SQLite dan sesi aktif ganda ditolak |
| Recovery | Checkpoint server + RecoverAttempt/ReconcileExposure sudah ada | Mekanisme recovery/order tetap sama; tidak mereset budget atau mencoba ulang order tidak pasti |
| Transport exception | Send ping dapat masuk runtime quarantine | Exception transport ditangani di connectivity agar ManagePositions tetap dipanggil |
| Feed publisher | Exception tak tertangani bisa mematikan service | Fetch exception tidak mematikan checkpoint/heartbeat; tidak membuat snapshot sehat palsu |

CAS tetap wajib dan ACK tetap sesudah commit SQLite WAL/FULL. Jika ACK hilang setelah commit, reconnect membaca state yang telah tersimpan; tidak mengirim ulang order. SQLite lease menggunakan jam UTC host: sinkronisasi waktu VPS harus aktif. Jalankan hanya satu instance bridge untuk database ini; registry sesi aktif bukan koordinasi multi-worker. Jangan menyalin database aktif tanpa prosedur backup SQLite.

## WSS dan pemasangan

cTrader Cloud membatasi WebSocketClient ke TCP **25345**. Jangan mengganti dengan 443 untuk Cloud. Gunakan `wss://<hostname-sertifikat>:25345` dan sertifikat CA publik yang cocok dengan hostname. Self-signed hanya dipakai uji lokal, bukan produksi. HTTP tidak menggantikan feed WSS Cloud. Dokumentasi: https://help.ctrader.com/ctrader-algo/documentation/cbots/cloud-requirements/ . LocalStorage Cloud tidak bertahan setelah instance restart; checkpoint bridge penting untuk recovery tanpa JSON manual.

Untuk deployment final gunakan `cbot_bridge/` di root repository dan `cbot_bridge/deploy/`; folder `bridge` di paket awal ini hanya prototipe audit lokal dan bukan bridge produksi terbaru (receipt/idempotency berada di `cbot_bridge`). Folder prototipe berisi server, feed asli, requirements, template environment dan systemd. Template memakai `/opt/rizan-bridge`, port 25345 tetap, dan user VPS `Rizanrizan`; sesuaikan user jika berbeda. Instal dependencies di venv menggunakan requirements. Isi token acak minimal 32 karakter, path database persisten, serta certificate/key. Jangan commit environment terisi. Pastikan user service bisa membaca key TLS; jangan menjadikan private key world-readable. Perpanjangan sertifikat memerlukan reload/restart bridge untuk memuat sertifikat baru. Firewall/provider harus mengizinkan inbound 25345. Health test tidak menggunakan akun trading.

Di cBot isi Bridge WSS dengan hostname tersebut dan token yang sama. Parameter ExpectedAccount dan EnableTrading tetap seperti source asli. Pada deployment baru, checkpoint belum ada; pada restart dengan aktivitas sebelumnya, checkpoint harus sesuai identitas/schema/contract. Jika database hilang, jangan mengosongkan recovery untuk memaksa trading baru. Integritas invalid tetap masuk quarantine sesuai mekanisme source.

## Macro/event XAU

`feeds.py` byte-identical dengan sumber beku: DGS10/DFII10 dari FRED, kalender USD Forex Factory dan BLS. Lag dua hari kerja AS, usia macro maksimum tujuh hari, usia snapshot maksimum 180 detik, jendela event -30/+495 menit serta aturan arah macro tidak diubah. Feed tidak sehat, coverage mingguan tidak cukup, atau data kedaluwarsa tetap memblokir entry XAU. Bridge tidak memperluas coverage kalender secara fiktif. Publisher berjalan di thread agar fetch HTTP tidak memblokir heartbeat; source bisa gagal/berubah sehingga health feed live perlu diperiksa.

## Verifikasi

Dari root repository:

```bash
python -m unittest discover -s cbot_connectivity/vps/tests -v
python cbot_connectivity/vps/tests/verify_scope.py
dotnet run --project cbot_connectivity/vps/tests/TransportXauTests.csproj -c Release
dotnet run --project cbot_connectivity/vps/tests/TransportEurTests.csproj -c Release
```

Lima test lulus: protokol kedua schema, CAS/lease persisten, strict JSON, WSS/TLS dengan verifikasi hostname, ping/pong, ACK, restart dan recovery checkpoint, penolakan koneksi ganda, waktu macro/hari libur/stale dan cakupan kalender. Test WSS memakai fixture feed sehingga tidak menyatakan provider live sehat. Verifier membandingkan semua source/project dan bagian robot di luar metode connectivity, serta seluruh Cycle mulai ManagePositions. Archives diperiksa ulang dengan SHA256SUMS.

**Batas validasi (diperbarui audit final):** Adaptasi C# telah lulus compile terhadap reference .NET 6 dan cAlgo.API dari paket cTrader.Automate 1.0.21. Uji transport memakai API simulasi (55 assertions), bukan koneksi cTrader Cloud asli. Tidak dibuat .algo baru. Tidak ada deployment, koneksi live VPS, aktivasi trading atau bukti feed live dalam pekerjaan ini. Nama domain/sertifikat VPS dan akses pemasangan masih diperlukan sebelum rollout. Tidak ada .algo baru yang siap dipasang.

Checkpoint `ready` ditolak sebelum dipakai jika invalid; state sebelumnya dikembalikan saat validasi gagal. Pesan ready di luar handshake ditolak. Tidak ada perubahan validator atau recovery order.
