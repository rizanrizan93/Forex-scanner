# RIZAN — audit final support layer, 11 Oktober 2026

STRATEGY_SUPPORT_READY=NO

Audit source dan pengujian lokal selesai; kesiapan live belum terbukti. Tidak ada perubahan setting live execution, account binding, frozen JSON atau archive original. Tidak ada order riil, pemasangan VPS, service restart live, reboot VPS, atau .algo baru. Commit ini adalah kandidat support/transport untuk review.

## Status wajib

PASS di bawah memiliki ruang lingkup bukti yang dijelaskan setelah tabel. FAIL mencakup pemeriksaan yang gagal **atau belum dapat dibuktikan**; tidak otomatis berarti VPS/provider sedang rusak.

```text
GIT_HEAD=a84b6e2ddda63ae6cede27c68f7b90e40dcfea2c
WORKTREE=bridge-connectivity-audit (clean before report creation; report commit follows)
XAU_FROZEN_HASH=PASS
EUR_FROZEN_HASH=PASS
XAU_CBOT_SOURCE_PARITY=PASS
EUR_CBOT_SOURCE_PARITY=PASS
XAU_SIGNAL_REPLAY_PARITY=PASS
EUR_SIGNAL_REPLAY_PARITY=PASS
XAU_LAYER_RISK_PARITY=PASS
EUR_LAYER_RISK_PARITY=FAIL
XAU_CHECKPOINT=PASS
EUR_CHECKPOINT=PASS
CHECKPOINT_RESTART_RECOVERY=PASS
CHECKPOINT_LOST_ACK=PASS
CHECKPOINT_ANTI_DUPLICATE=FAIL
CHECKPOINT_DISK_LOSS_PROTECTION=FAIL
XAU_DGS10=PASS
XAU_DFII10=PASS
XAU_EVENT_FEED=PASS
XAU_EVENT_GATE_PARITY=PASS
EUR_MACRO_EVENT=N/A_EXPECTED
DUCKDNS=FAIL
TLS=FAIL
WSS_PUBLIC_25345=FAIL
BACKEND_LOCAL_25346=FAIL
CTRADER_CLOUD_XAU_BRIDGE=FAIL
CTRADER_CLOUD_EUR_BRIDGE=FAIL
XAU_SNAPSHOT_DELIVERY=FAIL
TURSO_HEARTBEAT=FAIL
SYSTEMD_RECOVERY=FAIL
VPS_REBOOT_RECOVERY=FAIL
STRATEGY_SUPPORT_READY=NO
```

## Bukti dan batas PASS

- Kontrak: canonical SHA256 contract JSON cocok dengan expected XAU dan EUR; 16 field FrozenContract masing-masing cocok. Semua pinned source dan archived .algo cocok. Ini mengaudit artifact di repository, bukan hash .algo yang sedang berjalan di Cloud.
- Source adaptasi: FrozenCore kedua versi, EurBatchExecution dan project byte-identical dengan original; bagian robot di luar metode connectivity dan seluruh Cycle mulai ManagePositions identik. Arsip 50 migration + 67 entri manifest EUR diperiksa tanpa perubahan. Tidak ada archive duplikat baru.
- XAU replay kernel: 4.000 bar fixture historis (14 BUY, 18 SELL) cocok; confirmation differential 41 kasus cocok. Sizing oracle 240 kasus gabungan pada core migrasi lulus (120 XAU). Source rule BUY regression channel 48, SELL sweep-confirm 24, strict H1/M15, completed M5, 4 depths, 45 menit confirmed additions, risk 12,5%, margin 50%, target 6,6R, hold 480 menit dengan cutoff source 19:59 UTC, child 1 oz, commission .03 per side, stop max(2.65 ATR,.5,anchor), dan reference leverage 100 tetap.
- EUR Batch v1.1.0 kernel: 23.978 M1, 1.599 features, 31 signals serta split-state virtual feedback/restart cocok dengan reference. Frozen constants: 3 stages 0/.2/.4R, .4 initial, power 1.5, DD .25/reduction .7, risk .2725, margin .5, 4R, 240 menit, leverage 200. Batch-specific planner 12.023 assertions dan original runtime simulation 67 assertions lulus, termasuk one aggregated request/second, pending intent durability, pending volume/first-fill anchor, recovery from exposure/history, uncertain-result quarantine dan no blind retry. Ini belum membuktikan per-basket hasil historical replay identik.
- Transport patch: 42 assertions XAU + 11 EUR lulus melawan API simulasi; semua test mengirim nol order broker. Kedua salinan patch juga lulus compile terhadap reference .NET 6 dan cAlgo.API paket cTrader.Automate 1.0.21. Ini bukan native Cloud runtime test atau packaged .algo build.
- Bridge: 15 tests lulus. SQLite WAL/FULL, CAS, receipt retry idempotent sesudah restart, lease 45 detik persisten, namespace terpisah, pending EUR state roundtrip, corruption reject, same-lease simultaneous sockets rejected, token auth, XAU-only snapshot, fake Turso outage, malformed provider schema, loopback backend guard, private state files. Lokal restart/retry PASS bukan full VPS reboot PASS.
- Macro/event: fetch publik dari mesin audit berhasil untuk DGS10, DFII10, FF dan BLS tanpa error. Macro availability +2 hari kerja federal AS/NY-midnight UTC, holiday test dan stale/future rejection lulus. Snapshot health kini memeriksa umur 180 detik, coverage -30/+495, finite values, available timestamps serta schema event. Ini indikator kesehatan data; tidak memberi arah atau order dan tidak mengubah gate cBot. Event gate unchanged diuji di kedua boundary untuk keenam kategori; BUY memakai DFII10 delta <=0, SELL DGS10 delta >=0; EUR bypass macro tetap. Pengiriman snapshot aktual ke XAU Cloud belum terbukti.

## Blocker nyata

1. **Strict EUR layer/risk historical equivalence belum terbukti.** Oracle scalar migrasi lama gagal pada latest Common helper: RemainingStageBudget 22.54 versus 22.51 (extra planned entry-slippage reserve). Penting: test ini memanggil `FrozenCore.StartBasket`, sedangkan production Batch memakai `EurBatchExecution.Start`, yang menghitung ulang initial allocation. Karena itu kegagalan ini **bukan bukti otomatis bahwa Batch salah**. Batch-specific tests lulus, tetapi masih diperlukan oracle/replay authoritative untuk production Batch path dengan fill/quote assumptions yang sama. Strategi tidak diperbaiki atau diubah; bagian strategy berhenti untuk report sebagaimana instruksi. No full historical basket creation/stage activation/layer count/exit timing parity claim.
2. **Akses dan bukti live belum ada.** SSH ke VPS serta TCP 25345/25346 dari mesin audit menghasilkan Network unreachable/OSError. Ini tidak membuktikan firewall VPS tertutup. Hostname DuckDNS aktual dan sesi VPS yang dapat diakses belum tersedia dalam audit ini. DNS A/update, public trusted TLS/renewal, Nginx Upgrade, private backend binding, firewall dan active systemd perlu diperiksa di host. Template Nginx/DuckDNS yang ada serta service/renewal templates yang ditambahkan bukan bukti layanan terpasang. Tidak dilakukan controlled restart/reboot pada sistem live tanpa akses/observability.
3. **Handshake dan recovery Cloud belum terbukti.** Tidak tersedia sesi cTrader Cloud/log privat yang dapat diverifikasi. Actual hello/ready/ping/pong/save/ack kedua cBot, XAU snapshot freshness, ExpectedAccount/BridgeUrl/BridgeToken binding privat, deployed algo hashes dan actual LoginSuffix terhadap current live account belum diperiksa. Setting/binding tidak diubah. Comprehensive anti-duplicate across native cBot/Cloud restart, exact pre-order/post-fill bridge crash serta broker history propagation masih belum dibuktikan; synthetic receipts/recovery lulus. Ini alasan CHECKPOINT_ANTI_DUPLICATE=FAIL dalam scope menyeluruh, bukan kegagalan receipt test.
4. **Total disk loss belum terlindungi.** Source Turso mirror hanya meng-upsert runtime_heartbeats. Tidak ada off-host authoritative checkpoint/backup yang terbukti, sehingga Turso heartbeat tidak boleh dianggap checkpoint recovery. Desain online SQLite backup, encryption, digest/revision/idempotency dan stale-backup broker reconciliation tersedia di `cbot_bridge/deploy/DISASTER_RECOVERY.md`, tetapi belum diimplementasikan/deploy atau diuji restore. Persistent disk/path live dan actual Turso heartbeat/reboot recovery juga belum dapat diverifikasi.

## Perbaikan yang dikomit

- `cbot_bridge`: registry sesi aktif agar satu lease tidak dipakai dua socket; lease expired tidak mengunci identitas selamanya; send snapshot deadline; DB close saat service berhenti; placeholder token ditolak; default backend loopback 25346 dan public-bind guard; health validation yang mengikuti freshness/coverage frozen. Tidak ada fungsi broker order atau broker credential baru.
- `cbot_connectivity/vps`: salinan source transport yang terpisah dengan handshake/heartbeat/save-ACK timeout, socket-generation fence, reconnect, transient lease handling dan ACK matching; unchanged Durable/order/recovery methods. Prototipe `cbot_connectivity/vps/bridge` bukan bridge final: gunakan **cbot_bridge** untuk deployment reviewed.
- Tests, field/pin auditor, service/renewal templates dan disaster-recovery design. Tidak ada deploy script yang dijalankan. Frozen/archives tidak disentuh.

## Cara mengulang uji lokal

```bash
python scripts/audit_frozen_cbot_parity.py
python scripts/audit_cbot_final_support.py
python -m unittest discover -s cbot_bridge -p 'test_*.py' -v
python cbot_connectivity/vps/tests/verify_scope.py
dotnet run --project cbot_connectivity/vps/tests/TransportXauTests.csproj -c Release
dotnet run --project cbot_connectivity/vps/tests/TransportEurTests.csproj -c Release
```

Differential original parity dan planner/runtime tests dijalankan pada salinan temporary source archive; source immutable tidak menerima bin/obj/build output. Host audit mengalami keterbatasan process introspection MSBuild sehingga compile menggunakan Roslyn dari SDK 8.0.425; native-reference compile memakai .NET 6 reference pack 6.0.36. Test runtime memakai .NET 8 dan broker API stubs. Warning nullable di stub bukan kegagalan compile source cBot. Tidak ada artifact build dipasang pada akun live.
