# RIZAN Frozen V1 — P0 audit, 23 November 2026

**Result: monitoring repair deployed and verified; exact native stoppage cause remains UNKNOWN.**

Four role leases are active again. Recovery was already visible at 02:04 UTC / 09:04 WIB, before this investigation changed monitoring. No cBot was restarted, and no order or trading checkpoint was changed by this work. Frozen V1 strategy/source was not modified.

## A. Root cause and confidence

| Finding | Classification | Evidence |
|---|---|---|
| BOOTSTRAP, XAUUSD, EURUSD and BTCUSD are four links in one cBot | CONFIRMED | Pinned source `90172c2fba345e4221ca822c8e7d1d760a98c6b1`, `source/RizanXauEurPortfolio.cs`, shared lifecycle/timer |
| Four leases stopped receiving accepted renewals within 7.028171 seconds | CONFIRMED | Historical SQLite-derived snapshots, exact timestamps below |
| Bridge stayed active without a service restart across the incident | CONFIRMED | `ExecMainStartTimestamp=Sat 2026-11-14 21:53:10 WIB`, MainPID 788419, NRestarts 0, Result success; 18 expired snapshots still show service active |
| VPS reboot caused the incident | NOT SUPPORTED | Current boot began 2 November 2026, 08:47:21 WIB / 01:47:21 UTC |
| Bridge deployed code changed around the incident | NOT SUPPORTED | Current bridge `server.py` and `durable_store.py` SHA-256 match pinned released files; VPS mtimes are 14 November |
| One shared native lifecycle, timer or network path failed | PROBABLE | Common parent cBot and near-simultaneous loss of four independently renewed links; exact failing component cannot be isolated |
| cBot was STOPPED, crashed, killed, disconnected, or stalled | UNKNOWN | No native lifecycle/Journal receipt was accessible. Expired leases cannot distinguish these conditions |
| OOM, CPU/memory pressure, broker authentication expiry, manual stop, or cTrader host recycling caused the failure | UNKNOWN | No direct supporting event. No OOM match in retained kernel evidence; no historical CPU/memory series was collected by the old system |

The confirmed failure mechanism is **accepted heartbeat traffic stopped, and 45-second leases elapsed**. That is not proof of the initiating native failure. No percentage confidence is assigned to competing unobserved causes.

### Why the previous watchdog did not recover it

The bridge unit uses `Restart=on-failure`. A running bridge with no cBot traffic does not satisfy that restart condition. The repository's manual-monitor watchdog only checks publication age and dispatches `cbot-manual-monitor.yml`; it neither supervises Frozen V1 native lifecycle nor restarts that cBot. A recent snapshot publication can contain old leases.

The released bridge handler also closes failed sockets without recording structured connect/disconnect/rejection lifecycle events. Native `OnStop` has no explicit stop-reason receipt. These are confirmed evidence gaps, not a proven explanation for why the original process ceased renewing.

## B. Timeline and impact

| Event | UTC | WIB | Interpretation |
|---|---|---|---|
| Last historical all-role active snapshot before incident | 17 Nov 19:59:26 | 18 Nov 02:59:26 | All leases active |
| XAUUSD last accepted renewal | 18 Nov 01:01:18.930115 | 18 Nov 08:01:18.930115 | Earliest final renewal |
| BOOTSTRAP last accepted renewal | 18 Nov 01:01:23.001101 | 18 Nov 08:01:23.001101 | Phase GROWTH retained |
| BTCUSD last accepted renewal | 18 Nov 01:01:23.966288 | 18 Nov 08:01:23.966288 | Checkpoint retained |
| EURUSD last accepted renewal | 18 Nov 01:01:25.958286 | 18 Nov 08:01:25.958286 | Latest final renewal |
| First lease expired: XAUUSD | 18 Nov 01:02:03.930115 | 18 Nov 08:02:03.930115 | Lease deadline, not native stop timestamp |
| All four leases expired | 18 Nov 01:02:10.958286 | 18 Nov 08:02:10.958286 | Last deadline: EURUSD |
| First stored expired snapshot retrieved | 18 Nov 02:08:29.216492 | 18 Nov 09:08:29.216492 | Direct observation of expiration |
| Last stored expired snapshot before recovery | 22 Nov 21:59:19.766173 | 23 Nov 04:59:19.766173 | Same final renewal timestamps and checkpoint versions |
| First direct active snapshot in this audit | 23 Nov 02:04:26.876670 | 23 Nov 09:04:26.876670 | Recovery already occurred, mechanism UNKNOWN |
| Independent watchdog installed | 23 Nov 02:11:50 | 23 Nov 09:11:50 | Bridge process identity unchanged |
| Shadow expired-lease detection passed on VPS | 23 Nov 02:11:57 | 23 Nov 09:11:57 | No trading restart |

There are 18 retrieved expired observations. Persisted final-renewal timestamps remain unchanged through 22 November 21:59 UTC, a span of **4 days 20:57:08.807887 after the final expiry deadline**. This measures absence of accepted renewals in retained bridge state; it is not a measured duration of a STOPPED cBot. Exact recovery is bounded by the last expired and first active observations, not known to the second. First initiating failure timestamp and first failing component remain UNKNOWN.

No missed executable signal or order is proven. `last_signal_at=null` is not proof of no signal, and the current broker reader covers 48 hours, not the entire 18 November incident. There is no claim of zero missed trades.

## C. Evidence collection

Successful forensic Actions run: [45098732849](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45098732849).

- Retained system journal: 19,628 rows; bridge: 984; kernel: 3; nginx: 42.
- Focused interval 18 November 00:45–02:00 UTC: 5,545 journal rows, below the 20,000-row limit.
- The 146 generic connection/disconnection matches in that focused interval belong to SSH/session units. They are **not** evidence of Frozen V1 WebSocket failure.
- The bridge's 82 `opening handshake failed` matches are on **17 November**, before the incident. They are not attributed to the 18 November failure.
- No bridge lifecycle event at the incident timestamp was present. Nginx access log was empty; retained rotated error files exist but were not used to infer client lifecycle.
- Current SQLite `PRAGMA quick_check`: `ok`.
- Eleven GitHub Actions runs started in the focused interval. No Frozen V1 deploy/restart workflow appears among those starts; this does not exhaust runs that began earlier or non-GitHub actions.
- Raw logs remain in a root-private VPS evidence directory. SHA-256, coverage and sanitized observations are in [evidence.json](evidence.json). The Actions artifact is `bootstrap125-p0-sanitized-evidence`, ID 14784760404, digest `sha256:4865570f17f477c8efb23efec52ffe63723d98821953845ae30b624feddcd7fc`.

## D. Repair and tests

Forensic collector commit: `4036935a0df2bb65f8d3f600e108328379da90f0`.

Monitoring/watchdog commit: **`03bf0789ace00683b4a5f52d545ed366505be99f`**.

Successful validation/deployment run: [45098732835](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45098732835).

Changed code:

- `operations/bootstrap125_forensics/collect.py`: preserves raw evidence privately; exports hashes and classified observations.
- `src/fx_scanner/cbot_v1_reliability.py`: separates bridge availability, accepted lease traffic, native lifecycle and execution readiness.
- `src/fx_scanner/cbot_v1_dashboard.py`: explicit per-role stale/expired indicators and heartbeat timestamps. Lease expiration is a failed connectivity gate; native lifecycle and execution readiness remain UNKNOWN without native evidence.
- `operations/bootstrap125_watchdog/watchdog.py` and `install.py`: independent ten-second systemd observer, no broker credentials, no network, no trading-state access, no restart authority. Emits `V1_HEARTBEAT_ALERT` or `V1_HEARTBEAT_OBSERVED` to its journal.
- Two dedicated Actions workflows and three regression test modules.

**45 tests passed:** dashboard/monitor 29; watchdog 4; existing direct-monitor isolation 4; pinned released bridge SQLite and loopback WebSocket 8. Tests use the actual released Python bridge at pinned commit `90172c2fba345e4221ca822c8e7d1d760a98c6b1`; deployed source hashes match it. The deploy stage runs only after validation succeeds.

| Required scenario | Verification and limit |
|---|---|
| 1. WebSocket disconnect | Abrupt loopback transport abort, reconnect, state preserved |
| 2. Sudden cBot crash | Missing-traffic monitor simulation; no real cTrader crash injected |
| 3. VPS/bridge restart | Close/reopen scratch Store, durable state and receipts preserved; no LIVE reboot |
| 4. Missing heartbeat | Missing/stale timestamps cannot pass liveness checks |
| 5. Lease expired | Exact deadline rejects touch/save; VPS shadow copy emits alert |
| 6. Old identity reconnect | Same owner reacquires durable state; replaced owner fenced; bad account state rejected |
| 7. Duplicate role ownership | Two real loopback sockets, including same lease owner, rejected with LEASE_BUSY |
| 8. Pending order on recovery | Persisted pending-intent fixture survives restart; observer never authorizes restart. No broker pending-order recovery was executed |
| 9. Checkpoint without traffic | Cannot become connected/healthy solely from checkpoint presence |
| 10. Active service, broken path | Stale bridge/lease remains attention-required, execution readiness UNKNOWN |

No broker session exists in the injected tests. They prove bridge state/transport and monitoring behavior, not order exactly-once behavior of an unobserved cTrader restart. No LIVE order was submitted, amended or cancelled by this work. No LIVE checkpoint was reset.

Deployment output: `installed=true`, `trading_service_identity_unchanged=true`, `automatic_recovery=false`. VPS copied-JSON injection output: `VPS_SHADOW_EXPIRED_HEARTBEAT_DETECTED_NO_RESTART`. The timer is active; its real journal contains advancing `V1_HEARTBEAT_OBSERVED` receipts.

## E. Latest verified state and residual risk

Status observation: **23 Nov 2026 02:13:33 UTC / 09:13:33 WIB**. Broker observation: **02:12:30 UTC / 09:12:30 WIB**.

| Component | Verified state |
|---|---|
| BOOTSTRAP | Lease active; last heartbeat 02:13:24.790047 UTC; GROWTH; checkpoint 6 |
| XAUUSD | Lease active; last heartbeat 02:13:29.779152 UTC; checkpoint 2929 |
| EURUSD | Lease active; last heartbeat 02:13:27.782493 UTC; checkpoint 3089 |
| BTCUSD | Lease active; last heartbeat 02:13:31.783790 UTC; checkpoint 4, client revision 5 |
| Bridge | Service active, current health/profile present; BTC feed READY |
| Broker | OBSERVED; history requests succeeded |
| V1 labelled exposure | Reader counts zero open positions and pending orders for all three instruments at that observation |
| Other exposure | `foreign_exposure_present=true`; ownership not established; account must not be called flat |
| Execution readiness | UNKNOWN; lease freshness cannot establish native account binding, PortfolioReady or full order reconciliation |
| Recovery | Automatic restart disabled; safe fail-closed monitoring |

The watchdog detects expired/missing heartbeat or stale observations and records alerts. It does not automatically deliver a phone notification, restart a cTrader host, or make unknown execution state safe. Typical checks run every ten seconds, but scheduler/publisher delays and total VPS failure can delay or prevent detection. It shares the VPS failure domain; external redundancy remains a limitation.

**The underlying failure can recur because its native cause has not been established.** The repaired monitoring removes the old equivalence between service activity and cBot readiness. Exact STOPPED/DISCONNECTED/RECOVERING/HEALTHY native labels are deliberately withheld without direct evidence.

To close the RCA, the missing evidence is the actual cTrader instance Journal/lifecycle export for **18 November 2026 00:45–02:00 UTC / 07:45–09:00 WIB**, plus the stop/start receipt associated with recovery before **23 November 02:04 UTC / 09:04 WIB**. No native cTrader process was present in the VPS process-name inventory at audit time, and no native Journal was exposed through the available GitHub/VPS interface. Root cause cannot responsibly be declared resolved without that evidence.
