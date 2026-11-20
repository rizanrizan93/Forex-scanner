# R7 — XAUUSD Factor Map with Horizon-specific Learned Weights
**Date:** 2026-11-20. **Status:** read-only methodology and tested software, not demonstrated market forecasting performance.

## Target
Predict next XAU price LOG return over *trading sessions*:
D1=1, W1=5, M1=21, Y1=252. These are **not** exact calendar
1 day/week/month/year; overnight closures and holidays matter.

Given an as-of decision t with real historical factors X_(i,t),
the ridge model estimates:

  E[log(P_(t+h)/P_t)] = alpha_h + sum_i beta_(i,h)*clip((X_(i,t)-mu_(i,train))/sd_(i,train),-4,4)

Train beta by minimising squared future log-return error plus
lambda*sum(beta^2). Both mean and SD are fit on historical training
inputs only; no future samples can enter the model.

The weight display is 100*abs(beta_i)/sum(abs(beta)), for factors
that are standardized by training data. Interpretation: the
RELATIVE MAGNITUDE of fitted ridge coefficients, not causal
economic influence, not prediction accuracy, and not a confidence
or success percentage. Closely correlated DXY/US Treasury signals
can share the same predictive information or destabilize signs.

An independent research ranking drops each factor group, REFITS,
and measures the change in MSE/RMSE on identical out-of-sample
decision timestamps. Drop-group increases RMSE => that group helped
on that period, negative increases => it hurt. Group interactions
and regime-dependent weights may be compared in a subsequent
pre-registered challenger; no assumption they improve OOS skill.

## Horizon-specific factor map
| Horizon | Key drivers exposed for empirical estimation |
|---|---|
| D1 | Real US10Y, US2Y, DXY, Fed surprise, VIX, actual futures flow, liquidity stress, 5d gold momentum, SMC structure score |
| W1 | Real US10Y, US2Y, DXY, Fed path repricing, VIX, COMEX OI, COT net positioning, ETF flow, 21d momentum |
| M1 | Real US10Y, breakevens, DXY, Fed path, VIX, COMEX OI, COT, ETF flow, bank purchases, 21d momentum, global PMI |
| Y1 | Real US10Y, breakevens, DXY, Fed path, ETF, central-bank gold demand, global PMI, GDP revision and 252d momentum |

This is an *admission map*, NOT an empirical factor ranking. Input
columns have consistent units in their names (bps, percent,
tonnes, contracts). Genuine point-in-time as-of availability is
mandatory. A missing feature is NOT imputed from latest vendor
revision; explicitly fit a documented subset only for ablation.
The engine labels subset runs as non-full models.

## Point-in-time requirements
Each session-as-of row must have:
- gold_close and gold_close_received_at (time of access);
- vintage_verified=true, supported by actual source vintage logs;
- for each admitted factor k: k and k_received_at;
- all receipts <= session-as-of decision time; row timestamps
  sorted, unique, timezone-aware UTC-convertible;
- observation date alone is NOT source publication time.
- daily Treasury official / FRED/ALFRED series: only use values
  available as of original publication. ALFRED vintage day date
  cannot safely substitute for exact intraday timestamp.
- COT observation Tuesday -> normally released Friday. COMEX open
  interest released after its trading session; no same-session
  retrospective effect.
- ETF flow / central bank series have their own publication lags.
- Raw futures orderflow must come from a genuine historical
  exchange/broker-compatible source; chart wick is not a
  replacement for executed market order flow.

## Training and testing
Training excludes the last 2*h sessions before each decision.
The last known training outcome must end at least h sessions
before the decision (purge/embargo). Standardization and ridge
fitting only use the admitted training history.

Minimum causal training rows: D1=300, W1=500, M1=900, Y1=2000.
If not met -> WAIT. Effective minimum nonoverlap out-of-sample
calls: 60/40/24/15 respectively. Nonoverlap evaluation step h
prevents counting each strongly overlapping multi-day return as
an independent forecast. A single short 2019-2026 study rarely
provides 15 independent Y1 holdout observations; annual models
need a much longer multi-decade historical archive before
claims of predictive reliability.

Model produces research-only estimated return and price, a
provisional SEARCH side if >0.05% edge, and weight breakdown.
This edge threshold is illustrative and DOES NOT represent
transaction-cost coverage or statistical confidence.
No calibrated win probability is emitted. Separate historic
broker costs, sample sufficiency, systematic nonstationarity,
trade overlap and drawdown must be evaluated.

Ablation and walk-forward software are present, but NO matched
2019-2026 point-in-time daily/weekly/monthly/annual factor
matrix has been supplied to these R7 functions in this turn.
The eight sampled-month R6.5 price-only direction backtest
(51.45% baseline / 51.65% guarded after $0.40/oz assumed
spread) is NOT evidence for R7 learned factor weights.
The only R7 tests so far are synthetic unit/regression checks.

## Technical and policy boundaries
This standalone module does not import cTrader execution APIs,
modify Frozen V1, send orders, set portfolio risk, or claim
out-of-sample verified alpha. It belongs on a draft research PR.
Do not add to production decision logic until data provenance,
walk-forward, post-tuning holdout and forward-shadow audit pass.

## Research foundations
World Gold Council GRAM:
https://www.gold.org/goldhub/tools/gold-return-attribution-model
World Gold Council long-run GLTER:
https://www.gold.org/goldhub/research/golds-long-term-expected-return-glter
FRED ALFRED real-time:
https://fred.stlouisfed.org/docs/api/fred/realtime_period.html
CFTC COT release cadence:
https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
