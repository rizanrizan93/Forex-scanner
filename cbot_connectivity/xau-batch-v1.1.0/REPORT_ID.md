# Perbaikan connectivity XAU Batch v1.1.0 — 12 Oktober 2026

Status: source dan patch selesai; pengujian lokal lulus. Deployment VPS dan Journal cTrader produksi belum diverifikasi karena sesi ini tidak mempunyai akses SSH, environment/token bridge produksi, atau sesi cTrader. Jangan menganggap hasil simulasi sebagai bukti runtime produksi.

## Identitas release

Paket asli: `RIZAN_XAU_BATCH_v1.1.0_ALGO_SOURCE_VALIDATION_20261012.zip`.
Seluruh 21 entri manifest SHA256 asli diverifikasi sebelum modifikasi. Salinan asli lengkap ada di `cbot_sources/archive/xau-batch-v1.1.0/`; patch aktif ada di `cbot_connectivity/xau-batch-v1.1.0/source/`.

- Version: 1.1.0.
- ExecutionModel: `XAU_BATCH_STAGE_FIXED_REF_WAL_V1`.
- Contract: `7ab0cd24eb2e46480d0ba371ba2cd713c5d6bd30747aee71f91ced5a57fce8bf`.
- Class/prefix/account suffix: `RizanXAUBatch` / `RZXA1` / `4480`, tidak berubah.
- Algoritma, SL/TP, layering, sizing, equity scaling, batch, parameter dan binding tetap sama.

## Root cause yang dibuktikan dari source

1. `Serialize()` untuk checkpoint lokal memakai `Json` dengan `UtcDateTimeConverter`, tetapi `Persist()` untuk envelope `save` memakai `JsonSerializer.Serialize(...)` **tanpa `Json`**. Field DateTime yang Kind-nya Unspecified (misalnya waktu dari API broker, `.Date`, nilai default) dapat keluar tanpa offset. Payload tersebut tersimpan di server, kemudian `ready.state` ditolak converter ketat dengan `TIMESTAMP_OFFSET_REQUIRED`. Tes sekarang menguji envelope save asli, termasuk timestamp Unspecified, hingga round-trip deserialize.
2. `Cycle()` sebelumnya memanggil `ConnectBridge()` setiap `_bridgeReady=false`. Flag itu menunjukkan handshake, bukan lifecycle socket. Kegagalan parse bisa mengubah flag ketika socket masih aktif; Connect dipanggil lagi pada instance lama.
3. Callback disconnect sebelumnya tidak dibatasi generation. Callback lama dapat merusak state koneksi baru. Tidak ada guard CONNECTING/CLOSING yang terpisah, dan teardown tidak dilakukan sebelum retry.
4. Error dari bridge sebelumnya selalu memanggil quarantine, tanpa klasifikasi fault. Exception kirim heartbeat juga dapat keluar ke handler exception runtime umum. Fault transport sementara kini ditangani di jalur transport dan fail-closed sementara; safety quarantine tetap berlaku.
5. Server sebelumnya mengizinkan dua sesi dengan key dan lease yang sama. Lease SQLite membatasi instance berbeda, tetapi tidak mencegah sesi kedua dari instance yang sama. Registry kini mereservasi key sebelum await dan mempertahankannya sampai socket ditutup.

Ini membuktikan cacat source dan reproduksi lokalnya. Versi proses/server yang benar-benar berjalan di VPS belum dapat dibandingkan dalam sesi ini; seluruh jalur scanner/backend lain di VPS belum diaudit langsung.

## File dan patch utama

| File | Perubahan |
|---|---|
| `source/Common/RizanRobot.cs` | Json options pada save; guard lifecycle; generation fence; dispose sebelum retry; bounded backoff 1/2/4/8/15/30 detik + jitter; timer tunggal heartbeat; timeout handshake/save/heartbeat; validasi ACK; resync WAL; klasifikasi fault dan recovery terbatas |
| `cbot_bridge/timestamps.py` | Parser offset ketat dan canonical UTC; validasi rekursif field waktu |
| `cbot_bridge/server.py` | Validasi checkpoint/payload/snapshot; penolakan sesi duplikat; pong timezone-aware; tutup socket gagal kirim sebelum key dilepas |
| `cbot_bridge/feeds.py` | UTC canonical; input clock naive ditolak; macro/event rule tetap sama |
| `cbot_bridge/repair_legacy_xau_timestamps.py` | Audit read-only / perbaikan offline checkpoint legacy dengan backup SQLite dan pemeliharaan receipt lost-ACK |
| `cbot_bridge/test_timestamps.py`, `test_session_soak.py`, `test_protocol.py` | Timestamp, durable state dan 100 siklus WebSocket lokal |
| `tests/ConnectivityTests.cs`, `tests/ApiStubs.cs` | Instrumentasi socket dan pengujian lifecycle pada class robot yang dipatch |
| `verify_scope.py` | Bukti byte-identical core, sizing, binding, parameter dan 17 method strategy/execution; Cycle hanya mengganti blok transport |
| `.github/workflows/xau-cbot-connectivity.yml` | CI Python/C#, scope, soak, regresi dan build .algo dengan SDK cTrader sebenarnya |

Diff source robot asli versus patch dapat direproduksi:

```bash
git diff --no-index cbot_sources/archive/xau-batch-v1.1.0/source/Common/RizanRobot.cs cbot_connectivity/xau-batch-v1.1.0/source/Common/RizanRobot.cs
```

Perubahan paling penting:

```diff
- JsonSerializer.Serialize(new{type="save",base_revision=_remoteRevision,client_revision=_sentRevision,state=_state})
+ JsonSerializer.Serialize(new{type="save",base_revision=_remoteRevision,client_revision=_sentRevision,state=_state},Json)
```

Tidak ada penghapusan validasi offset, perubahan FrozenCore, atau perubahan XauBatchExecution. Converter asli sudah menormalisasi offset ke UTC dan tetap dipakai.

## Hasil pengujian lokal

- Python: 13 test lulus, termasuk checkpoint survival restart SQLite, lost-ACK idempotency, offset Z/+00:00/+07:00/-05:00, naive ditolak, registry sesi duplikat dan 100 siklus WebSocket sungguhan pada loopback.
- C# ConnectivityTests: 1.675 check, 200 siklus. `MaximumActiveSockets=1`, `FinalActiveSockets=0`, `BrokerRequests=0`, `LiveVerified=false`.
- BatchAckTests: 24 kombinasi phase/RTT; tidak ada request sebelum ACK dan tidak ada request ulang.
- BatchRuntimeTests: kasus batch normal, recovery posisi/history, SL/TP, budget, broker volume cap, migrasi state dan stage add lulus.
- SizingParityTests: 1.000 check lulus terhadap helper penelitian asli, termasuk equity dan nonlinear margin.
- Scope audit: 21 file manifest asli valid, core/sizing/class/project byte-identical, 17 method identik dan body trading Cycle tidak berubah.
- Build Release memakai package `cTrader.Automate` 1.0.21: 0 warning, 0 error; `.algo` dihasilkan oleh build resmi, bukan direkonstruksi.
- Log dan bukti di folder `validation/`. Tes dengan stub membuktikan lifecycle aplikasi; belum membuktikan jumlah task/socket internal SDK cTrader dalam proses produksi.

## Recovery dan batas keselamatan

Payload malformed tidak pernah dipakai untuk trading; snapshot dibersihkan, `_bridgeReady=false`, dan Durable tetap menahan request. Socket lama dibuang sebelum reconnect. Callback dari socket lama diabaikan. Gagal Dispose menghentikan retry sampai restart, sehingga socket kedua tidak dibuat.

Checkpoint resync berlangsung sebelum ready dapat menghasilkan request: ValidateState, RecoverAttempt, ReconcileExposure dan save/ACK WAL tetap dipakai. Local WAL yang lebih baru tidak ditimpa checkpoint remote lama. Konflik state pada revision yang sama tetap safety fault. Pending attempt yang tidak dapat direkonsiliasi tetap quarantine sesuai logic frozen; patch tidak mengubahnya menjadi retry order.

Auto-recovery hanya untuk alasan lama **persis** `BRIDGE_MESSAGE_INVALID`, setelah handshake dan tiga heartbeat valid, binding/contract/state valid serta rekonsiliasi. Account mismatch, uncertain fill, missing protection, revision conflict dan semua quarantine keselamatan lainnya tidak dibuka otomatis. AUTH_FAILED menahan retry sampai restart setelah konfigurasi dibetulkan.

Bridge ini melayani ready/save/ack/ping/pong serta snapshot macro/event. Source XAU menghitung signal dan mengeksekusi di cBot. Patch tidak menambahkan protokol external order/signal baru; message `signal` yang tidak dikenal tetap ditolak.

## Deployment VPS

1. Backup checkpoint lokal cTrader, file `.algo` lama, database SQLite beserta WAL melalui SQLite backup, dan catat commit VPS yang sedang berjalan. Jangan hapus storage instance, pending label atau LastSignalUtc.
2. Temukan service bridge yang benar (`rizan-cbot-bridge.service` dari deploy script repository, atau nama service aktual VPS). Stop instance cBot XAU lama dengan checkpoint tersimpan, kemudian stop **service bridge tersebut**. Jangan restart service scanner lain tanpa kebutuhan.
3. Checkout commit branch perbaikan yang sudah diuji. Pastikan unit menjalankan `cbot_bridge/server.py` dari checkout ini; salinan server terpisah di VPS juga harus diperbarui beserta `timestamps.py` dan `feeds.py`.
4. Audit database offline dengan interpreter venv dan **key penuh yang benar**. Jangan menyalin nomor akun dummy dari tes:

```bash
.venv/bin/python cbot_bridge/repair_legacy_xau_timestamps.py PATH_DATABASE --key RZXA1:NOMOR_AKUN:XAUUSD
```

Jika audit menemukan timestamp naive pada checkpoint dari source XAU v1.1.0 yang telah diverifikasi, jalankan saat bridge tetap STOP:

```bash
.venv/bin/python cbot_bridge/repair_legacy_xau_timestamps.py PATH_DATABASE --key RZXA1:NOMOR_AKUN:XAUUSD --apply --confirm-legacy-utc-producer
```

Alat ini menambahkan `Z` pada wall-clock UTC legacy yang provenance-nya diketahui, tanpa menggeser waktu atau mengubah revision/intent. Ini bukan toleransi parser runtime; naive tetap ditolak. Bila source/identitas tidak cocok, jangan menebak zona waktu. Alat membuat backup sebelum apply dan mengupdate digest receipt terbaru yang tepat.

5. Start service bridge yang benar dan periksa journal. Tidak perlu mengubah token, account binding, contract atau parameter trading.
6. Jalankan probe WSS autentikasi menggunakan environment rahasia yang sudah berada di VPS; jangan kirim token ke chat. `public_wss_probe.py` memakai identitas sintetis dan tidak mengirim save/order.

## Deployment cTrader

1. Pastikan instance XAU lama berhenti. Simpan parameter dan checkpoint. Hindari menjalankan cBot lama dan baru bersamaan.
2. Import `.algo` hasil build patch, kelas `RizanXAUBatch`, dengan parameter WSS/account/token/trading **sama seperti sebelumnya**. Jangan mengganti setup frozen.
3. Pertahankan local storage instance atau gunakan `Checkpoint pemulihan JSON` asli bila cTrader menciptakan instance baru. Jika field pemulihan diisi, perhatikan field itu lebih diprioritaskan daripada storage lokal; jangan terus menggunakan checkpoint manual lama pada restart berikutnya.
4. Journal yang harus dibuktikan:
   `RIZAN_STARTUP_OK version=1.1.0`, `BRIDGE_CONNECTING`, `BRIDGE_CONNECTED`, `BRIDGE_HANDSHAKE_OK`, `TIMESTAMP_VALID`, `BRIDGE_HEARTBEAT_OK`, serta telemetry `accountBound=True`, `trading=True` sesuai parameter sebelumnya, `quarantined=False` bila tidak ada safety fault.
5. Amati runtime panjang dan beberapa drop/reconnect nyata. Pastikan socket lama selesai, handshake ulang, heartbeat sehat dan watermark/checkpoint konsisten. Jangan memaksa order untuk membuktikan connectivity; order tetap mengikuti setup frozen.

Acceptance produksi belum PASS sampai Journal dan proses VPS benar-benar menunjukkan kondisi tersebut. Local test tidak menggantikan langkah ini.

## Rollback

Stop cBot patch dan bridge; backup state terbaru terlebih dahulu. Checkout commit deployment sebelumnya untuk file bridge, lalu import `.algo` asli yang SHA256-nya `a348edee4e3c1844741bea26fd09ce00fe925d7e2bd374b846fd0d0093f69262`. Pertahankan checkpoint **terbaru** dan rekonsiliasi posisi; jangan mengembalikan checkpoint lama jika ada aktivitas order setelah upgrade. Backup SQLite sebelum perbaikan timestamp hanya boleh dipulihkan jika tidak ada perubahan state/trade sesudah backup; bila ada, rollback kode saja dan lakukan audit checkpoint. Pengembalian kode lama dapat mengembalikan bug serialization; pertahankan fail-closed bila itu terjadi.
