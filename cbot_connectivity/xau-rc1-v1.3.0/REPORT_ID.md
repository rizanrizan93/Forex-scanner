# RC1 v1.3.0 bridge integration

Original release: commit 1069a9cbef6dde07119bc1531a15bc764f3aa34d on
freeze/xau-rc1-1025-primary. The uploaded algo matches the release byte for byte:
cbe20989440e1aee82f7c72271b78634f4c14a7dfc7367c8576687447aa7ef12.
Original source/config/tests/algo are archived under cbot_sources/archive/xau-rc1-v1.3.0.

Exact bridge identity: RZXRC1:<full-account>:XAUUSD, schema 1,
contract 44db60b75e3eb19c0fb94f10baca96f35ab4686086a70eea53f626533ca9923c,
execution model XAU_BATCH_SEND_REF_COOLDOWN_V1. This is separate from RZXA1.
The server validates all fields and never rewrites an old checkpoint as RC1.

The original RC1 producer predates the existing v1.2.1 transport fix. This integration
ports that same transport fix using a three-way merge against original v1.2.1:
socket disposal, callback generation fencing, single-flight reconnect, bounded backoff,
handshake/save/heartbeat deadlines, UTC serialization, local WAL preservation and
recovery from connectivity-only quarantine. Trading-related quarantine is retained.
The startup banner identifies 1.3.0-bridgefix.

verify_scope.py verifies original archive digests, byte-identical contract/execution
files, checkpoint schema, parameters, account binding, risk/cooldown/tolerance
constants, execution methods, ACK filtering and Cycle trading body.
The native cTrader build and RC1 execution/200-cycle transport fixtures are required
by Deploy cBot bridge via SSH before the VPS deploy job can run.
The resulting artifact is RizanXAU-RC1-v1.3.0-bridgefix.

## Deploy

1. Let the bridge workflow finish with DEPLOY_PASS and
   WSS_RC1_AUTH_TIMESTAMP_HEARTBEAT_RECONNECT_PASS. These probes use synthetic
   accounts, never submit broker orders, and never save production checkpoints.
2. Replace the old XAU instance when its positions and pending execution are settled.
   Old RZXA1 positions are not owned by the new RZXRC1 prefix. Do not run the old
   and new trading instances together as a replacement procedure.
3. Import the bridgefix algo, select XAUUSD and the existing bound USD hedged
   account (suffix 4480), preserve the full account number, WSS :25345 and token.
   Do not paste a RZXA1 checkpoint into RC1; the contract rejects it.
   For a restart of an existing RC1 deployment, preserve its RC1 checkpoint.
4. Confirm the Journal shows the RC1 hash, version 1.3.0-bridgefix, BRIDGE_HANDSHAKE_OK,
   BRIDGE_READY and healthy heartbeat, and that macro/event data is valid.
   The original algo and bridgefix default Kirim order to No; preserve the user's
   intended execution setting when starting the replacement.

The source keeps RC1 2.4 ATR stop, 5.5R target, 0/0.20/0.40R stages,
90-minute adds, 12.1% runtime basket risk cap, 50% margin cap, $102.50 balance step,
480-minute hold and 3-day cooldown. No replay performance claim is added here.
VPS deployment success and native cTrader Journal acceptance are separate checks.

## Validation completed locally

- Bridge Python tests: 16 passed; deployment tests: 12 passed.
- RC1 execution fixtures: 33 cases passed.
- Transport fixture: 1,675 checks across 200 cycles; maximum active sockets 1,
  final active sockets 0, broker requests 0.
- Native cTrader.Automate 1.0.21 Release build completed. Metadata confirms
  cAlgo.Robots.RizanXAU_RC1_v1_3_0 and assembly version 1.3.0.0.
- Source scope verification passed after build. See validation/build-proof.json.
- No remote push, VPS deployment or cTrader runtime acceptance was completed:
  automatic approval review rejected publication to the repository pending
  explicit destination/production authorization.
