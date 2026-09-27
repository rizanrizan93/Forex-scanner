# Brent Uni Depth V238B / Broker Discovery V238C — Findings 2012–2026

## Scope

V238B applies the existing XAU V225.2 causal Supply/Demand first-touch depth methodology to Brent historical data without fitting Brent-specific thresholds.

- Historical pair: HistData BCOUSD M1
- History: 2012–2026
- Available years: 15 / 15
- Timeframes: H4 / H1 / M15
- First-touch only
- Reaction definition: favorable move before close beyond distal edge
- Favorable reaction starts strictly after the first-touch M1 bar
- Same-M1 target/break ambiguity: STOP_FIRST
- Truncated horizons: censored, not counted as failure
- Policy: SHADOW_ONLY
- Execution influence: false
- Execution authority: false
- LIVE execution: false

V238C separately reads the actual FP Markets cTrader DEMO symbol catalogue and contract metadata. It creates no order and does not subscribe the discovered Brent candidates to a trading lane.

## Overall Brent results

Total causal first-touch episodes: **64,211**.

| TF | Touches | Reaction >=0.50 ATR | Wilson LB 95% | Median depth | P25 | P75 | IQR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H4 | 4,440 | 69.84% | 68.48% | 16.88% | 5.47% | 40.00% | 34.53 pp |
| H1 | 14,187 | 71.02% | 70.26% | 19.44% | 6.15% | 43.95% | 37.80 pp |
| M15 | 45,584 | 74.71% | 74.30% | 18.18% | 5.17% | 41.18% | 36.00 pp |

The highest conditional depth hazard remains the **00–10%** band on all three timeframes. This is a conditional turning-depth statistic, not a trade win probability.

## Reaction ladder and excursion geometry

| TF | >=0.25 ATR | >=0.50 ATR | >=0.75 ATR | >=1.00 ATR | Median MFE | Median MAE | Median candidate→touch | Median time to 0.50 ATR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H4 | 86.26% | 69.83% | 55.00% | 42.88% | 0.85 ATR | 0.39 ATR | 247 min | 22 min |
| H1 | 84.17% | 71.01% | 59.09% | 49.02% | 0.97 ATR | 0.64 ATR | 75 min | 11 min |
| M15 | 86.00% | 74.70% | 63.30% | 54.26% | 1.14 ATR | 0.72 ATR | 19 min | 2 min |

The 0.50 ATR rung was cross-checked against the original V225.2 evaluator after removing first-touch-bar favorable excursions. The two calculations align to rounding.

## Directional symmetry

| TF | LONG reaction | SHORT reaction | LONG median depth | SHORT median depth |
| --- | ---: | ---: | ---: | ---: |
| H4 | 69.76% | 69.93% | 16.67% | 17.25% |
| H1 | 71.39% | 70.64% | 20.00% | 19.10% |
| M15 | 74.66% | 74.75% | 18.18% | 17.97% |

LONG/SHORT first-touch behavior is sufficiently symmetric that no directional side should receive a structural prior merely from this historical depth study.

## Era stability

| Era | Episodes | H4 reaction | H4 median / IQR | H1 reaction | H1 median / IQR | M15 reaction | M15 median / IQR |
| --- | ---: | ---: | --- | ---: | --- | ---: | --- |
| 2012–2018 | 30,616 | 71.33% | 15.50% / 34.02 pp | 71.25% | 19.23% / 37.98 pp | 74.27% | 16.67% / 40.00 pp |
| 2019–2024 | 25,967 | 68.05% | 18.12% / 35.54 pp | 70.87% | 19.55% / 37.84 pp | 75.08% | 18.75% / 34.93 pp |
| 2025–2026 | 7,628 | 70.39% | 18.35% / 33.66 pp | 70.57% | 20.00% / 37.06 pp | 75.18% | 19.23% / 35.90 pp |

M15 is the most stable Brent layer by reaction rate across the three eras. H4 is less stable and weakened in 2019–2024.

## Brent vs EURUSD vs XAU — same first-touch geometry

EURUSD and XAU reference numbers come from the existing V235/V225.2 comparison.

| TF | Brent reaction | EURUSD reaction | XAU reaction | Brent median depth | EURUSD median | XAU median | Brent IQR | EURUSD IQR | XAU IQR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H4 | 69.84% | 71.95% | 71.37% | 16.88% | 17.07% | 20.03% | 34.53 pp | 33.55 pp | 37.72 pp |
| H1 | 71.02% | 72.25% | 70.96% | 19.44% | 19.51% | 20.88% | 37.80 pp | 36.55 pp | 37.75 pp |
| M15 | 74.71% | 75.15% | 74.29% | 18.18% | 19.51% | 20.37% | 36.00 pp | 36.46 pp | 36.97 pp |

Interpretation:

1. **EURUSD remains the cleanest outer-depth stability benchmark overall.**
2. Brent H4 has narrower depth dispersion than XAU, but a lower >=0.50 ATR reaction rate.
3. Brent M15 has the narrowest IQR of the three in this comparison and a reaction rate between XAU and EURUSD.
4. Brent is therefore a credible commodity satellite for further research, but the evidence does not support calling it uniformly easier or more stable than EURUSD.
5. Reaction geometry alone does not prove positive trading expectancy.

## Nested hierarchy

Brent:
- H4 successful reactions: 3,101
- Pre-existing H1 child coverage: 46.47%
- M15 child coverage given H1 child: 37.68%
- H1 child median depth: 33.33% (P25 13.79%, P75 60.49%)
- M15 child median depth: 44.10% (P25 20.00%, P75 68.62%)

Nested refinement is usable but does not justify reusing Gold thresholds without instrument-specific validation.

## FP Markets cTrader DEMO broker discovery

V238C read **1,002** symbols from the actual FP Markets cTrader DEMO catalogue.

Two strong Brent-related symbols exist:

| Broker symbol | cTrader symbol ID | Broker meaning |
| --- | ---: | --- |
| BRENT | 1072 | Brent Crude Oil vs US Dollar **Future** |
| XBRUSD | 100 | Brent Crude Oil vs US Dollar **Cash** |

FP Markets publicly lists the same distinction:
- XBRUSD = Brent Crude Oil vs US Dollar Cash
- BRENT = Brent Crude Oil vs US Dollar Future

Official product reference:
- https://www.fpmarkets.com/id-id/commodities/
- https://www.fpmarkets.com/id-id/forex-spreads/

The broker discovery resolver intentionally remains **UNRESOLVED** when both strong candidates are present. A symbol name alone must not silently decide whether the scanner is studying cash Brent or a futures CFD.

### Contract metadata observed from cTrader DEMO

Both symbols:
- digits: 3
- pip position: 2
- short selling enabled
- trading mode active
- schedule timezone: America/New_York
- five regular schedule intervals
- same raw min/step/max-volume contract fields in the cTrader protobuf

Differences observed:
- BRENT: swapLong 0.0, swapShort 0.0
- XBRUSD: swapLong 5.35, swapShort -21.84
- XBRUSD carried broker holiday metadata while BRENT did not in this snapshot

These differences are consistent with two distinct product contracts and reinforce the rule not to pool them.

## Instrument mapping for the next research gate

V238B historical data is the non-expiring **BCOUSD Brent-in-USD** series. For a cash-style broker parity test, **XBRUSD is the appropriate first cTrader candidate** because FP Markets explicitly labels it Brent Cash.

BRENT must remain a separate futures-CFD research instrument. It can be tested later, but it must receive:
- its own history/parity validation,
- roll/expiry handling,
- instrument-specific depth calibration,
- its own cost model,
- and separate walk-forward/OOS evidence.

This is a research mapping decision only. It does not grant execution authority to XBRUSD.

## What V238B/V238C do not prove

They do **not** prove:
- positive expectancy after costs,
- profit factor > 1,
- acceptable drawdown,
- profitability of the V229 child ladder on Brent,
- structural-target hit-rate superiority,
- robustness around high-impact energy/geopolitical events,
- equivalence between HistData BCOUSD and FP Markets XBRUSD prices,
- or permission for automated Brent orders.

## Next valid gate

Before any Brent execution lane exists:

1. cTrader XBRUSD historical parity against the BCOUSD research series.
2. Quantify spread/slippage as ATR-normalized costs.
3. Test structural M15/H1/H4 target hit rates.
4. Build an instrument-specific execution simulation using conservative STOP_FIRST ordering.
5. Report expectancy R, profit factor, drawdown and margin feasibility.
6. Segment 2012–2018 / 2019–2024 / 2025–2026.
7. Walk-forward and untouched OOS validation.
8. Keep all results SHADOW_ONLY until those gates pass.

Gold remains the scanner core. EURUSD remains the stability benchmark. XBRUSD becomes the Brent **cash parity candidate**, not an execution-authorized satellite.
