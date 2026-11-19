# RIZAN Fed Macro R3 — FINAL 2019–2026 Yield/DXY 80% Research Replay

**Run: SUCCESS:** https://github.com/rizanrizan93/Forex-scanner/actions/runs/44637740507

- 16/16 integrity tests passed.
- 69/69 previously sealed R1 Fed event ledgers loaded (2019–2026).
- Models: 8 predefined symmetric macro rules using SF Fed USMPD
  ex-post MP2, UST2Y, UST10Y and DXY reaction, NOT realtime prices.
- H1/H4 omitted from the primary table because of post-FOMC M1
  session-gaps; D1/D3/D5/D10 measured from next completed trading-day
  closes. $0.50/oz synthetic cost; no historical actual carry/spread.
- Horizon censoring and **NEXT FOMC overlap exclusions** applied.
- No threshold was chosen after reviewing winning examples. 64
  model×horizon×side comparisons are exploratory, not independent
  tests or a clean untouched holdout.

## D1 directional accuracy (wins / evaluable events)

| Model | BUY | SELL |
|---|---:|---:|
| MP2 only | 10/15 **66.67%** | 3/8 37.50% |
| MP2 + 2Y | 8/12 66.67% | 3/8 37.50% |
| MP2 + DXY | 9/12 75.00% | 3/8 37.50% |
| MP2 + 2Y + DXY | **8/10 80.00%** | 3/8 37.50% |
| MP2 + 2Y + 10Y + DXY | 6/8 75.00% | 3/7 42.86% |
| 2Y + 10Y + DXY | 13/21 61.90% | **10/15 66.67%** |
| 2Y + DXY | 15/25 60.00% | 12/19 63.16% |
| Strong MP2 + 2Y + DXY | 6/8 75.00% | 3/8 37.50% |

The **8/10 80% BUY** observation has Wilson 95% CI
**49.02%–94.33%**, not lower bound 80%. SELL remained 3/8.
The yield-only consensus includes more bearish events, but
**10/15 66.67% SELL** is also not 80%.

## D5 (approximately five complete trading days) with next-FOMC overlap excluded

| Model | BUY | SELL |
|---|---:|---:|
| MP2 only | 8/13 61.54% | 2/7 28.57% |
| MP2 + 2Y | 7/10 70.00% | 2/7 28.57% |
| MP2 + DXY | 6/10 60.00% | 2/7 28.57% |
| MP2 + 2Y + DXY | 5/8 62.50% | 2/7 28.57% |
| MP2 + 2Y + 10Y + DXY | 3/6 50.00% | 2/6 33.33% |
| 2Y + 10Y + DXY | 6/18 33.33% | 6/12 50.00% |
| 2Y + DXY | 10/22 45.45% | 8/16 50.00% |
| Strong MP2 + 2Y + DXY | 4/6 66.67% | 2/7 28.57% |

## D10: apparent strong BUY in MP2 alone, not generalizable

- MP2-only BUY **9/11 = 81.82%** after excluding
  2 longer-horizon overlaps and censoring 2 missing sessions.
  Wilson95 [52.30%,94.86%]; SELL **2/7=28.57%**.
- MP2 + 2Y + DXY BUY **4/6=66.67%**; SELL
  2/7=28.57%. Strict additional confirmation is NOT
  automatically better over 10 sessions.
- Unfiltered matched event-clock D5 baseline: hypothetical BUY
  30/60=50%, SELL 29/60=48.33%. This is a descriptive baseline
  with more events, not a randomized causal comparison.

## Decision — TARGET NOT MET

**NO R3 model reaches simultaneously observed >=80% BUY and SELL with
>=30 independent evaluable events PER SIDE.** Historical R1/Fed R2
communication results remain insufficient for a verified 80% system.
Seemingly high D1 BUY 8/10 and D10 BUY 9/11 are *small-sample
research observations*, not validated trade win rates.

- Decline to deploy or create cTrader buy/sell orders.
- Retain Fed/R2 as verified official macro fact / WATCH context,
  NOT as an execution signal or an artificially rounded 80% metric.
- Next registered research should test *actual Fed policy-path*
  curve repricing (1y OIS / SOFR futures), **real yield** (TIPS),
  equity/credit *Fed information shock* differentiation, live
  CPI/PCE/NFP surprises and prospective snapshot timestamps.
- Test each horizon separately and do not claim the 2019–26 sample is
  prospective; it has repeatedly been searched.
- True same-event Fed futures, yield, dollar quote capture,
  exact costs and prospective untouched dual-side testing are
  prerequisites before dashboard promotion.

## Reproduction

- `scripts/replay_fed_macro_80pct_r3.py`
- `tests/test_fed_macro_80pct_r3.py`
- `.github/workflows/fed_macro_80pct_r3.yml`
- Official audit/source hashes in prior R1:
  `research/fed_expectation_r1/FED_R1_2019_2026_FULL_REPLAY_ID.md`
- CI artifact: `fed-macro-r3-80pct-research-2019-2026-ablation`.

No changes to `main.py`, Frozen V1, Manual R3, cBot LIVE, bridge,
account or risk.
