# BTC seven-day bridge repair — 21 Oktober 2026 WIB

Status: VPS installed and externally verified; cTrader instance parameters still require user update.

## Verified cause
Read-only Actions run 39506844164 showed no BTC service, no listener on loopback8130, no /btc7d130 route, and only XAU/EUR contracts in the primary bridge. Thus the prior package contained a BTC backend implementation that had not been installed on this VPS. The screenshot alone does not establish whether its exact rejection code was identity or authentication.

## Completed repair
- Installed rizan-btc7d130.service using byte-unchanged V1.3.0 bridge source and pinned seed.
- Added exact TLS path /btc7d130 on existing host rizan-bridge.duckdns.org and port25345.
- Reused existing primary bridge token in a separate root-readable BTC environment file; primary production environment unchanged. No token disclosed.
- BTC retains its own database/contract/feed. Seven-day Bitstamp history is preserved; no replacement with weekday broker bars.
- Main XAU/EUR backend root route, process PID, source and service remained unchanged; nginx configuration was tested and gracefully reloaded.
- Public WSS authenticated hello, current feed and pong succeeded. Feed68398 H1 bars, through2026-10-20 22:00UTC (2026-10-21 05:00WIB).
- Six original bridge tests passed. Checkpoint probe used a temporary lease and did not save checkpoint state or send orders.
- Frozen strategy, SL, TP, risk, leverage and cBot trading parameters unchanged. No merge to main.

## cTrader parameters
Keep main Bridge WSS and Token bridge unchanged.
Set BTC 7D WSS to:
`wss://rizan-bridge.duckdns.org:25345/btc7d130`
Set Token BTC 7D to the same existing value as Token bridge.
The old client treats non-lease rejection as fatal for that instance; apply corrected parameters and restart that instance to reconnect. No replacement algo is required for this server repair.
This deployment does not remotely change cTrader instance parameters and does not prove the user's instance is connected until its subsequent journal is checked.

## Evidence
- Audit: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39506844164
- Repair: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39507175279 — completed/success
- Artifact: BTC7D-REPAIR-VERIFICATION, ID12303822303
- Artifact outer ZIP SHA256: 6387b0c908723437ed27dc8756c6e1fe3e3826f4aa9964b4b9f7fb5e55f01376
- Installed source/deployment commit: 7c254d57ac3f77177d0441001528e3156b035b06
- Frozen source parent: e357272fec03411a6e7c4d2397faf742d1a11047
- Branch: fix/btc7d-bridge-connectivity-20261021
- Server verification: /home/Rizanrizan/rizan-btc7d130/DEPLOYMENT_VERIFICATION.json
- Route backup and separate state retained on VPS.

The shared token is a copied value at installation; a future deliberate primary-token rotation must also update the BTC service configuration. Separate protocol endpoints do not inherently require different credentials.

No historical profit or drawdown result is changed or newly validated by a connectivity repair.
