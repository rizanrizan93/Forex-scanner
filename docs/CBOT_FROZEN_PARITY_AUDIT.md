# RIZAN frozen strategy ↔ cBot parity audit

Date: 2026-10-11

## Scope

This audit pins the current frozen XAUUSD and EURUSD strategy contracts to the
cBot artifacts that were generated for cTrader, and wires the XAU macro/event
feed required by the frozen XAU signal. It does **not** activate unattended live
trading and does not claim that broker fills will reproduce a historical replay.

Canonical machine-readable contract: `config/cbots/frozen_parity_v1.json`.

## Frozen contracts

| Symbol | Strategy | Contract SHA-256 | Current cBot |
|---|---|---|---|
| XAUUSD | `XAUUSD_LAYERING_226432_RAW_FROZEN_V1` | `7ab0cd24eb2e46480d0ba371ba2cd713c5d6bd30747aee71f91ced5a57fce8bf` | `RizanXAU.algo` SHA-256 `35b1e03e777d1867e3de57a4020d014c271ef5acadab549347496f9a75b58184` |
| EURUSD | `EURUSD_RAW_200_78880_DD4484_FROZEN_V3` | `4b4ef3cbe83c26b0752c11d05c866a7345b5db93b8011af091d9e8ad68d77976` | `RizanEURBatch_v1.1.0.algo` SHA-256 `ade77a372309c3ab513ed2e5f32741caf4ebd13652b2f9a044e4225d18f89274` |

`RizanEUR.algo` SHA-256
`cfe50044f18f70554897a8fe898e32ab54a848954bd28a3bd18d306e56563071`
is retained only as a superseded artifact. The current EUR path is the v1.1.0
batch execution model.

## XAU parity

The frozen selected signal is not a generic XAU setup. It is pinned to two
historical signal streams:

- SELL: group 6, `S10_DIRECTION_000183`, `SWEEP_CANDLE_CONFIRM`, strict H1/M15,
  parameter 24, DGS10 one-day macro filter.
- BUY: group 274, `S10_DIRECTION_006616`, `REGRESSION_CHANNEL_REENTRY`, strict
  H1/M15, parameter 48, DFII10 one-day macro filter.

The current XAU cBot source in `RIZAN_CBOT_MIGRATION_20261010.zip` contains the
same frozen contract hash, four layering stages, depths
`0 / 0.161111 / 0.322222 / 0.483333 R`, confirmed additions, 45-minute add
expiry, 0.01-lot child, 12.5% frozen basket-risk ceiling, 50% margin ceiling,
2.65 ATR structural stop with 0.50 USD floor, 6.6R target and 480-minute hold.

The migration validation reported parity for a 4,000-bar XAU fixture (14 BUY,
18 SELL), 41 XAU confirmation cases, and shared sizing cases. This is signal /
kernel parity evidence, not a ten-year native-cTrader fill replay.

## XAU macro and event contract

The XAU macro/event rule is now explicit in both
`config/cbots/frozen_parity_v1.json` and `cbot_bridge/feeds.py`.

Macro:

- SELL reads FRED DGS10. A negative latest eligible daily delta blocks SELL;
  therefore SELL is eligible only when DGS10 delta is >= 0.
- BUY reads FRED DFII10. A positive latest eligible daily delta blocks BUY;
  therefore BUY is eligible only when DFII10 delta is <= 0.
- An observation becomes eligible at observation date + 2 US federal business
  days, 00:00 America/New_York, matching the conservative frozen replay proxy.
- The latest eligible macro point must be no more than seven days old.

Events:

- categories: NFP, CPI, PPI, JOLTS, ECI, FOMC;
- frozen event window is 15 minutes before to 30 minutes after a release;
- because the XAU planned hold is 480 minutes, a new entry is blocked when a
  relevant release falls between entry - 30 minutes and entry + 495 minutes;
- the live bridge requires both the Forex Factory weekly calendar and the BLS
  official calendar coverage to be healthy; any fetch/schema/week/coverage
  failure is fail-closed;
- snapshots older than 180 seconds are rejected by the XAU cBot.

The bridge persists the same snapshot to
`state/xau_macro_event_snapshot.json` for scanner/dashboard monitoring while
publishing it to the cBot over the WSS bridge.

Historical evidence used final/revised daily FRED series and a conservative
availability proxy rather than point-in-time FRED vintages. The historical
event set was a final calendar rather than an actual-vs-consensus surprise
model. The live bridge therefore implements the **frozen decision contract**,
not a claim of historical vintage-data reconstruction.

## EUR batch parity

The frozen EUR signal/risk contract remains identified by the same contract
SHA-256. `RizanEURBatch_v1.1.0.algo` changes execution topology, not the strategy
contract:

- one virtual child remains 1,000 units / 0.01 lot;
- multiple virtual children may be grouped into one physical broker order;
- at most one broker order is sent per second;
- risk, stage allocation, margin, first-fill anchor, actual fill, commission,
  recovery and durable pending intent are checked at batch quantity;
- checkpoint schema is 2 and execution model is
  `EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1`;
- prefix is `RZEU4B`.

This grouping means physical order count/timing is intentionally different from
a one-order-per-child implementation. It must not be described as identical
broker-order topology. The cBot keeps virtual-child accounting so the frozen
basket mathematics can be compared consistently.

The v1.1.0 source/replay package records a clean build, runtime/planner tests and
replay checks. Native broker fill/latency/reject behavior is still a forward-test
requirement.

## Bridge state compatibility

The integrated `cbot_bridge/server.py` accepts only the current identities:

- `RZXA1` / XAUUSD / contract hash above / checkpoint schema 1;
- `RZEU4B` / EURUSD / contract hash above / checkpoint schema 2 /
  `EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1`.

State persistence uses SQLite WAL + `synchronous=FULL`, compare-and-swap server
revision and a 45-second exclusive lease. Non-finite JSON, wrong account/symbol,
wrong contract, wrong schema, wrong EUR execution model, stale revision and a
second active lease are rejected.

## VPS deployment

`vps_xau_eur_deploy.sh` is the one-command deployment entry point. It:

1. runs the base VPS bootstrap;
2. installs bridge dependencies;
3. verifies committed execution remains `DISABLED` and cTrader remains DEMO;
4. runs the frozen/cBot static parity audit;
5. probes DGS10, DFII10, Forex Factory and BLS;
6. installs restartable systemd services for the cBot bridge and cTrader
   research-cloud runtime;
7. leaves research-cloud stopped if its required credentials are incomplete;
8. leaves the bridge bound to localhost if public TLS configuration is missing.

A remote cTrader Cloud XAU instance still requires a valid public
`wss://<hostname>:25345` endpoint whose certificate matches the hostname and
whose firewall permits TCP 25345. The deployment deliberately does not expose a
plain public WebSocket endpoint.

## Safety and remaining validation

- Repository broker policy remains `DISABLED` / cTrader `DEMO` by default.
- The parity metadata grants no execution authority.
- Do not enable unattended live trading from this deployment.
- Before any broker execution test, verify the actual cBot binary hash against
  `config/cbots/frozen_parity_v1.json`.
- Run a DEMO forward comparison on the same bar stream and compare signal time,
  direction, anchor/ATR, stage depths, stage quantities, SL/TP, expiry,
  rejection reason, restart recovery and actual broker costs.
- XAU will intentionally produce no new entry when macro/event feed health is
  incomplete. That is a valid fail-closed result, not a reason to bypass the
  gate.
