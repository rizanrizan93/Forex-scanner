# BTC VPS security and connectivity audit — 21 Oktober 2026

Observed 06:13WIB /20 Oktober23:13:23UTC. Scope is the bridge checks listed here; this is not a guarantee of all VPS security, future uptime, native trading eligibility or strategy performance.

## Actual checks
- Direct SSH via GitHub Actions39513463956: completed/success.
- Two read-only samples of existing native leases; no test lease acquired. XAU/EUR/BTC all active and renewed during observation.
- BTC heartbeat last-touch age4.43s before and6.46s after; remaining lease38.54s after.
- BTC server/client checkpoint revision2; Fault=false, Sending=false, ExitPending=false. SQLite PRAGMA quick_check=ok via read-only connection.
- Main andBTC services active, NRestarts=0, both process PIDs unchanged during audit.
- BTC service NoNewPrivileges=yes, ProtectSystem=strict, ProtectHome=read-only.
- Existing main service NoNewPrivileges=yes; ProtectSystem/ProtectHome=no. No unsolicited changes made to that service.
- Secret environment file and BTC SQLite database mode0600, no group/other access and no symlink. Tokens match internally; no token disclosed.
- Both backends127.0.0.1:8130 and127.0.0.1:25346 loopback-only. Public TLS25345 is the intended frontend.
- Hostname/chain verification succeeded withTLS1.3. Certificate expiry9Jan2027, approximately80.64days at observation.
- Public BTC route correctly rejected invalid token, correct token with wrong account, and correct token with wrong contract. All rejection probes occur before lease acquisition; no real identity lease taken.
- Runtime BTC server.py/store_base.py/timestamps.py and seed hashes match frozen commit e357272fec03411a6e7c4d2397faf742d1a11047 bytewise.
- Independently reconstructed pinned Bitstamp seed plus current M1 extension:68399H1 bars, through21Oct06:00WIB /20Oct23:00UTC. No synthetic missing-bar fill.
- This independent reconstruction verifies data availability and validation logic, not a direct observation of the running native client's FeedReady/RecoveryReady flags.

## Operational decision
Leave the existing connected instance and services running. No reset/restart, lease deletion, checkpoint mutation, production-env change, order, live-risk change, EnableTrading change, or main merge performed. Creating isolated audit scripts and logs does not change the running bridge.

BTC connection/checkpoint and the tested authentication/storage/TLS protections passed at the observation time. Entry additionally depends on native feed freshness, schedule, signal, margin and risk gates; no claim that every entry condition is currently satisfied.

## Evidence
- Actions: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39513463956
- Artifact: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39513463956/artifacts/12306593530
- Outer ZIP SHA256: ff2ede0db63afa26f9352b8a8e687c40f7236dbe30ceb5f25672872d1bc43bf7
- Audit source commit:95fbee57b56b39b15e77f78c51a5a400b0ea5e08
- Separate branch:fix/btc7d-bridge-connectivity-20261021
