# Rejection Engine V3 — Actual M1 replay audit (2026-11-19)

**Research-only.** Tested PR #887 branch without modifying `main`, Frozen V1,
Manual R3, cBots, bridge, order routing or account risk.

## Reproduction and provenance

CI: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44494465850

Script: `scripts/replay_rejection_v3_outcomes.py`; 23 tests passed in the
replay methodology job. Event states are carried chronologically, with
entry candidates emitted at closed M1, and later M1/M5 closes only used in
outcome labeling. Historical bid/ask are **not recorded**; replay injects
hypothetical bid/ask from M1 close ±$0.25 ($0.50/oz spread). Signals are
historical reconstructions, **not** archived actual scanner alerts or fills.
Same-minute target/adverse ambiguity is resolved against the position.
Early/late watch events and entry-eligible events are explicitly separated.

### cTrader public read-only M1, Nov 2026

- 12,000 rows; SHA-256 of normalized M1 frame:
  `09c787a93d72a4793d9e6da85e0bcb787356ecdee04e7970128d9a3e7347cacb`
- Source publication `2026-11-19 09:14:42 UTC`.
- Screened `2026-11-13 02:45 UTC` to `2026-11-18 17:11 UTC`.
- 4,976 successfully evaluated M1 closes, 24 rejected unavailable states.
- 99 raw early BUY and 104 raw early SELL detections, **not** qualified entries.

| V3 candidate subset | BUY n | SELL n | SELL H1 correct | SELL H4 correct | SELL $3 before -$3 (60m) | SELL $10 before -$5 (240m) |
|---|---:|---:|---:|---:|---:|---:|
| Eligible early | 0 | 14 | 8/14 (57.14%) | 10/14 (71.43%) | 10/14 (71.43%) | 5/14 (35.71%) |
| Eligible retest | 0 | 12 | 5/12 (41.67%) | 8/12 (66.67%) | 7/12 (58.33%) | 4/12 (33.33%) |

- Early SELL Wilson 95% interval for $3-before-$3:
  **45.35%-88.28%**, not a confirmed lower bound above 60%.
- 8/14 early SELL crossed their frozen failure boundary on a closed M1
  within 60 minutes. Importantly, **5 of 10** early SELL that hit $3
  before -$3 **subsequently also crossed their rejection invalidation
  boundary within 60 minutes**. This demonstrates temporary rejection
  does not establish sustained reversal.
- All early SELL were clustered into four days: Nov 13 (1), Nov 16 (6),
  Nov 17 (2), Nov 18 (5).
- *Bare* early wick (not qualifying entry): BUY n=85, H1 29.41%;
  SELL n=93, H1 53.76%. Do not interpret these as valid entry signals.

### HistData public secondary market M1, Sep 2023

- Requested 2023-09-01 to 2023-09-29; 28,330 M1 rows; zero failed periods.
- Source conversion fixed EST UTC-5 to UTC, pinned downloader commit
  `4a3c11b67f97758f6e3f77a3e5905b6aa87367b8`;
  normalized CSV SHA-256
  `0127bae35fc66a5ba44eccf1f407fe03c7772a9d3eff2effd4e12cb98714668c`.
- Screened `2023-09-07 17:23 UTC` to `2023-09-13 09:04 UTC`.
- 4,875 evaluated M1 closes. **Eligible early BUY=0, SELL=0;
  retest BUY=0, SELL=0**.
- Bare early wick BUY n=98, H1 correct 33.67%, $3-before-$3 11.22%;
  SELL n=89, H1 correct 34.83%, $3-before-$3 6.74%.
  These broad detections are not qualified strategies.

## Interpretation and methodological limits

- **DO NOT DEPLOY / DO NOT MERGE.** V3 has not met BUY + SELL >=60%
  direction or durable reversal. BUY entry n=0; SELL n=14 insufficient.
- H4 71.43% in 2026 is based on only 14 SELL events and does **not** imply
  60%+ generalization. H1 SELL was 57.14%.
- Rejection event watch detection is abundant, but most do not qualify as
  entries. This is an important trade-frequency constraint.
- As-of source and OHLC SHA are documented, but historical quote-age,
  bid/ask spread, commissions, slippage and rollover are not measured.
- 2025–2026 already influenced research, and the 2023 month is a
  falsification sample, not pristine out-of-sample.
- The initial 2026 screening window ends Nov 18. A separately labeled
  Nov 19 post-hoc diagnostic was therefore run (see below). Neither run
  represents archived LIVE scanner emissions.
- `confirmed_M1_pct` is an *eventual structural level crossing* metric,
  not proof confirmation occurred before invalidation. Do not cite it as
  predictive accuracy; a strict event-order audit is required.
- Retest and early samples are not paired by underlying event, so
  comparisons are descriptive only.

## Falsification gates next

1. Explicitly compute *first-confirmation-before-first-invalidation* and
   *target-before-invalidation*, with separate H1/H4 outcomes.
2. Capture immutable prospective V3 alerts/clock times and compare with
   future broker quotes; synthetic quote replay cannot establish LIVE alert
   performance.
3. Expand to distinct predeclared years, keep year & BUY/SELL splits,
   compare to same-period unconditional direction baselines, and report
   day-clustered uncertainty and signal counts.
4. Test user-specific Nov 19 bounce-and-breakout as a separately labeled,
   **post-hoc diagnostic**, with adequate forward history and without
   claiming it is an independent holdout.
5. Leave PR #887 **draft** until causality and empirical dual-side gates pass.

## Explicit Nov 19 post-hoc diagnostic: failed early SELL

CI run: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44495555972

- Public read-only cTrader M1 snapshot published **2026-11-19 09:21:11 UTC**;
  normalized frame SHA-256
  `f715564b57005407ed84b3a6cc62d0c7b7b03f56b64def21f7890a3d2e6583f1`.
- Screened `2026-11-16 19:55 UTC` through
  `2026-11-19 05:19 UTC` (12:19 WIB); complete forward outcomes were
  observed after that cutoff, not used to decide the signal.
- 3,235 successfully evaluated closed M1, fixed hypothetical spread $0.50/oz.
- Latest overlapping sample: **BUY eligible n=0**, **SELL eligible early
  n=8**, SELL early H1 correct **4/8 (50%)**, H4 correct **6/8 (75%)**,
  $3-before-$3 **6/8 (75%)**, $10-before-$5 **3/8 (37.5%)**.
  These **overlap** the earlier Nov 2026 sample; do NOT pool them as
  independent observations.
- The specific 2026-11-19 04:52 UTC (11:52 WIB) event was
  `ELIGIBLE_EARLY_ENTRY SELL M5 EMA20`, frozen level **3723.369**,
  invalidation **3724.83121**. The +$3 target was **NOT** reached
  before adverse −$3 in the next 60 minutes (ADVERSE_FIRST); the
  rejection crossed its invalidation boundary on a closed M1 within
  60 minutes and a completed M5 close confirmed a breakout within 240m.
- The 04:56 UTC (11:56 WIB) `ELIGIBLE_RETEST SELL` at the same
  zone also produced `ADVERSE_FIRST` and was invalidated within H1.
- This resembles the user's posted fall-then-bullish-spike scenario, but
  source quotes, alert issuance, and fill cannot be matched to screenshots
  precisely. It is a **negative falsification example** of the current
  entry timing despite the lifecycle kill-switch.

**Result:** V3 is **NOT ready for production**. The invalidation control works
conceptually, but does not by itself prevent over-late SELL entries next to
support or price acceleration. Do not post-hoc tune thresholds against this
known Nov 19 case and then represent it as a pristine holdout; formulate
predeclared, forward-only diagnostics for proximity to opposing liquidity,
M1/M5 impulsive regime, and quote age on other historical periods.
