# RIZAN Fed R6 — FINAL 2019–2026 Causal Swing + H1 Adverse-First Replay

**Status:** Historical research completed, **NO production qualification**.

**Verified GitHub Actions:** https://github.com/rizanrizan93/Forex-scanner/actions/runs/44653729303
- **31/31 R6 no-lookahead pivot, risk, meeting-unit/source tests PASS**
- All eight annual real XAUUSD M1 replay jobs SUCCESS (2019 through 2026)
- All 69/69 actual official FOMC event windows and price sources covered
- Zero failed source events, aggregate job SUCCESS
- Macro source: official San Francisco Fed USMPD, pinned original
  SHA256 `2b91297c42cf692dd74f65eabf7ee97f81d452676e23fa02edb222bfa60f0d0a`
- Historical XAU M1: secondary-market HistData with source SHA and
  fixed converter per event, not FP Markets actual bid/ask
- Full FOMC initial context expires at +150min from real statement
  release; after whole conference window ends the eligible window is
  often <=60 minutes. Long 2020-03-15 emergency event counted as
  WAIT/zero entries (not missing market data).
- Price spread/cost **synthetic $0.50/oz**. No broker slippage,
  commissions, financing or validated historical realtime macro feed.

## 1. SMC/ICT-style confirmed swing A/B

Original V4 checks the nearest candle high/low in last 36 M5 candles.
R6 replaces ONLY the opposing room reference with:
- Strict **2 completed M5 bars LEFT + 2 completed M5 bars RIGHT**
  confirmation; excludes ties and nonconsecutive M5 sequences.
- Lookback 96 past completed M5 bars.
- BUY: nearest confirmed swing high above hypothetical ask; SELL:
  nearest confirmed swing low below hypothetical bid.
- Required room >= **0.80 M5 ATR** unchanged.
- All other V4 requirements including HTF, candle trigger,
  spread, anti-chase, failed rejection and frozen invalidation
  remain in force. No trade authority.

Results across all 69 FOMC meetings:

| Prior V4 stage | BUY | SELL | Total |
|---|---:|---:|---:|
| Complete trigger-stage pattern (before other vetoes) | 12 | 14 | **26** |
| Pattern with ALL unrelated V4 gates already satisfied | 3 | 1 | **4** |
| R6 confirmed-swing hypothetical candidate | 1 | 0 | **1** |
| Previously blocked SOLELY by old swing room, now recovered | 1 | 0 | **1** |

**Conclusion:** Confirmed structural swings can change eligibility
in a real historical example, but cannot rescue V4 at meaningful
frequency. The other V4 safety/technical gates are the main bottleneck
in this specific post-FOMC window. Do NOT remove gates wholesale
or claim this single BUY qualifies a trading strategy.

## 2. H1 directional accuracy versus adverse path

Each row is the FIRST M1 continuation observation after the completed
official FOMC communication window per FOMC meeting, rule and
direction (not repeated correlated M1 signals). H1 = following 60
complete M1 candles. A target-before-adverse result requires
favorable excursion **>= $3.50/oz gross** (net +$3 after assumed
$0.50 cost) strictly before **$3/oz adverse** excursion.
If target and adverse are both touched within the same M1, count
ADVERSE FIRST. Future M1 gaps are censored. Initial structural
invalidation uses pre-signal 3 M1 extremes +/-0.1 M5 ATR.

| EX-POST macro selection | Side | H1 direction correct | Target3 before adverse3 | Early structural stop before target |
|---|---|---:|---:|---:|
| MP2+TIPS10+DXY | BUY | 7/9 **77.78%** | 4/9 **44.44%** | 4/9 |
| MP2+TIPS10+DXY | SELL | 5/7 **71.43%** | 3/7 **42.86%** | 2/7 |
| OIS1Y+TIPS10+SP500 POLICY_LIKE | BUY | 6/11 **54.55%** | 6/11 **54.55%** | 3/11 |
| OIS1Y+TIPS10+SP500 POLICY_LIKE | SELL | **9/11 81.82%** | 6/11 **54.55%** | 2/11 |
| OIS1Y+TIPS10+DXY | BUY | 9/14 **64.29%** | 7/14 **50.00%** | 5/14 |
| OIS1Y+TIPS10+DXY | SELL | 10/13 **76.92%** | 7/13 **53.85%** | 3/13 |

95% Wilson intervals for target-before-adverse (distinct per side):
- MP2/TIPS/DXY: BUY **18.88–73.33%**; SELL **15.82–74.95%**.
- OIS/TIPS/equity: BUY and SELL both **28.01–78.73%**.
- OIS/TIPS/DXY: BUY **26.80–73.20%**, SELL **29.14–76.79%**.

The 81.82% direction estimate for SELL under the equity veto model
falls to **54.55% target-first** and is only **n=11**. A rate-direction
forecast can be RIGHT but the initial entry has already breached
a meaningful adverse risk barrier or static structural stop.

### Unfiltered continuation baseline (same FOMC event-clock population)

| Direction | First event H1 terminal correct | First event +$3 before adverse $3 |
|---|---:|---:|
| BUY | 26/55 = **47.27%** | 24/55 = **43.64%** |
| SELL | 25/56 = **44.64%** | 20/56 = **35.71%** |

These are descriptive comparisons, **not causally matched
improvements or prospective alpha**. The macro selected
subsets are smaller and made with completed-window USMPD
retrospective study values, not captured LIVE outcomes.
Never pool models as independent meetings.

### 20 September 2023 real-price example

- Official FOMC full communication window ended 19:30Z,
  initial release at 18:00Z, macro context expires 20:30Z:
  60 eligible M1 close timestamps.
- 28,330 real HistData M1 (September sample SHA
  `0127bae35fc66a5ba44eccf1f407fe03c7772a9d3eff2effd4e12cb98714668c`).
- V4 no entry-qualified candidate.
- 3 correlated raw SELL continuation M1 signals; first unique
  H1 terminal direction was correct **1/1**.
- MFE after synthetic round-trip cost **$7.12/oz**, MAE
  **$1.41/oz**; target net +$3 touched before gross -$3,
  **BUT** static pre-signal structural invalidation touched
  **BEFORE** target.
- This proves a favorable terminal label is not the same as a
  valid/survivable entry, NOT a 100% success event.

## Research verdict

- Neither the earlier R4 macro outlook nor R5/R6 entry
  system has demonstrated **>=80% BUY and SELL
  risk-adjusted entry success** with meaningful independent n.
- Real historical early FOMC V4 triggers are too rare;
  confirmed swing replacement reopens only **one BUY** across
  69 meetings, so it is insufficient.
- Future research should separate:
  1. **Direction** (Fed actual/expected policy, real yields,
     DXY, equity information shock),
  2. **Entry trigger** (pre-timestamped continuation or liquidity
     rejection confirmed *without lookahead*),
  3. **Risk survivability** (MFE/MAE, structural invalidation,
     adverse-before-target, true spread/slippage).
- Needed: time-stamped independent live intraday OIS/SOFR curve,
  TIPS real yield, US2Y/10Y, dollar proxy and broker actual
  quotes, and prospective event capture after rule freeze.
- For multi-day/weekly bias, do NOT extrapolate a +150-minute
  FOMC engine for D5/D10: refresh policy expectations, CPI/PCE,
  labor data and the yield/FX relationship each session.

**PRODUCTION RELEASE GATE LOCKED.** All modules are research-only
and never touch Frozen V1, Manual R3, cTrader cBots LIVE, bridges,
order routing or account settings.

**Source code:** draft PR #894. All numeric results trace back to
the final eight-year GitHub Actions aggregate and its per-year
source-provenance artifacts.
