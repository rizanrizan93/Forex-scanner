# RIZAN V8 — actual native replay evidence
As of 2026-11-24T21:13:08.477134+07:00. Research in progress; target USD10 billion remains unchanged.

Completed full continuous native replays: 1. Unique B1 challengers: 0. New module screens: 0. New annual-reset simulations: 0.

| Candidate | Initial USD | Ending USD | Floating DD | PF | Baskets | Requests | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| V7_CONTROL | 100 | 1,662,133,293.08 | 56.672093% | 2.1768 | 1047 | 187560 | CONTROL |

Baseline parity, exact dataset hashes and original commit verification are retained. Receipts include full order/basket ledgers, equity curve and accounting. Total contributions include the original USD100; additional deposits are zero. Each accepted receipt has no open positions, BTC fault/pending state, quarantines or accounting errors. Cash residual tolerance is USD0.05.

Floating DD is the full synthetic native equity peak-to-trough metric, not closed-balance DD or scaled ledger sensitivity. Milestone and recovery data are available in instrumented receipts; absent diagnostic fields are unknown, not zero. Minimum equity and observed risk/margin are included in CSV/JSON.

The inherited model uses original C# strategy sources with synthetic M1 price paths and API stubs. It is not execution of the original .algo on broker ticks. Synthetic admission macro snapshots and heartbeats are not certified historical vintages. Cost factor 2 changes modeled fees, slippage and funding; spread multiplier stays 1. Broker stop-out and nonlinear market impact are not implemented. Results do not certify broker capacity or LIVE profitability.

2012–2018 trading remains unvalidated because inherited entry/seed gates exclude earlier activity. Full A1/B1/A2/B2, explicit spread/slippage/delay stress, walk-forward, Monte Carlo, start-date and capacity validation remain pending until actual receipts exist. No production, main, VPS or cTrader instance changes.

Code and evidence branch: research/v8-native-10b-accelerated-growth. This execution uses Work, not GitHub Actions; no new Actions run is claimed.
