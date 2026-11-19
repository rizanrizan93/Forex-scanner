# RIZAN Fed Expectation → XAUUSD: real market replay 2019–2026

**Research status: 8-year real-price replay completed; NOT a validated
realtime backtest. Production gate LOCKED.**

CI: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44621561755

## Original sources and audit

- Official Federal Reserve Bank of San Francisco U.S. Monetary Policy
  Event-Study Database (USMPD), XLSX SHA-256
  `2b91297c42cf692dd74f65eabf7ee97f81d452676e23fa02edb222bfa60f0d0a`.
- Official reference: https://www.frbsf.org/research-and-insights/data-and-indicators/us-monetary-policy-event-study-database/
- `MP2` = surprise implied expected policy rate at *next FOMC meeting*,
  in percentage-point change. It is not the entire 1-year forward path.
  `UST2Y` = US 2y yield change in percentage points;
  `DXY` = DXY percentage return for the completed event window.
- 69 statement FOMC records: 2019=9, 2020=13 (includes emergency
  communications), 2021–2025 each=8, 2026=7 up to available release
  source. 69/69 corresponding real-XAU HistData M1 source windows loaded
  successfully, **0 period-download failures**. Every event has its
  own normalized UTC source SHA in the year-sharded JSON artifacts.
- XAUUSD secondary-market HistData M1 downloaded with pinned downloader
  Git SHA `4a3c11b67f97758f6e3f77a3e5905b6aa87367b8`;
  source timestamps FIXED EST−5 converted to UTC, no synthetic price
  bars filled. Model $0.50/oz fixed spread, broker commissions/overnight
  carry/slippage **not verified**.
- Source cutoff **2026-11-20**. Incomplete future D10 and missing
  holidays/weekdays are censored. H4 requires 240 uninterrupted minutes,
  so most post-FOMC H4 outcomes are legitimately censored.
- Canonical event uses the full monetary window where both a statement
  and press conference are unambiguously matched by local ET date.
  Otherwise uses the completed press conference if present, else the
  statement itself. No synthetic 2020 emergency press conferences.
  Multiple events on a calendar day avoid ambiguous joins.
- Thresholds frozen before observing this experiment:
  `MP2_ONLY` ≥+2bps SELL, ≤-2bps BUY;
  `THREE_MARKET_CONSENSUS` also requires UST2Y ≥+1bp
  and DXY ≥+0.05% for SELL or both ≤negative thresholds for BUY.
  Other observations are WAIT. Event windows were determined from
  official USMPD ET timestamps with DST, not estimated calendar-day times.
- D1, D3, D5 (≈one trading week), D10 (≈two trading weeks) are
  subsequent *complete UTC weekday trading-session* terminal labels.
  Accuracy = signed terminal price return after the modeled cost,
  not whether an arbitrary $3 scalp TP was touched.

## Core findings — eight years combined

### MP2-only next-Fed-meeting repricing

| Horizon | BUY correct / evaluable | SELL correct / evaluable |
|---|---:|---:|
| H4 | 0/2 | n=0; most censored |
| D1 | **10/15 (66.67%)** | **3/8 (37.50%)** |
| D3 | 8/14 (57.14%) | 2/7 (28.57%) |
| D5 | **8/14 (57.14%)** | **2/7 (28.57%)** |
| D10 | 10/13 (76.92%) | 2/7 (28.57%) |

D5 MP2 BUY Wilson 95% CI [32.59%,78.62%]; SELL
[8.22%,64.11%]. Overlap with the *next* FOMC excluded D5 BUY:
8/13 (61.54%, CI [35.52%,82.29%]); still unproven.

### MP2 + cash UST2Y + DXY unanimous

| Horizon | BUY correct / evaluable | SELL correct / evaluable |
|---|---:|---:|
| H4 | 0/2 | n=0; most censored |
| D1 | **8/10 (80.00%)** | **3/8 (37.50%)** |
| D3 | 4/9 (44.44%) | 2/7 (28.57%) |
| D5 | **5/9 (55.56%)** | **2/7 (28.57%)** |
| D10 | 5/8 (62.50%) | 2/7 (28.57%) |

D1 filtered BUY Wilson 95% CI [49.02%,94.33%]; D5 BUY
[26.66%,81.12%]. The impressive D1 percent is only 8/10 and
its lower confidence bound remains **well below 60%**.
The filter **does not improve SELL D5** in this sample; the rate
stays just 2/7. D5 BUY fraction is lower than MP2 alone.

### Unconditional matched FOMC entry clocks, no macro side filter

| Horizon | Hypothetical always BUY | Hypothetical always SELL |
|---|---:|---:|
| D1 | 30/64 (46.88%) | 31/64 (48.44%) |
| D5 | 30/60 (50.00%) | 29/60 (48.33%) |
| D10 | 27/51 (52.94%) | 24/51 (47.06%) |

These descriptive unconditional cohorts have **different n** from
the selected shocks and are not a causal randomized experiment.

## Annual D5 ablation, MP2-only (wins / evaluable n)

| Year | Official events with price | BUY | SELL |
|---|---:|---:|---:|
| 2019 | 9 | 1/1 | 0/2 |
| 2020 | 13 | 1/3 | n=0 |
| 2021 | 8 | n=0 | n=0 |
| 2022 | 8 | 2/4 (1 censored) | 1/1 |
| 2023 | 8 | 1/2 | n=0 (1 censored) |
| 2024 | 8 | 1/2 | 0/1 |
| 2025 | 8 | 1/1 | 0/2 |
| 2026 | 7 | 1/1 | 1/1 (1 censored) |
| **TOTAL** | **69** | **8/14** | **2/7** |

For 2019–2024 alone, D5 MP2 BUY 6/12 (50%),
SELL 1/4 (25%); triple-market D5 BUY 4/8 (50%),
SELL 1/4 (25%). No statistical proof of ≥60% on either
side even if recent 2025–26 are excluded.

## Research integrity and non-production decision

- Full study is **ex-post / oracle only**. USMPD final market-window
  changes were compiled retrospectively. No verified historical
  at-time availability of policy futures, cash US2Y or DXY data;
  GENUINE PIT macro BUY n=0, SELL n=0.
- **ALL 69 XAU sources** downloaded; this does not mean all horizon
  labels were evaluable. D5 baseline 60/69 evaluable, D10 baseline
  51/69, H4 baseline just 7/69. Never treat censored as losses/wins.
- The next-FOMC overlap check removes potentially contaminated
  longer holds; window definitions and daily/weekly labels cannot
  establish a causal Fed-only effect, because intervening CPI/NFP,
  real yields, geopolitics, positioning and other shocks matter.
- 2019–2026 has been researched repeatedly. **2025–2026 is not a
  pristine holdout**; neither are prior 2023 experiments.
- The 69-event universe is FOMC statements/emergency announcements.
  It is NOT a replay of every CPI, PCE, NFP, FOMC minutes or speech
  during 2019–2026.
- **≥60% BUY AND SELL** across daily/weekly horizons is **NOT MET**
  (particularly bearish signals); Wilson lower bounds not ≥60%;
  event count per direction is far below meaningful forward validity.
- PR #889 and parent PR #887 remain **DRAFT**, no merge into
  production, no Frozen V1/Manual R3/cBot LIVE/bridge/orders/risk changes.

## Reproduction and artifacts

- Script: `scripts/replay_fed_macro_2019_2026_r1.py`
- Aggregate: `scripts/aggregate_fed_macro_2019_2026_r1.py`
- Tests: `tests/test_fed_macro_2019_2026_replay_r1.py`
- CI workflow: `.github/workflows/fed_macro_2019_2026_r1.yml`
- Job summary and eight per-year JSON artifacts:
  https://github.com/rizanrizan93/Forex-scanner/actions/runs/44621561755

## Follow-up hypothesis (unvalidated; register before new test)

1. Replace near-term-only `MP2` with a *term-structure path*
   expected-Fed-rate surprise using ED/SOFR/OIS 1y (but confirm
   contract roll and availability); examine **hawkish policy
   surprise vs hawkish growth-information shock** regimes.
2. Record true timestamped as-of futures, nominal/real yields,
   dollar index, and XAU as new events occur; evaluate future
   H4/D1/D3/D5/D10 against frozen baselines.
3. Test separate CPI/PCE/NFP/communications surprises and
   independent event-time news; multiple checks require
   multiplicity control, not a posteriori 'best' threshold.
4. Keep clear division: macro directional state/re-evaluation
   vs Rejection Engine V4 M1/M5 execution timing.
