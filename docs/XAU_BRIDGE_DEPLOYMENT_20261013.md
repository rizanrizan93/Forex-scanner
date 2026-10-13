# Hasil deployment XAU bridge — 13 Oktober 2026

## Update setelah Journal pengguna, 09:35 WIB
- Koneksi cBot awal ditolak sebelum handshake karena checkpoint akun suffix 4480 berasal dari format legacy schema 1 tanpa ExecutionModel.
- Audit read-only 02:28:41 UTC: version/revision 628, core hash sesuai, quarantined=false, macro siap, connected=0. Empat field naive: Eur.LastExitUtc, LastRealExitUtc, LastSignalUtc, XauDay.
- Provenance diverifikasi terhadap source canonical v1.0.1 pada cbot_sources/archive/migration-20261010/v1.0.1/Common/RizanRobot.cs dan FrozenCore.cs: hash sama, schema 1, tidak memiliki ExecutionModel, UTC converter dan envelope save tanpa opsi Json.
- Repair offline explicit XAU_LEGACY_CORE_V1 hanya menerima schema 1 dengan ExecutionModel absent/empty, hash/account/symbol sesuai. Tidak menambah model atau mengubah wall-clock, revision, intent, watermark; digest lost-ACK diperbarui secara terikat.
- Deployment lanjutan eca8bd4e95396687ecfab3db8daaedded2a9340c: SUCCESS, https://github.com/rizanrizan93/Forex-scanner/actions/runs/38337479301.
- Log repair: naive_fields=4, version_unchanged=628, revision_unchanged=628.
- Backup terbaru: /home/Rizanrizan/Forex-scanner/state/bridge-backup-20261013T023455Z.
- Audit read-only 02:35:51 UTC (09:35:51 WIB): service active, account 4480 version/revision 630, hash sesuai, model XAU_BATCH_SEND_REF_COOLDOWN_V1, quarantined=false, invalid_time_fields=[], connected=1, macro_event_ready=true, lease remaining 42.4 detik.
- Audit ulang 02:37:05 UTC (09:37:05 WIB): koneksi tetap 1, macro siap, quarantined=false, timestamp invalid tetap kosong dan revision maju normal ke 632. Lease diperbarui dengan sisa 40.7 detik.
- Ini bukti cBot pulih otomatis dan menyimpan checkpoint baru. Transisi model berlangsung melalui flat-only migration asli cBot; tool repair tidak melakukan transisi tersebut.
- Validasi lanjutan: 14 test bridge, 10 test deployment, 33 fixture C#, 1675 checks/200 cycles; XAU Connectivity dan Frozen Parity PASS. CI umum tetap gagal pada import execution/models.py yang tidak diubah.
- Workflow audit: https://github.com/rizanrizan93/Forex-scanner/actions/runs/38337035856. Tidak mengirim order, mengambil lease, memodifikasi checkpoint atau merestart service.
- File algo sebelumnya tetap berlaku; cBot tidak perlu diimport ulang untuk repair checkpoint ini. Journal akhir accountBound/trading/heartbeat dan observasi panjang tetap melengkapi bukti VPS.

## Status deployment pertama
- Branch: main. PR #785 merged; merge commit 7fb3c133a69bbee791f073423be20c3c29fec2b2.
- Commit kode yang benar-benar dideploy: c7778659e9146ee775a6aba9d7c84605a3fd9b74.
- Workflow: https://github.com/rizanrizan93/Forex-scanner/actions/runs/38334698546
- Validate dan deploy: SUCCESS.
- Unit: rizan-cbot-bridge.service, checkout /home/Rizanrizan/Forex-scanner.
- Log 2026-10-13 01:59:48 UTC (08:59:48 WIB): DEPLOY_PASS dan WSS_AUTH_TIMESTAMP_HEARTBEAT_RECONNECT_PASS.
- Pengujian WSS memakai identitas sintetis; tidak mengirim order atau menyimpan checkpoint.
- cBot cTrader pengguna belum dapat dioperasikan dari lingkungan ini. Acceptance penuh accountBound/trading/quarantined serta runtime panjang masih memerlukan Journal.

## Root cause dan patch
Source terbaru pengguna diverifikasi sebagai RizanXAUStable v1.2.1, model XAU_BATCH_SEND_REF_COOLDOWN_V1, core hash 7ab0cd24eb2e46480d0ba371ba2cd713c5d6bd30747aee71f91ced5a57fce8bf. Detail audit source dan diff berada di cbot_connectivity/xau-stable-v1.2.1/REPORT_ID.md dan validation/RizanRobot.patch.

1. Save envelope sebelumnya melewati converter UTC sehingga DateTime tanpa offset masuk checkpoint dan ditolak saat resync. Gunakan opsi serializer UTC yang sudah diaudit; parser tetap menolak naive timestamp, menerima Z/offset valid dan memakai UTC internal.
2. Flag handshake digunakan sebagai indikasi socket tidak aktif sehingga reconnect memanggil Connect saat socket lama masih aktif. Guard lifecycle, generation callback, Dispose sebelum connect, bounded backoff, heartbeat tunggal dan resync menjaga satu transport.
3. Fault connectivity malformed masuk quarantine permanen. Payload dibuang/fail-closed, koneksi degraded; recovery terbatas membutuhkan handshake, tiga pong valid, binding dan rekonsiliasi valid. Fault account/strategy/uncertain order tetap dilindungi.
4. Deployment awal tertahan secret SSH/host key. Keduanya sudah diset pengguna; host fingerprint dipatok, strict checking tetap aktif.
5. VPS mempunyai perubahan lokal dan checkout tanpa fixture tes terbaru. Three-way merge memakai base blob yang diverifikasi hash dilakukan hanya pada candidate privat. Perubahan lokal models.py tidak disentuh.
6. Tes port tetap tersambung ke listener lain dan mendapat AUTH_FAILED. Port loopback kosong menyelesaikan kegagalan tanpa melemahkan assertion.
7. Checkpoint dari source/model belum dikenali tidak dinormalisasi. Row tersebut dipertahankan utuh; validasi server tetap berlaku ketika row dipakai.

## File
- cbot_connectivity/xau-stable-v1.2.1/source/Common/RizanRobot.cs: lifecycle/serialization/recovery transport.
- cbot_bridge/server.py, feeds.py, timestamps.py: protocol, registry socket, UTC parsing/serialization.
- cbot_bridge/repair_legacy_xau_timestamps.py: repair offline terikat hash/model/account.
- cbot_bridge/test_protocol.py, test_session_soak.py, test_timestamps.py: regression dan loopback soak.
- deployment/deploy_bridge.py, bridge-connectivity.patch, patch-bases.json, test-fixtures.json, test_deploy_bridge.py.
- .github/workflows/deploy-cbot-bridge-ssh.yml dan xau-cbot-connectivity.yml.

Empat file produksi yang diinstall di VPS: server.py, feeds.py, timestamps.py dan repair_legacy_xau_timestamps.py. Strategy, entry, SL, TP, layering, risk sizing, equity scaling, batch, signal criteria, backtest dan core hash tidak diubah. Scope verifier membandingkan 17 method strategy/execution, parameter, schema dan branch ACK.

## Tes dan bukti
| Pemeriksaan | Hasil |
|---|---|
| Python bridge | 13 PASS, termasuk 100 WebSocket reconnect cycle |
| Deployment | 8 PASS: konflik fail-safe, partial/mixed patch, fixture hilang, preservation, rollback tanpa rewind WAL |
| C# fixture original | 33 PASS |
| C# connectivity | PASS: 1675 checks, 200 cycles |
| MaximumActiveSockets dalam simulator | 1 |
| FinalActiveSockets dalam simulator | 0 |
| BrokerRequests dalam simulator | 0 |
| Scope strategy/execution | PASS |
| Candidate pada venv VPS | PASS |
| Public WSS auth/snapshot aware/pong/reconnect | PASS, 2 reconnect session |
| Frozen cBot Parity / XAU cBot Connectivity | PASS pada 1adb04d6fcaa3358842f57335c4547be44d4c92c; validate pada deployed commit juga PASS |
| CI umum | FAIL, import OrderSide/ExecutionMode dari execution/models.py; di luar perubahan connectivity |

Soak membuktikan maximum satu socket pada simulator, bukan pengukuran native SDK cTrader. Payload valid tidak memicu connectivity quarantine dalam tes; quarantined=False pada cBot pengguna belum diverifikasi. Tidak ada live order yang dikirim untuk verifikasi.

## Restart cTrader
1. VPS sudah direstart oleh workflow; tidak perlu git reset atau menghapus perubahan lokal.
2. Gunakan RizanXAUStable_v1.2.1_bridgefix.algo, SHA256 4156b1f716b1dc6ec7f36b117c9c2848d7515a0cddfaad42cdef8ce1c79c77a8.
3. Stop instance lama dahulu. Import file bridgefix sebagai pengganti versi 1.2.1 dengan parameter account/WSS/token/trading sebelumnya dan storage/checkpoint tetap terjaga. Jangan jalankan dua instance.
4. Jangan ubah execution model checkpoint atau menghapus pending intent/watermark agar lolos gate. Upgrade lintas model tetap mengikuti flat-only migration asli.
5. Periksa Journal: RIZAN_STARTUP_OK version=1.2.1, BRIDGE_CONNECTING, BRIDGE_CONNECTED, BRIDGE_HANDSHAKE_OK, TIMESTAMP_VALID, BRIDGE_HEARTBEAT_OK. accountBound=True; trading mengikuti parameter pengguna; quarantined=False hanya jika semua safety contract valid.
6. Jika muncul model/contract checkpoint mismatch, kirim Journal; tidak boleh dipaksa dengan mengedit checkpoint.

## Rollback
Backup deployment sukses: /home/Rizanrizan/Forex-scanner/state/bridge-backup-20261013T015938Z.

Stop cBot patch dan unit bridge; backup checkpoint terkini terlebih dahulu. Restore hanya empat file produksi dari backup sesuai existing flags pada metadata.json: file yang sebelumnya tidak ada harus dihapus, file yang ada dipulihkan. Start unit yang sama. Pertahankan database terkini; jangan restore checkpoint lama setelah service pernah start atau ada transaksi/state baru. Pada cTrader gunakan algo original v1.2.1 dan rekonsiliasi state/posisi sebelum melanjutkan. Rollback mengembalikan bug transport lama.

Jika rollback dibutuhkan, operator dapat meminta eksekusi melalui Actions SSH; rollback belum dijalankan.
