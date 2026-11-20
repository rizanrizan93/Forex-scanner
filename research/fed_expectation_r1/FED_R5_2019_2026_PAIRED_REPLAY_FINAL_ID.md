# RIZAN Fed R5 — FINAL 2019–2026 FOMC × XAU Entry Alignment Replay

**Research conclusion:** Macro-direction-only gating is implemented
as a fail-closed READ-ONLY filter. On all **69 FOMC meetings** from
2019 to November 2026, the original V4 rejection engine provided
**zero qualifying technical entry candidates** within the valid
post-communication macro window. A new observational M1 continuation
pattern gives limited H1 directional samples but does NOT establish
>=80% BUY and SELL simultaneously. **NO PRODUCTION.**

## Verified reproducibility

- Final SUCCESS GitHub Actions run:
  https://github.com/rizanrizan93/Forex-scanner/actions/runs/44650113504
- 8/8 yearly source replay jobs, 69/69 official FOMC events, 69/69
  real XAUUSD M1 historical source windows loaded, zero source failures,
  aggregate job successful.
- 20/20 yearly source/meeting-unit aggregation tests passed;
  57/57 Fed direction + technical gate tests passed in prior R5 run;
  paired pilot test 19/19 passed in the latest clock-corrected CI.
- FOMC market response source is **official San Francisco Fed USMPD
  XLSX**, SHA256
  `2b91297c42cf692dd74f65eabf7ee97f81d452676e23fa02edb222bfa60f0d0a`.
- XAU M1 secondary-market HistData using a pinned downloader commit
  `4a3c11b67f97758f6e3f77a3e5905b6aa87367b8`, verified
  UTC-normalized SHA for each event stored in year artifacts.
- Original event dates and full/statement/press windows are read from
  the official source; window types and exact Eastern ET release
  clocks matched, no invented timestamps.
- Per event XAU source requests span 20 calendar days preceding
  through 7 days following the announcement; M1 signal detection
  only after the official completed communication window.
- Post-event M1 scanning window ends at the **earlier** of 90
  minutes after that window or 150 minutes after the original
  event RELEASE. For regular full press conference events finishing
  about +90 minutes after statement, the effective scan is only
  60 minutes. Exceptional long 2020-03-15 announcement is counted
  as a real source/event **WAIT** because the event macro validity
  expired before its full window finished. This is NOT a data failure.
- Synthetic historic bid/ask spread **$0.50/oz**. No broker
  executable fill data or overnight carry.
- H1 outcomes measured from the **first eligible M1 continuation
  structure-break observation** per macro rule/side/FOMC meeting.
  Missing future contiguous 60 M1 bars => CENSORED, never favorable
  imputation. Multiple within-event M1 continuations are NOT
  independent trades.

## Original V4 technical entry frequency

| Official FOMC year | Events/real-price sources | V4 entry-qualified M1 |
|---|---:|---:|
| 2019 | 9/9 | 0 |
| 2020 | 13/13 | 0 |
| 2021 | 8/8 | 0 |
| 2022 | 8/8 | 0 |
| 2023 | 8/8 | 0 |
| 2024 | 8/8 | 0 |
| 2025 | 8/8 | 0 |
| 2026 | 7/7 | 0 |
| **Total** | **69/69** | **0** |

This is NOT evidence V4 is bad in all market regimes. It is
**specific to the early post-FOMC valid event window under the strict
historical synthetic-spread and rejection/HTF/opposing-room gates.**
It does mean a policy of "only enter when R4 direction and V4
ENTRY_CANDIDATE agree" would produce **no researched entries** in
this replay. Loosening V4 indiscriminately risks false signals.

## Separate M1 continuation observation — H1 direction after costs

All rules predeclared in the 2023 pilot / R4 research branch, event-unit
cooldown and initial macro expiry enforced. These are **EX-POST
FOMC-side overlays, not PIT tradeable signals**:

| Historical EX-POST macro side selector | BUY correct/n | SELL correct/n |
|---|---:|---:|
| MP2 + TIPS10Y + DXY | **7/9 (77.78%)** | 5/7 (71.43%) |
| OIS1Y + TIPS10Y + SP500 policy-like veto | 6/11 (54.55%) | **9/11 (81.82%)** |
| OIS1Y + TIPS10Y + DXY | 9/14 (64.29%) | 10/13 (76.92%) |

95% Wilson interval:
- MP2/TIPS10/DXY BUY **45.26–93.68%**; SELL **35.89–91.78%**.
- Policy-like OIS/TIPS/equity BUY **28.01–78.73%**;
  SELL **52.30–94.86%**.
- OIS/TIPS/DXY BUY **38.76–83.66%**;
  SELL **49.74–91.82%**.

No model establishes 80% accuracy simultaneously on both directions
with an independent and adequately sized sample. **Several model
results are calculated from overlapping SAME FOMC events**, so the
different rows must NOT be pooled as extra independent observations.
2019–2026 is a repeatedly researched dataset, NOT prospective OOS.

### Selected FOMC 2023-09-20 audit, with corrected clock

- Official FOMC statement release **18:00Z**; entire press
  communication window finished **19:30Z**; initial R4 context
  expired **20:30Z**, giving exactly 60 eligible clock minutes.
- Historical price September 2023 **28,330 M1**, SHA256
  `0127bae35fc66a5ba44eccf1f407fe03c7772a9d3eff2effd4e12cb98714668c`.
- Ex-post OIS1Y/TIPS10/DXY and OIS1Y/TIPS10/equity both SELL;
  MP2/TIPS10/DXY conflicted and chose WAIT.
- V4 0 qualifying entry in those 60 minutes.
- M1 continuation 3 correlated raw SELL structure breaks;
  after *first unique per FOMC* restriction, H1 endpoint
  favorable 1/1. This is **ONE previously-examined meeting,
  not 100% win-rate validation**.

## What the project can/cannot presently do

**Implemented in research:**
- **SELL WATCH → only SELL V4 technical candidates** can ever pass
  the R5 macro alignment filter; BUY blocked.
- **BUY WATCH → only BUY V4 candidates** can pass;
  SELL blocked.
- **WAIT, old quote or mismatched official event → both sides blocked**.
- Existing closed M1/M5, spread, rejection invalidation,
  anti-chase and opposing-level rules remain intact.
- Read-only research dashboard labels V4 patterns as
  **technical-only**, and R5 states macro WAIT because
  genuine live intraday OIS/TIPS/SP500/DXY feeds are still absent.
- `fomc_continuation_observation_r5.py` evaluates M1 trend
  continuation with EMA9 + 3-bar structure break for future study
  but **cannot authorize entries**.

**NOT implemented or proven:**
- No genuine first-observed live quote ingestion for OIS1Y,
  TIPS10Y, SP500, dollar and broker executable XAU M1 bid/ask.
- No prospective real-money, forward-test, walk-forward alpha
  or live directional accuracy.
- No statistically supported >=80% BUY and SELL performance
  on H1, H4, D1, D5 or D10.
- A 150-minute initial FOMC shock does NOT authorize fixed
  daily/weekly directional entries. That requires continuous
  independently captured Fed policy-path, real-yield, DXY
  and updated communication revalidation.

## Next preregistered research priorities

1. **V4 structural room redesign:** require causal confirmed
   M5/H1 swing pivots (not every tiny M5 candle high/low). Keep
   this separate from continuation (no hindsight pivot lookahead).
   Compare same real-price event IDs with unchanged cost model.
2. **Continuation risk labels:** first entry per FOMC, measure
   directional H1 net, MFE/MAE, first adverse barrier and
   invalidation, with post-news spread/slippage stress testing.
3. **Rolling Fed expectation regime:** develop an explicit
   revalidated H4/D1/D5/D10 direction state from genuinely
   captured OIS/SOFR path, intraday TIPS/nominal yields, DXY
   and subsequent FOMC minutes/comments. Expire on conflict.
4. **Prospective event capture:** code/thresholds frozen BEFORE
   future events; collect exact released, published, ingested
   timestamps. Historical USMPD ex-post window changes cannot
   be retroactively labeled true captured PIT quotes.
5. **Sample expansion:** verified FOMC minutes, Fed speeches,
   CPI, Core PCE and NFP events with unambiguous timestamps.
   Any >=80% raw rate with tiny n is only a discovery.

**Release gate: LOCKED; no cTrader LIVE or production ForexScanner
modification.** See draft PR #893, parents #892/#891/#890/#889/#887.
