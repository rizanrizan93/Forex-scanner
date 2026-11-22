# RIZAN Snowball S6 — XAU-only versus EUR signal research (2026-11-22 WIB)

**Status: no candidate qualified. Research ONLY. Do NOT deploy or alter Frozen V1.**

## Objective and Frozen V1 control

User goal: from USD $100, sequentially reach $125, $250, $1,000 and compound toward $10,000,000,000 while controlling equity drawdown. Original Frozen V1 model 2019–13 Nov 2026: $1,662,133,293.08 and max equity DD 56.67%; **simulated** using historical synthetic M1, not broker-native tick proof, liquidation-capacity proof or expected future growth.

## Executed studies (GitHub Action evidence)

- EUR S5, 3,456 policies x 14 years 2012–2025, 48,384 model-year screening outcomes: no training-qualified policy. Historical retrospective 2023–2025 has known FXCM missing weeks. Run https://github.com/rizanrizan93/Forex-scanner/actions/runs/45024843870 ; audit https://github.com/rizanrizan93/Forex-scanner/actions/runs/45025011535.
- XAU S6, 3,456 policies x 14 years 2012–2025, 48,384 model-year screening outcomes. Sources: pinned public third-party Dukascopy-derived bid and ask M1 at commit `1d8e4c008fe177be455f6de05f5057ebdde901ae`, NOT FP Markets. Annual replay and aggregate SUCCESS: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45026252308.
- XAU vs EUR nominal cash-tier audit SUCCESS: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45026513715.

S6 stages were independent feasibility points at $100, $125, $250, and $1,000; **no sequential balance growth or native wallet transactions** were simulated. Assumptions: gold minimum 1 oz (0.01 standard 100-oz lot), planned risk <=8% at each nominal cash balance, leverage 1:200, margin cap 50%, M5-close signal and next M1 open, bid/ask price paths and hypothetical per-ounce slippage/fees. Actual broker minimum volume and precise contract specification not certified. Cost-2x S6 approximates extra charges on the same stop/TP OHLC sequence; it is NOT a full path-recomputed broker-stress result.

## All-stage results

| Cash-tier assumption | XAU training-qualified policies | EUR training-qualified policies |
| --- | ---: | ---: |
| $100 | **0/3456** | 0/3456 (EUR initial $100 only) |
| $125 | **0/3456** | not separately evaluated |
| $250 | **0/3456** | not separately evaluated |
| $1,000 | **0/3456** | not separately evaluated |

XAU 2012–18 training: 3,424/3,456 configs have >=90 feasible entries even at $100. None achieved positive mean net R after stress costs. Therefore signals and nominal minimum-lot eligibility exist; the bottleneck is *economic expectancy*, not raw signal count.

Top training config by base mean among >=90 entries (diagnostic only; rejected): DOUBLE_SWEEP SELL, lookback12, H4-with, US WIB session, hold120, SL1.5 ATR M5, TP2.5R, $100 stage. Training 2012–18 n184, base +0.03976R/entry but stress **−0.09767R/entry** and PF_base only 1.067. Validation 2019–22 n149, base −0.16493R, stress −0.25646R, PF_base 0.757. This demonstrates the danger of promoting single-year high P&L.

## S7 novel cross-market follow-up

Instead of adding EUR trades, S7 investigates EURUSD only as a causal DXY-direction proxy while XAUUSD is the traded instrument; one can observe EUR M5 closing before XAU next-minute entry. It combines bid/ask XAU with 15/60-minute EUR movement alignment/opposition, H4 directional bias and XAU past-volatility regime. 3,840 policies per year, trained 2012–18, validated 2019–22, retrospected 2023–25. Pilot: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45026732777. Full: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45026823361.

S7 is also cross-vendor, not native Frozen V1, 2023–25 EUR data has missing weeks; M1 stop-first, synthetic costs, source out-of-sample constraints apply. A positive S7 policy would only justify a *matched native replay*, not an assumption of improved $10B terminal wealth.

**No changes** to Frozen V1 files, user LIVE cBots, bridge, margin, broker, or production dashboard.
