# RIZAN R6.3 — FINAL Paired Price-Action Veto Audit (XAUUSD / FOMC 2019–2026)

**Decision: NO measurable robust improvement. Keep as conflict WARNING / safety
context, NOT as a historically-proven mandatory entry filter.**

**Verified GitHub Actions run:** https://github.com/rizanrizan93/Forex-scanner/actions/runs/44686277617

## Integrity and design

- 18/18 protocol, as-of confirmed bar and first-signal unit tests PASS.
- All 8 yearly real XAUUSD M1 historical replay jobs SUCCESS, 69/69
  official FOMC event windows/secondary market price source windows,
  zero source failures, final aggregate SUCCESS.
- Exactly **67 first-candidate records across three models**,
  **65 horizon-evaluable**; these are NOT 67 independent meetings:
  multiple macro models select the SAME 69 meetings.
- Baseline H1 correct counts and +$3 target-before-$3 adverse counts
  are separately ASSERTED EQUAL to the prior sealed R6 benchmark
  for each macro model and side (otherwise the aggregate aborts).
- R6.3 uses the **EXACT read-only production-code M15/H1 EMA20
  price + slope filter**, with H4 opposing trend veto, applied
  at the first original R6 M1 continuation signal timestamp;
  full M1 timestamp OPEN and resampled M15/H1/H4 candle CLOSE
  counts must be valid, never forming/future.
- Original entry timestamp, direction, assumed $0.50/oz roundtrip
  cost, 60 actual consecutive M1 future bars and outcome labels
  remain unchanged. If first candidate is rejected by R6.3,
  **NO second/later candidate may be substituted**.
- Price data is REAL secondary-market M1, but historical FOMC
  macro-factor side is the **EX-POST USMPD market-study oracle**,
  NOT genuine first-seen point-in-time Fed/OIS/TIPS/DXY data.
  Broker actual spread, slippage, fills, financing unavailable.
- 2019–2026 have been studied repeatedly, not an untouched
  independent out-of-sample sample. No prospective LIVE edge.

## H1 direction and coverage: original first signal versus retained by R6.3

| Ex-post macro rule | Side | Original H1 correct/n | After R6.3 correct/n | Change percentage points | Retained coverage | Correct rejected | Wrong rejected |
|---|---|---:|---:|---:|---:|---:|---:|
| MP2+TIPS10Y+DXY | BUY | 7/9 = 77.78% | 4/5 = 80.00% | +2.22pp | 55.56% | 3 | 1 |
| MP2+TIPS10Y+DXY | SELL | 5/7 = 71.43% | 2/4 = 50.00% | -21.43pp | 57.14% | 3 | 0 |
| OIS1Y+TIPS10Y+SP500 opposite | BUY | 6/11 = 54.55% | 3/6 = 50.00% | -4.55pp | 54.55% | 3 | 2 |
| OIS1Y+TIPS10Y+SP500 opposite | SELL | 9/11 = 81.82% | 5/7 = 71.43% | -10.39pp | 63.64% | 4 | 0 |
| OIS1Y+TIPS10Y+DXY | BUY | 9/14 = 64.29% | 5/8 = 62.50% | -1.79pp | 57.14% | 4 | 2 |
| OIS1Y+TIPS10Y+DXY | SELL | 10/13 = 76.92% | 5/8 = 62.50% | -14.42pp | 61.54% | 5 | 0 |

**Five of six direction-model comparisons became worse**, one
appeared marginally better with very small sample (BUY 4/5).
Wilson95 H1 direction for BUY 4/5 is only **37.55–96.38%**.
Under OIS1Y/TIPS10/SP500 SELL the filter rejected **four
previously correct signals and ZERO wrong signals**, reducing
the rate from 81.82% (9/11) to 71.43% (5/7). This is
particularly strong evidence AGAINST claiming that a stricter
H1/M15 same-direction veto necessarily helps this particular
post-event continuation setup.

### Risk path: first target +$3 after assumed cost BEFORE -$3 adverse

| Ex-post rule | Side | Original target-first | After R6.3 target-first |
|---|---|---:|---:|
| MP2/TIPS10/DXY | BUY | 4/9 = 44.44% | 2/5 = 40.00% |
| MP2/TIPS10/DXY | SELL | 3/7 = 42.86% | 2/4 = 50.00% |
| OIS1Y/TIPS10/SP500 | BUY | 6/11 = 54.55% | 3/6 = 50.00% |
| OIS1Y/TIPS10/SP500 | SELL | 6/11 = 54.55% | 3/7 = 42.86% |
| OIS1Y/TIPS10/DXY | BUY | 7/14 = 50.00% | 4/8 = 50.00% |
| OIS1Y/TIPS10/DXY | SELL | 7/13 = 53.85% | 4/8 = 50.00% |

No dual-side model meets >=80% H1 target-before-adverse.
A nominal 50% result on only 4 retained SELL events is NOT
evidence of profitable broker execution after realistic costs.

## Decision and follow-up validation

1. **Do not claim R6.3 improves entry accuracy based on these
   samples.** Its legitimate use today is to SHOW a macro/price
   disagreement and stop a one-variable mechanically inferred BUY.
   Keep display warnings and the non-executable WAIT policy; do
   not rewrite Frozen V1 or authorize cBot orders.
2. If testing an entry timing filter in future, pre-register
   a less restrictive *price confirmation* hypothesis (e.g.
   explicit liquidity shift plus structural reclaim rather than
   mandatory EMA20 H1/H4 alignment), **BEFORE** inspecting
   new independent data, with equal sample/event constraints.
3. The user's 20 November example involves daily US2Y/US10Y
   and a minute timestamped DXY proxy. R6.3 FOMC event-only
   EX-POST tests CANNOT establish all-day accuracy for this case.
   A valid 2019–2026 all-day comparison would require genuine
   archived point-in-time daily/intraday yields, DXY, Fed policy
   expectations and real broker M1 quotes at signal timestamps.
4. Preserve strict anti-lookahead, one first signal/event,
   measured retained vs blocked correct/wrong observations,
   80% two-sided criterion with meaningful independent n
   and prospectively frozen follow-up validation.

**Release gate remains LOCKED.** This study branch is draft
and does not modify production XAU dashboard, cBots,
Frozen V1, Manual R3, bridge, orders or account risk.
