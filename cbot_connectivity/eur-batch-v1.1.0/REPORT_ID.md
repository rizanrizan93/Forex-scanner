# EUR cBot v1.1.0 — perbaikan connectivity

Source canonical: cbot_sources/archive/eur-releases/v1.1.0. Tidak direkonstruksi.
Schema 2, model EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1, prefix RZEU4B, suffix 7903.
Contract hash: 4b4ef3cbe83c26b0752c11d05c866a7345b5db93b8011af091d9e8ad68d77976.

## Root cause
Save envelope original tidak memakai Json options, sehingga DateTime default/Unspecified tidak melalui converter UTC. Validasi bridge menolak payload dan checkpoint lama tanpa offset. Handler EUR original mengubah semua error bridge menjadi quarantine. Reconnect juga memanggil Connect pada socket yang sama tanpa lifecycle guard.

Audit VPS 13 Oktober 2026 11:09:37 WIB: EUR disconnected, checkpoint 1358 model/hash/schema valid, empat field naive (Eur.LastExitUtc, LastRealExitUtc, LastSignalUtc, XauDay). XAU tetap connected=1 dan quarantined=false. Journal lokal EUR menunjukkan revision lebih baru dan BRIDGE_TIMESTAMP_OFFSET_REQUIRED; local WAL yang lebih baru harus dipertahankan.

## Patch
- Envelope save memakai Json converter original; heartbeat memakai DateTimeOffset UTC.
- Guard satu socket, callback generation fence, Dispose sebelum reconnect, backoff 1/2/4/8/15/30 detik, handshake/ACK/heartbeat timeout.
- Payload malformed dibuang dan koneksi degraded/fail-closed. Auth failure menghentikan retry.
- Historical connectivity quarantine hanya dapat pulih setelah handshake, tiga pong valid, binding valid, ValidateState, RecoverAttempt dan ReconcileExposure. Safety quarantine tidak dilepas.
- Remote checkpoint lama tidak menimpa local WAL baru. Pending state/watermark tidak dibersihkan.
- ACK branch, checkpoint schema, semua parameter, binding, Durable, dan 24 method strategy/execution byte-identical. FrozenCore, EurBatchExecution dan class RizanEURBatch identik.
- Repair offline EUR hanya schema/model/hash/account/symbol exact; menambahkan Z pada naive UTC yang provenanced. Revision, pending intent, quarantine/model tidak dimodifikasi; receipt lost-ACK dijaga. Repair tidak membuka quarantine sendiri.

## Pengujian lokal
- Archive checksum: 14 file diverifikasi.
- Runtime fixtures original: 67 assertion PASS.
- Planner original: 12.023 assertion PASS.
- Connectivity: 1675 checks, 200 cycles, MaximumActiveSockets=1, FinalActiveSockets=0, BrokerRequests=0.
- Python bridge: 15 test PASS, termasuk lost-ACK dan pending intent EUR setelah repair.
- Deployment: 11 test PASS.
- Native build cTrader.Automate 1.0.21: PASS, 0 warning / 0 error. Semua test diulang di GitHub Actions dan PASS. Tes simulator bukan native host/tick replay atau bukti order live.

## Deployment/cTrader
Bridge deployed melalui Actions SSH dengan source/db backup dan synthetic probe XAU+EUR; tidak ada test broker order. Gunakan RizanEURBatch_v1.1.0_bridgefix.algo setelah build native berhasil.
Stop instance EUR lama dahulu, import pengganti dengan parameter yang sama, pertahankan storage/checkpoint lokal terbaru. Jangan menjalankan dua instance. Jangan mengubah model/schema, menghapus pending intent, atau memakai checkpoint lama di atas local WAL lebih baru.
Jika LEASE_BUSY setelah restart, tunggu sekitar 60 detik agar lease lama kedaluwarsa; reconnect memakai backoff. Jangan menghapus lease/checkpoint secara manual.
Jangan mengubah default Kirim order atau parameter account/token secara tidak sengaja. Source tetap mempertahankan default original.
Bukti akhir: BRIDGE_HANDSHAKE_OK, TIMESTAMP_VALID, heartbeat valid, accountBound=True, trading sesuai parameter pengguna, quarantined=False bila tidak ada safety fault.

## Rollback
Simpan algo EUR original v1.1.0. Stop instance patch sebelum memakai original. Reconcile posisi dan checkpoint terbaru; jangan restore checkpoint lama setelah order/state baru. Restore source bridge dari backup deployment menggunakan existing flags; pertahankan database terkini. Rollback producer mengembalikan bug transport dan timestamp lama.

## Hasil deployment dan runtime 13 Oktober 2026
- Branch main; deployed code commit 5d6ac11604b90640215cf42184689949b14c3dca.
- EUR native build/tes: https://github.com/rizanrizan93/Forex-scanner/actions/runs/38346131899 PASS.
- Deployment: https://github.com/rizanrizan93/Forex-scanner/actions/runs/38346131862 PASS.
- EUR checkpoint suffix 7903: 4 field repaired offline; version/revision tetap 1358. XAU repair 0 field; version/revision 738 tetap.
- WSS synthetic XAU+EUR auth, aware timestamp, heartbeat dan reconnect PASS, tanpa checkpoint save atau broker order.
- Backup: /home/Rizanrizan/Forex-scanner/state/bridge-backup-20261013T042342Z.
- Audit 11:24:50 WIB: XAU connected=1, macro_event_ready=true, quarantined=false, invalid_time_fields=[], revision 740. EUR connected=1, quarantined=false, invalid_time_fields=[], revision 1361. Core hash/schema/model sesuai masing-masing source.
- Kedua koneksi sudah pulih setelah repair VPS. Audit ini tidak membuktikan bahwa file EUR bridgefix baru sudah diimport ke cTrader; producer/reconnect cBot baru tetap perlu dipasang dengan parameter/storage yang sama.
- CI EUR Connectivity, XAU Connectivity, Frozen Parity dan deployment PASS. CI umum masih FAIL karena import OrderSide/ExecutionMode pada execution/models.py yang tidak diubah.

ALGO SHA256: 15e1b23b58bc98f049736d06562a964bde857850d27d49166c02d40b6cdd8b28
