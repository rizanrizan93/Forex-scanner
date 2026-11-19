# Rejection Engine V4 — First actual-price replay (19 Nov 2026)

**Research-only / NO PRODUCTION MERGE.** V4 splits Trend Rejection from
Countertrend Reversal on BOTH BUY and SELL. Previously used Sep 2023 and
Nov 2026 samples are exploratory, **not pristine holdouts**.

## Evidence and method

- Workflow: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44530612012
- V4 classifier and replay were specified prior to opening these results
  in `docs/rejection_v4_dual_side_prespecified_20261119.md`.
- 44 existing V4/lifecycle/regression tests passed; V4 replay-specific
  job passed 31 deterministic unit tests. Unit tests do NOT measure
  predictive accuracy.
- Closed M1 UTC, past-only completed M5/H1/H4. Forward labels generated
  after candidate emission; hypothetical next M1 open entry.
- Cost is fixed modeled $0.50/oz spread, NOT archived bid/ask or slippage.
- Bar ambiguity resolved against candidate; 60-minute signal cooldown.
- BUY and SELL are separately reported with sample size and Wilson 95%
  interval before claims of >60% directional accuracy.

## cTrader read-only M1 2026

- Snapshot published `2026-11-19 13:11:27 UTC`.
- 12,000 M1 OHLC rows; normalized SHA-256:
  `e8a3508e907c7a6430149750e2a977c5a6981fd5495812325ea257add99c8c40`.
- Screened `2026-11-13 06:42` to `2026-11-18 12:48` UTC;
  4,452 evaluated minute closes. This does NOT include the user's
  later Nov 19 screenshot itself.
- Countertrend BUY had 268 `SWEEP_RECLAIM_WATCH` emissions, 6 M1
  `MSS_CONFIRMED` observations, but **0 eligible entry candidates**.
- Trend SELL had 34 `RECLAIM_DETECTED` observations, 2 raw gated
  entry candidates, but only **1 mature independent outcome** after
  cooldown/censoring. That single SELL was directionally profitable
  at H1, unprofitable at H4 end-close, hit the $3 target before -$3
  in H1, and hit the $10 target before -$5 in H4. n=1 is NOT proof
  of positive expectancy or ≥60% accuracy.
- All other n, including Trend BUY and Countertrend SELL/BUY eligible
  candidates, were 0.

## HistData Sep 2023 (public secondary market)

- 28,330 M1 rows, no failed source periods, downloader pinned commit
  `4a3c11b67f97758f6e3f77a3e5905b6aa87367b8`.
- Source CSV SHA-256
  `0127bae35fc66a5ba44eccf1f407fe03c7772a9d3eff2effd4e12cb98714668c`;
  timestamps fixed EST UTC-5 converted to UTC.
- Screened `2023-09-07 17:23` to `2023-09-13 00:44` UTC;
  4,250 evaluated minute closes.
- Countertrend BUY: 151 `SWEEP_RECLAIM_WATCH`, 13
  `MSS_CONFIRMED`, but **BUY eligible n=0**.
- No eligible SELL (Trend or Countertrend); **SELL n=0**.

## Interpretation

V4 fixes a MODEL COVERAGE limitation: countertrend BUY setups are now
identified explicitly, even when H1/H4 bias remains bearish. This is
**not yet predictive success**: all countertrend BUY setups are blocked
after MSS by at least one additional entry gate.

Potential blockers include spread, opposing swing proximity or
anti-chase. The research replay script has been instrumented to
count each gate failure; do not adjust thresholds until that audit
reports actual contributions. Even then, causal ablation on new
predeclared periods is required, rather than overfitting these
historical samples.

**Final status:** ≥60% accuracy separately for BUY and SELL is
NOT DEMONSTRATED. Insufficient n, no real quote-age or broker fills,
no prospective comparison. Keep PR #887 **DRAFT**; no Frozen V1,
Manual R3, cBot LIVE, bridge or order changes.

## Gate diagnosis and ungated MSS ablation (second research pass)

CI: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44532454336
**32/32** V4/replay/lifecycle unit tests passed. Historical replay
completes on both read-only sources. The ablation uses the *same*
predeclared price windows, does **not** change entry thresholds, and
explicitly counts observation patterns separately from eligible entries.

### Why BUY candidates were rejected

| Source | BUY MSS occurrences | Opposing-room fails | Anti-chase fails | Spread assumption fails |
|---|---:|---:|---:|---:|
| Nov 2026 snapshot | 6 | 6 | 4 | 0 |
| Sep 2023 snapshot | 13 | 11 | 13 | 13 |

Failures overlap. In the 2023 low-volatility sample a **fixed synthetic
$0.50** spread exceeds the threshold of 20% of ATR(M5) for all 13
BUY MSS events. This does NOT demonstrate true 2023 broker spreads or
execution costs. In Nov 2026 all 6 failed the current nearest-M5-high
opposing-room gate, suggesting the *definition of opposing structure*
should be audited rather than removing the guard.

### What happens if we ignore entry gates?

Observations are distinct events after a 60-minute cooldown. These
are **NOT** trades approved by V4, and n is very small.

| Source | Raw bullish MSS n | H1 direction | H4 direction | $3-before-$3 H1 | $3 before frozen invalidation |
|---|---:|---:|---:|---:|---:|
| Nov 2026 | 4 | 2/4 (50%) | 1/4 (25%) | 2/4 (50%) | 3/4 (75%) |
| Sep 2023 | 4 | 2/4 (50%) | 1/4 (25%) | 0/4 (0%) | 0/4 (0%) |

**Interpretation:** no evidence that indiscriminately accepting previously
blocked BUY MSS patterns improves directional accuracy. It may merely
increase false positives. The two periods are previously analyzed and
are not an independent holdout; 4 observations per window do not
support precise probabilities.

### Decision

- Preserve **BUY WATCH** for countertrend liquidity sweeps and **BUY MSS
  CONFIRMED** as an observational structural status; do not call either
  a valid executable BUY entry without passed cost, room and anti-chase.
- Preserve countertrend SELL with symmetric logic.
- Further hypothesis: compare significant completed M5/H1 swing levels
  rather than nearest arbitrary candle high/low for opposing-room,
  but predeclare an entirely separate causal ablation on other years.
  Do **not** tune on this known Nov 2026 case and relabel it a holdout.
- Historical bid/ask, latency and slippage are not verified. Strict
  >=60% BUY **AND** SELL is still **unproven**; production remains unchanged.
