# Integrasi bridge RizanXAUStable v1.2.1

Source terbaru berasal dari ZIP pengguna `RIZAN_XAU_TARGET24K_v1.2.1_RESEARCH_20261012.zip`. Seluruh 38 checksum ZIP cocok dan algo terlampir identik dengan algo di ZIP. Arsip source/config/fixture original yang relevan disimpan di `cbot_sources/archive/xau-stable-v1.2.1/`; 16 file arsip yang tercantum pada manifest diverifikasi kembali oleh scope test. Hasil riset 10 tahun tidak dijalankan ulang dalam pekerjaan connectivity ini.

## Identitas yang dipertahankan

- Version: 1.2.1; class: RizanXAUStable; prefix RZXA1; account suffix 4480.
- ExecutionModel: XAU_BATCH_SEND_REF_COOLDOWN_V1.
- Core contract hash: 7ab0cd24eb2e46480d0ba371ba2cd713c5d6bd30747aee71f91ced5a57fce8bf.
- RiskCap 0,121; cooldown 3 hari; SendToleranceR 0,20; margin profile 50%; sizing slip reserve 0,10; commission reserve 0,06.
- Default Kirim order=False dan parameter account/WSS/token kosong tetap seperti source pengguna.
- Semua parameter dan account binding tetap identik. XauPendingSignal, XauResumeUtc dan schema checkpoint tidak diubah.

## Root cause dan perubahan

Release terbaru masih mengandung serializer envelope save tanpa opsi Json yang memasang converter UTC. DateTime Unspecified dapat dikirim tanpa offset, tersimpan dan ditolak ketika ready.state dibaca kembali. Validasi offset tidak dihapus. Save kini memakai Json; heartbeat memakai DateTimeOffset UTC. Timestamp Z dan offset positif/negatif tetap dinormalisasi ke UTC.

Source juga masih memanggil Connect pada socket lama ketika handshake flag false. Transport dipisahkan dari handshake, memakai guard CONNECTING/CLOSING, generation fence untuk callback lama, Dispose sebelum koneksi baru, backoff 1/2/4/8/15/30 detik dengan jitter, timer heartbeat tunggal, timeout handshake/heartbeat/save dan recovery connectivity terbatas. Dispose gagal menahan retry sampai restart, supaya tidak membuat socket kedua.

Payload malformed tidak digunakan untuk trading: snapshot dibersihkan, bridge offline/degraded, Durable tetap menahan request sampai resync dan ACK. Auth fault menahan retry; safety fault tetap quarantine. Auto-recovery hanya alasan historical tepat BRIDGE_MESSAGE_INVALID sesudah handshake, tiga pong valid, binding/state valid dan rekonsiliasi. Proteksi account, uncertain order, recovery exposure dan SL/TP tidak dibuka otomatis.

ACK branch terbaru dipertahankan byte-identical, termasuk kebijakan unmatched ACK diabaikan. Kami tidak menyalin policy ACK dari versi lama. Pending submission/recovery tetap memakai logic asli v1.2.1. Local WAL lebih baru tidak ditimpa remote checkpoint lama.

## File utama

- `cbot_connectivity/xau-stable-v1.2.1/source/Common/RizanRobot.cs`: integrasi transport saja.
- `source/Common/FrozenCore.cs`, `XauBatchExecution.cs`, `XauSendReference.cs`, class dan project cBot: byte-identical terhadap source pengguna.
- `verify_scope.py`: membandingkan 17 method strategy/execution, parameter, binding, risk/cooldown/send-reference, schema dan branch ACK. Body trading Cycle identik; hanya blok service transport diganti.
- `Tests.csproj` dan `tests/Tests.cs`: fixture original tidak diubah.
- `ReplayApi.cs`: tambahan instrumentasi socket/storage untuk pengujian, tidak termasuk build algo produksi.
- `ConnectivityTests.csproj`, `tests/ConnectivityTests.cs`: soak transport pada robot terbaru.
- `cbot_bridge/server.py`, `feeds.py`, `timestamps.py`: patch server dari pekerjaan sebelumnya tetap diperlukan.
- `cbot_bridge/repair_legacy_xau_timestamps.py`: pilihan execution-model explicit untuk checkpoint v1.2.1. Default lama dipertahankan.
- `.github/workflows/xau-cbot-connectivity.yml`: test/build terbaru ditambahkan.

Diff robot terdapat di `validation/RizanRobot.patch`; patch commit lengkap disertakan dalam ZIP delivery.

## Pengujian yang benar-benar dijalankan

| Pengujian | Hasil lokal |
|---|---|
| 33 fixture execution original v1.2.1 | PASS, source fixture identik |
| Transport C# 200 siklus | PASS, 1.675 check |
| MaximumActiveSockets | 1 |
| FinalActiveSockets | 0 |
| BrokerRequests dalam soak connectivity | 0 |
| Python bridge | 13 test PASS, termasuk 100 siklus WebSocket loopback |
| Source scope | PASS: helper/strategy/execution/schema/parameter/ACK identik |
| Build actual cTrader.Automate 1.0.21 Release | PASS: 0 warning / 0 error |

Fixture order memakai broker simulasi. Pengujian ini bukan tick replay, native-host backtest atau runtime live. Nilai saldo/DD dalam paket riset pengguna tidak menjadi jaminan runtime dan tidak diklaim direproduksi oleh pengujian connectivity ini. Jumlah socket internal SDK cTrader pada VPS belum dapat diukur.

## Deployment dan restart

1. Gunakan algo terbaru hasil integration ini, bukan algo bridgefix v1.1.0. Simpan algo original v1.2.1 dan checkpoint terbaru sebagai rollback.
2. Stop instance lama sebelum mengaktifkan instance baru. Jangan hapus local storage atau pending intent/watermark.
3. Perbarui sisi VPS juga: server.py, feeds.py dan timestamps.py dari patch. Pastikan unit service benar-benar menunjuk checkout tersebut. Service repository bernama rizan-cbot-bridge; identifikasi nama aktual VPS dahulu.
4. Stop bridge sebelum audit/perbaikan database. Dengan nomor akun penuh dan path database aktual:

```bash
.venv/bin/python cbot_bridge/repair_legacy_xau_timestamps.py PATH_DATABASE --key RZXA1:NOMOR_AKUN:XAUUSD --execution-model XAU_BATCH_SEND_REF_COOLDOWN_V1
```

Jika naive UTC berasal dari source yang diverifikasi, apply offline dengan backup otomatis:

```bash
.venv/bin/python cbot_bridge/repair_legacy_xau_timestamps.py PATH_DATABASE --key RZXA1:NOMOR_AKUN:XAUUSD --execution-model XAU_BATCH_SEND_REF_COOLDOWN_V1 --apply --confirm-legacy-utc-producer
```

Tool tidak menggeser wall-clock, tidak mengubah revision/intent/LastSignalUtc/XauResumeUtc, dan menjaga digest receipt terbaru yang sesuai untuk lost-ACK. Parser runtime tetap menolak naive timestamp. Jika checkpoint masih execution-model lama, audit dengan model lamanya; jangan mengedit model agar bisa lolos validasi.
5. Upgrade dari model v1.1.0 ke v1.2.1 tetap mengikuti flat-only migration **asli**. Posisi/basket/pending aktif yang tidak kompatibel tidak boleh dipaksa melewati gate.
6. Start bridge, lalu import/start class RizanXAUStable dengan parameter account/WSS/token/trading yang sesuai konfigurasi pengguna sebelumnya. Patch tidak menyalakan order atau mengubah account.
7. Bukti produksi yang masih wajib: RIZAN_STARTUP_OK version=1.2.1, BRIDGE_CONNECTING, BRIDGE_CONNECTED, BRIDGE_HANDSHAKE_OK, TIMESTAMP_VALID, BRIDGE_HEARTBEAT_OK, accountBound=True, trading=True bila parameter sebelumnya aktif, quarantined=False bila tidak ada safety fault; lalu observasi runtime panjang dan drop/reconnect nyata.

Update 13 Oktober 2026: deployment VPS melalui GitHub Actions SSH sudah PASS pada commit c7778659e9146ee775a6aba9d7c84605a3fd9b74. Autentikasi WSS publik, timestamp aware, heartbeat dan reconnect telah diverifikasi memakai klien sintetis tanpa order atau checkpoint save. Checkpoint dengan provenance yang belum dikenali dibiarkan utuh. Acceptance cBot cTrader sebenarnya masih menunggu Journal; jumlah socket SDK dan quarantined=False pada instance pengguna belum diklaim. Detail deployment dan rollback: docs/XAU_BRIDGE_DEPLOYMENT_20261013.md. Bridge tetap menyediakan ready/save/ack/ping/pong/snapshot; tidak ditambahkan jalur external order baru.

## Rollback

Stop cBot patch dan bridge; backup checkpoint terbaru terlebih dahulu. Restore source/server deployment sebelumnya dan algo original **v1.2.1** dari upload pengguna. Pertahankan state terbaru dan rekonsiliasi posisi; jangan restore checkpoint lama bila ada transaksi sesudah backup. Backup database sebelum timestamp repair hanya boleh dipulihkan bila belum ada perubahan state/trade sesudahnya. Rollback ke algo original mengembalikan bug transport, sehingga koneksi yang fault harus tetap fail-closed.

## Publikasi

Patch dipush dan PR #785 digabung ke main atas instruksi pengguna. Merge commit 7fb3c133a69bbee791f073423be20c3c29fec2b2. Deployment VPS berhasil pada c7778659e9146ee775a6aba9d7c84605a3fd9b74 melalui Actions run 38334698546. Validasi deployment, XAU connectivity dan Frozen cBot Parity PASS. CI umum masih FAIL karena import OrderSide/ExecutionMode pada execution/models.py yang sudah bermasalah sebelum pekerjaan ini; file execution tersebut tidak diubah.

## Update runtime 13 Oktober 2026, 09:35 WIB

Checkpoint legacy akun suffix 4480 memiliki empat field tanpa offset. Source canonical v1.0.1 dan core hash diverifikasi sebelum menambahkan repair offline untuk schema 1 tanpa/empty ExecutionModel. Tool hanya memperbaiki timezone serialization: version/revision tetap 628; model dan intent tidak ditulis ulang. Regression lost-ACK setelah repair PASS.

Commit eca8bd4e95396687ecfab3db8daaedded2a9340c dideploy melalui Actions run 38337479301, PASS. Audit read-only run 38337035856 pada 09:35:51 WIB menunjukkan koneksi akun 4480=1, macro_event_ready=true, quarantined=false, invalid_time_fields=[] dan revision 630. cBot pulih otomatis serta melakukan flat-only migration original ke XAU_BATCH_SEND_REF_COOLDOWN_V1; strategy/execution source tidak diubah. Tes bridge 14 PASS dan deployment 10 PASS; CI Connectivity/Parity PASS, CI umum masih FAIL karena execution imports di luar scope.
