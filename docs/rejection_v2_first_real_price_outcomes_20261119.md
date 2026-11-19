# Rejection V2 — First real-price post-signal falsification (19 Nov 2026)

**Research only; not approval to deploy.** CI run:
https://github.com/rizanrizan93/Forex-scanner/actions/runs/44454468956

## Design / outcome definitions
- Replay the **exact research V2 classifier** against **past closed M1 bars**.
  Retroactively simulated bid/ask: mid close ±$0.25, assumed spread **$0.50/oz**.
  These are reconstructed **entry proxies**, not archived LIVE emitted signals
  or verified FP Markets fills.
- Signal timestamp = M1 close; hypothetical entry = next M1 open. 60-minute
  cooldown per side and category; require complete 60/240-minute future paths.
- Direction H1/H4: signed end-close minus assumed spread is positive.
- Reversal test: +$3 before adverse −$3 within H1; +$5 before adverse −$3
  within H1; +$10 before adverse −$5 within H4.
- If target and adverse are in the same M1 candle, adverse wins (conservative).
- Results NOT pristine OOS; cost constant, no commission/slippage, partial-day
  and volatility regime differences; 240-minute outcomes may overlap under a
  60-minute cooldown; compare only with matching rules.

## Verified input / reproducibility
- CI unit and causality tests: **22 passed**. Synthetics are not win-rate tests.
- Read-only cTrader public M1 feed: 12,000 bars, 2026-11-06 10:33 UTC to
  2026-11-19 03:52 UTC; normalized OHLC SHA-256
  `634df9bae56c5934a8638fc08b98ba75d7ba9fac9e0eaac8ad694b2e5833168e`.
  Evaluated 4,968 M1 closes from 2026-11-12 20:22 through 2026-11-18 11:50 UTC.
- HistData public secondary M1: requested 2023-09-01 through 2023-09-29;
  28,330 rows, no failed periods; pinned provider commit
  `4a3c11b67f97758f6e3f77a3e5905b6aa87367b8`, source in fixed EST
  UTC−5 converted to UTC; CSV SHA-256
  `0127bae35fc66a5ba44eccf1f407fe03c7772a9d3eff2effd4e12cb98714668c`.
  Evaluated 5,856 M1 closes from Sep 7–14 UTC.

## 2026 cTrader real OHLC replay (historical quote PROXY)

| Reconstructed type | BUY n | SELL n | SELL 60m $3-before-$3 | SELL H1 direction | SELL H4 $10-before-$5 |
|---|---:|---:|---:|---:|---:|
| EARLY ENTRY CANDIDATE | 0 | 19 | 15/19 = 78.95% | 10/19 = 52.63% | 9/19 = 47.37% |
| RETEST ENTRY CANDIDATE | 0 | 16 | 9/16 = 56.25% | 10/16 = 62.50% | 5/16 = 31.25% |

Additional EARLY SELL: 60m $5-before-$3 = 10/19 (52.63%);
H4 direction = 12/19 (63.16%).
Wilson 95% for $3-before-$3 SELL = **56.67–91.49%**, below a
statistically conclusive lower bound of 60%. BUY has **n=0**, not a zero
success rate and not evidence of ≥60% dual-side accuracy.
With 240-minute non-overlap cooldown post-hoc diagnostic, EARLY SELL
drops to n=9, 7/9 $3-before-$3 and 4/9 $10-before-$5. This does not
establish generalization; no parameter optimization was made.

Per-day early SELL events: Nov 13: 4/4, Nov 16: 6/9, Nov 17: 2/3,
Nov 18: 3/3 reached $3 before −$3. Only four sampled trading days.

## 2023 HistData historical price replay
- **EARLY_ENTRY_PROXY: BUY n=0, SELL n=0** with intact forward labels.
  There were 6 SELL detections before cooldown/future completeness, none
  admitted to the evaluated event set. This means the strict entry engine
  produced no evaluable trades in the sampled September 2023 span.
- Bare `EARLY_WICK_ONLY` events (NOT valid full entry):
  BUY n=63, only 3/63 (4.76%) made +$3 before −$3 within H1;
  SELL n=61, 3/61 (4.92%). Absolute $3 targets across different
  volatility regimes must NOT be naively pooled.

## Decision
**DO NOT MERGE / DO NOT DEPLOY.** Evidence supports only exploratory
short-horizon SELL bounce capture in a small, selected November 2026 sample.
It does not demonstrate robust 60% directional accuracy on H1/H4, no
evidence for qualifying BUY entries, and not robust across 2023/2026.

Next falsifications: 1) ≥4 distinct market regimes and more historical
samples, 2) cost/slippage stress with true bid/ask when obtainable,
3) holdout-like prospective event capture with immutable signal timestamps,
4) compare early-vs-retest on *matched events* rather than incomparable
groups, 5) report n, Wilson 95% and day-cluster CI separately.

**No Frozen V1, Manual R3, cBot LIVE, bridge, route, risk, or main changes.**
