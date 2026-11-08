# BUY050 bridge identity fix — 8 November 2026

## Root cause
The genuine frozen BUY050 .algo uses `TPX_13bfa137`, `TPE_13bfa137` and `TPBTC:<profile>`. Its default WSS route points to `/disp1506/`, which is reserved for the Displacement strategy. The BUY050 bridge supplied inside the frozen archive was not deployed by the build. A different server on `/disp1506/` can reject BUY050 with `IDENTITY_INVALID`; the cBot then quarantines trading.

## What is changed
Only a **new, isolated bridge** is prepared: `/buy050/` on public WSS port 25345 routed to `127.0.0.1:25352`, distinct systemd service, distinct account-bound checkpoint DB and lease namespace. It matches the original BUY050 frozen profile. No XAU/EUR/BTC entry, exit, sizing, layering, stop, target, trading flag, checkpoint or original .algo is modified. An OPTIONAL C# transport-only source patch is provided separately (NOT compiled): it changes default URLs and permits clearing ONLY the BRIDGE_IDENTITY_INVALID quarantine after 3 authenticated heartbeats and successful local checkpoint/broker reconciliation, with no open basket, pending children or owned position. Do not treat this as an installed binary. Original binary and source are included unchanged and checksummed.

## Do NOT do these things
- Do not add BUY050's keys to an existing Displacement/TP500/BTC10 bridge, and do not overwrite `/disp1506/`.
- Do not clear any `Quarantined` state, force `ready`, replay old checkpoints, or replace the newer local WAL.
- Do not print tokens or full account IDs in logs, PR, or screenshots.
- Do not enable new orders until the BUY050-specific WSS endpoint, full-account binding, BTC feed freshness, XAU/EUR data, checkpoint continuity, and all three heartbeats are verified.
- Do not run `provision_isolated.py` from a public runner or on any host except the intended authorized VPS after explicit review and backup. It needs root and changes systemd/nginx on that VPS.

## Deployment checklist (NOT performed)
1. Back up current cTrader instance configuration, current local checkpoints/WAL and any open/pending broker positions. Record original binary SHA256. Do not stop any current service yet.
2. On the authorized VPS inspect port 25352 and existing `/buy050` Nginx route. Preserve existing services. The dedicated `bridge/deploy/provision_isolated.py` creates isolated `/opt/rizan-buy050-bridge`, `/var/lib/rizan-buy050-bridge`, and `/etc/rizan-buy050-bridge.env`; it reads the old BTC bridge's token/account allowlist privately and copies the BTC M1 **cache only**, never checkpoints. Do not run if secrets are missing, route exists, account binding differs, or audit fails.
3. The script installs and starts only `rizan-buy050-bridge.service`, adds `/buy050` Nginx locations, reloads Nginx after `nginx -t`, and runs an authenticated no-order handshake/heartbeat/data probe. It does NOT send broker orders. Read its exit status and report. Wait >45 seconds for probe leases to expire.
4. In **the same original BUY050 .algo instance** (no new build needed just to change URLs; note sticky quarantine below), change only parameters:
   - `Bridge WSS :25345` → `wss://rizan-bridge.duckdns.org:25345/buy050/`
   - `BTC 7D WSS :25345` → `wss://rizan-bridge.duckdns.org:25345/buy050/btc`
   - Keep original bridge token fields, correct account lock, all frozen trading parameters, native local storage/WAL and existing positions unchanged. Stop prior instance *only once* new bridge is verified, then resume exactly one instance; never start a duplicate.
5. Verify three `BRIDGE_HANDSHAKE_OK` / BTC ready, fresh macro and BTC feeds, account/symbol/contract matches, remote revision/watermarks and reconciled open broker positions, no `IDENTITY_INVALID`, no persistent quarantine. **Important:** Original .algo keeps `BRIDGE_IDENTITY_INVALID` quarantine sticky. Even with healthy bridge, its new orders remain blocked. The included `source_patched_TRANSPORT_ONLY_UNBUILT/` contains a guarded fix, but must be **compiled natively and tested** before it can replace the instance. Do not bypass quarantine by deleting local state. Only after native build, broker-state reconciliation, restored checkpoint continuity and `quarantined=False` consider restoring the original `Kirim order` setting.

## Tests
From the extracted root (with installed Python `websockets`):
`cd bridge && python -m unittest -v test_bridge test_native_frames test_buy050_isolation test_source_transport_only`
`python -m py_compile bridge/*.py bridge/deploy/*.py`
Extra `test_tls` requires local certificate fixture dependencies. Tests are synthetic and do not attest live connectivity or execution. **Important archive defect found:** bundled XAU and BTC `validation/native_fixtures` contain an older profile hash `aa75f...`, not BUY050 `13bfa...`. They must be rejected by the BUY050 bridge; integration tests use copies corrected to the BUY050 profile solely for protocol validation, not as proof of native cTrader emission. A new native fixture run is required before any LIVE enablement.

## Limitations
This chat did not SSH into the VPS, deploy or restart services, or alter cTrader Cloud. The original .algo was NOT rebuilt and its checksum must match; the transport-only source patch is unbuilt and not an executable fix to the persistent quarantine. Source changes are confined to bridge and deployment files, not strategy C#. Build-time performance results are benchmarks, not guarantees.

## GitHub packaging note
In this repository, the historical Bitstamp BTC seed is stored as a pinned Git blob copied from `repairs/btc_fullfix_20261104/bridge/BTC_SEED_PACKET.json.gz`. Provisioning decompresses and checks the expected SHA256 before any BUY050 service is started. This GitHub copy contains patched C# source; download the native-built `.algo` ONLY if GitHub Actions build and regression succeed. Source parity remains frozen except for URL defaults and guarded identity-route recovery.
