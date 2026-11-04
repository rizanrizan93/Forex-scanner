# RIZAN BTC10 FullFix — complete replacement, 4 November 2026

This release is a complete three-instrument cBot, named `RizanPortfolioBTC10FullFix`, version 3.3.1. The user requested a full replacement that repairs the existing BTC lock automatically instead of a manual checkpoint edit. It retains the frozen F005_BTC10_FROZEN_20261102 profile, native labels, remote keys, parameter definitions and strategy hash.

## Changes

- Retains the corrected UTC-week schedule-cache invalidation before weekend decisions.
- Adds a narrowly scoped, automatic recovery for the observed never-traded BTC checkpoint on account suffix 7903: lock 2026-11-09 00:00 UTC becomes 2026-11-02 00:00 UTC.
- The repair is considered only during that UTC week, when the broker timetable permits entry, after identity validation, native reconciliation, exclusive bridge lease and a durable ACK.
- It requires full account binding, a fresh strategy feed, portfolio readiness, no account positions or pending orders, no other engine intent/risk/margin reservation, and a clean original and current BTC checkpoint. Faults, sending/exit intents, queued batches, prior BTC signals/expiry or BTC-labelled history exclude migration.
- Backs up the exact pre-repair state in instance LocalStorage using a separate valid key and verifies its readback. Only WeekendLockUntil and monotonic Revision change. Watermarks, strategy fields, expiry and sequence are not reset.
- Uses the normal bridge save/CAS/lease/ACK protocol. There are no direct SQLite edits, forced leases or broker requests on the repair tick. Entry remains blocked until the repair revision is acknowledged. Backup/persistence uncertainty blocks new entries.
- Arbitrary future locks and normal weekend protection are not cleared. Old signals are not replayed.

The runtime LocalStorage backup is not a claim of cross-restart cloud file retention. A private remote SQLite snapshot was successfully made on the VPS at 4 November 08:29:58 WIB; it is pre-maintenance evidence, not a later CAS value. The LIVE cBot and production bridge were not modified in preparing this release.

## Scope

Of 21 original source/project files, 18 are byte-identical to the frozen release. BtcEngine.cs contains the cache patch and recovery integration. RizanXauEurPortfolio.cs only changes the public robot class name. The project changes name/assembly metadata to 3.3.1. BtcWeekendRecovery.cs is new. XAU/EUR strategy/execution sources, FrozenR3 profile, BTC signal/risk/batch/intent/bridge code and BtcWeekendPolicy remain byte-identical.

Earlier audit P1 (XAU SELL 3 November 19:05 WIB) remains unverified; this release does not bypass macro/news guards to force that candidate. P2 was consistent with the scheduled XAU market break. No unproven strategy/execution defect is claimed fixed.

## Validation

Official cTrader.Automate 1.0.21 / net6.0 build: 0 warnings, 0 errors.
Build source: 2fc87dc90b7bf0e7b6468b7ed70d944aa8b0cfef.
Successful workflow: https://github.com/rizanrizan93/Forex-scanner/actions/runs/41757212527

- 64 scoped lock recovery checks, including exact field preservation, backup failures, ACK withholding, disconnect, local revision ahead, unsafe checkpoints and time windows.
- 58 weekend/calendar checks.
- 449 native BTC checks.
- 54 XAU/EUR native checks.
- 295 gate checks / 141 historical BTC signal times and sides.
- 920 checks total, simulated brokers only, zero real test orders.
- Binary metadata verified: robot cAlgo.Robots.RizanPortfolioBTC10FullFix, assembly 3.3.1.0, UTC, all parameters identical to the prior verified frozen binary; default Kirim order=false.
- Additional empty-new-instance storage / remote adoption validation PASSED: https://github.com/rizanrizan93/Forex-scanner/actions/runs/41757501169 (test commit 2051a3e8c46c6a1b540ede32c11eba2052421da0). Production source is unchanged from the binary build commit.

This is not a new profit/DD replay. Cloud import, actual LIVE deployment, automatic state repair and a real new order remain unverified until the user installs and starts this binary and runtime evidence is inspected.

## Simple deployment for the owner

1. Choose a time when account 7903 has no positions or pending orders. Keep a private copy of old parameters and token.
2. Stop the old combined instance. Do not delete it. Wait about 60 seconds for its existing lease to expire.
3. Import RizanPortfolioBTC10FullFix_20261104.algo in cTrader Android.
4. Select the same full account number ending 7903. Copy the old parameter values, including bridge URLs and token. Keep all three instruments enabled and all frozen risk/SL/TP values unchanged. Set Kirim order=true when starting the replacement for normal execution.
5. Start only the FullFix instance. Do not run the old and new instances together. The bridge connection, state recovery and scoped lock migration run automatically.
6. Send the Journal for verification with account/token details masked. The binary prints BTC_FULLFIX_20261104 and, only if the migration occurs, BTC_WEEKEND_LOCK_REPAIRED with awaiting_remote_ack=True. That message alone is not proof that the remote ACK or all entry guards subsequently passed.
7. A new natural frozen signal is required for an order. Do not chase or replay an old signal.

If a recovery/identity/persistence fault occurs, do not start another instance or reset checkpoints. Preserve current state and journal for reconciliation. Do not blindly restore an older checkpoint after any new activity.

## Binary

Filename: RizanPortfolioBTC10FullFix_20261104.algo
SHA256: 8927fb01bc209471e51af56db79269c00f2b719cbe06c681cb0c56885e275cce
