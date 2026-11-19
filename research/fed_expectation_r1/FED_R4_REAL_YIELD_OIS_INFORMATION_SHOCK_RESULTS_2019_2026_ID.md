# RIZAN Fed Macro R4 — 2019–2026 OIS/TIPS/Stocks × XAUUSD

**Status:** Completed retrospective event-study research, **NOT** production-validated BUY/SELL prediction.

**Version:** R4 research branch `research/fed-information-shock-r4-20261120`; [draft PR #892](https://github.com/rizanrizan93/Forex-scanner/pull/892)

**Verified CI:** https://github.com/rizanrizan93/Forex-scanner/actions/runs/44641555539 — **36 tests passed**, replay SUCCESS, all **69/69** official event-window rows matched by type, date and original Eastern-time release clock, with **0 unmatched rows**.

## Inputs and assumptions

- Source: original San Francisco Fed USMPD full XLSX, SHA256
  `2b91297c42cf692dd74f65eabf7ee97f81d452676e23fa02edb222bfa60f0d0a`.
- Financial-market variables: MP2, OIS1Y/OIS2Y, UST2Y/UST10Y,
  TIPS5Y/TIPS10Y, SP500, DXY.
- MP2/OIS/Treasury/TIPS are **percentage-point CHANGES**, converted
  to **basis points** by ×100; SP500/DXY are percent returns, NOT bps.
- `UST10Y - TIPS10Y` measures the CHANGE in the nominal-minus-real
  10-year spread within the same event window, not an observed
  level of inflation expectations and not pure inflation expectations.
- Historical XAUUSD entry/future returns: the previously sealed R1
  real secondary-market M1 ledgers for all 69 FOMC communication dates
  2019–2026, not synthetic prices; daily session gaps are censored.
- Fixed hypothetical $0.50/oz round-trip transaction cost; historical
  broker spread/slippage, overnight carrying cost and true fills
  not verified.
- D1, D3, D5, D10 = subsequent 1/3/5/10 fully observed weekday
  UTC trading-session closes. Events crossing the following FOMC
  are excluded from the independent horizon group.
- **NO input from historical USMPD is established as archived real-time
  at the FOMC decision minute.** Completed-window responses are
  ex-post study observations. Outputs are candidate correlations
  rather than historically executable predictions.
- 2019–2026 has been researched multiple times. 10 model families ×
  4 horizons × 2 sides are exploratory multiple comparisons, not
  a pristine untouched backtest.

## Fed policy-like versus information-like event classification

Rule: MP2 rate expectation and SP500 share **opposite signs** =>
policy-like; **same signs** => information-like (proxy for the
Jarocinski–Karadi high-frequency sign logic). This does not prove
structural causality or explain all macro factors:

| Category | FOMC event count |
|---|---:|
| POLICY_LIKE | 19 |
| INFORMATION_LIKE | 3 |
| UNKNOWN_SMALL/UNRESOLVED | 47 |
| **Total** | **69** |

Reasons for abstention include small joint reaction (under MP2 2bp
or SP500 0.10% thresholds) and missing/mixed data. An information-like
event is *not* automatically an inverted BUY or SELL; the market
direction needs separate corroboration.

## D1 outcomes: BUY and SELL separately

| Rule | BUY wins / n | SELL wins / n |
|---|---:|---:|
| MP2-only | 10/15 = 66.67% | 4/9 = 44.44% |
| MP2 + TIPS10Y + DXY | **8/10 = 80.00%** | 4/7 = 57.14% |
| OIS1Y + TIPS10Y + DXY | 11/17 = 64.71% | 9/13 = 69.23% |
| TIPS10Y + DXY | 17/28 = 60.71% | 12/16 = 75.00% |
| TIPS5Y + TIPS10Y + DXY | 17/27 = 62.96% | 11/15 = 73.33% |
| MP2 + OIS1Y + TIPS10Y + DXY | 8/10 = 80.00% | 4/7 = 57.14% |
| MP2 + TIPS10Y + DXY + equity veto | **6/6 = 100%** | 4/6 = 66.67% |
| MP2 + UST2Y + equity veto | 6/8 = 75.00% | 4/8 = 50.00% |
| **OIS1Y + TIPS10Y + equity veto** | **9/13 = 69.23%** | **9/11 = 81.82%** |
| TIPS10Y only | 18/30 = 60.00% | 13/20 = 65.00% |

**Never promote** the apparently perfect **6/6 BUY**: Wilson
95% CI **60.97%–100%** and this is an already-inspected sample.
Likewise the **9/11 SELL** result has Wilson 95% CI
**52.30%–94.86%**, not confidence >=80%.

### Year-stratified D1: OIS1Y + TIPS10Y + equity veto

| Prior research segment | BUY | SELL |
|---|---:|---:|
| 2019–2022 | 5/6 (83.3%) | 3/3 (100.0%) |
| 2023–2024 | 2/5 (40.0%) | 3/3 (100.0%) |
| 2025–2026 | 2/2 (100.0%) | 3/5 (60.0%) |
| **Total** | **9/13 (69.2%)** | **9/11 (81.8%)** |

The SELL result degrades to **60% on 2025–26**. All folds are
research-exposed, not prospectively untouched.

### The macro-thesis loses longevity

For the same OIS1Y + TIPS10Y + equity veto:
- **D1:** BUY 9/13 = 69.23%; SELL 9/11 = 81.82%.
- **D5:** BUY 6/12 = 50.00%; SELL 5/8 = 62.50%.
- **D10:** BUY 4/8 = 50.00%; SELL 3/8 = 37.50%.

Even the selected apparently strong D1 SELL signal does NOT produce
verified durable 1–2-week SELL accuracy. The next Fed speech,
CPI, PCE, NFP, yields, USD and risk regimes can reverse it.

## Decision

**No model meets >=80% for BOTH BUY and SELL with >=30
independent qualifying events per side.** No model can claim a
Wilson 95% lower bound >=80% or independently verifiable historical
at-time capture. Target NOT MET.

R4 does, however, supply a falsifiable and directionally symmetric
**policy-information contextual WATCH** module:

`research/fed_expectation_r1/policy_information_watch_r4.py`

Inputs must be freshly ingested, event-matched actual intraday
1Y OIS rate, intraday 10Y cash TIPS yield, stock index level, and
USD index proxy (pre/post levels); rejects FRED daily yield as
intraday. If OIS/stocks same sign, classify information-like and
**WAIT**. If policy-like and real yields/USD confirm, return either
**SEARCH_SELL_REBOUND** or **SEARCH_BUY_DIP**, while opposing
FOMC text => WAIT. All outputs say RESEARCH WATCH ONLY and have
**NO ORDER AUTHORITY**, NO stated model confidence and NO deploy.

**Unit tests and source integrity:** 36 passed on the latest R4 CI,
including polarity inversion, missing TIPS, future ingestion, older
event IDs, information veto, and no false LIVE probability.

## Next research (not executed in this PR)

1. **Feed provenance:** seek a licensed real intraday TIPS and
   OIS1Y quote feed; daily FRED TIPS is inadequate for 5–100 minute
   post-FOMC reprice.
2. **Independent news events:** test FOMC minutes, scheduled Fed
   speeches/press conferences, CPI, Core PCE, NFP using true
   publication timestamps and no added lookahead.
3. **Prospective capture:** start capturing actual pre/post source
   snapshots with ingestion clock and immutable hashes on FUTURE
   events; 2019–2026 is not untouched OOS.
4. **Macro revalidation:** reevaluate direction as real yields, USD,
   Fed path and new communication change; do not freeze a D1
   response as an automatic D10 strategy.
5. **Execution:** only after dual-side evidence meets robust
   statistical and after-cost gates should a separate read-only
   ForexScanner research tab be reviewed. Never silently merge
   into Frozen V1 or cTrader order routing.

Official data:
https://www.frbsf.org/research-and-insights/data-and-indicators/us-monetary-policy-event-study-database/
Federal Reserve methodology:
https://www.frbsf.org/research-and-insights/publications/working-papers/2025/12/financial-market-effects-of-fomc-communication-evidence-from-a-new-event-study-database/
Jarocinski and Karadi (2020):
https://www.aeaweb.org/articles?id=10.1257%2Fmac.20180090
