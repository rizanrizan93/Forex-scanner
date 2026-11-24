# RIZAN V8 — actual native replay evidence
As of 2026-11-24T22:55:02.223054+07:00. Research in progress; target USD10 billion remains unchanged.

Completed full continuous native replays: 9. Unique B1 challengers: 6. New module screens: 0. New annual-reset simulations: 0.

| Candidate | Initial USD | Ending USD | Floating DD | PF | Baskets | Requests | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| V7_CONTROL | 100 | 1,662,133,293.08 | 56.672093% | 2.1768 | 1047 | 187560 | CONTROL |
| V7_LOCK_BTC18_ALL_CAP | 100 | 1,889,793,789.50 | 58.753694% | 2.1201 | 1058 | 214866 | B1 improvement; robustness pending |
| V7_LOCK_BTC18_ALL | 100 | 1,839,227,158.78 | 58.753694% | 2.2000 | 1058 | 212816 | B1 improvement; robustness pending |
| V7_CAP_ONLY | 100 | 1,703,125,878.22 | 56.672093% | 2.1004 | 1047 | 190060 | B1 improvement; robustness pending |
| V7_LOCK_CAP | 100 | 1,701,362,259.95 | 56.694507% | 2.1004 | 1047 | 189752 | B1 improvement; robustness pending |
| V7_LOCK | 100 | 1,662,089,374.91 | 56.694507% | 2.1780 | 1047 | 187323 | REJECT: no balance improvement |
| V7_BTC_T30_H96 | 100 | 1,469,716,521.55 | 58.805905% | 2.0718 | 1051 | 165232 | REJECT: no balance improvement |

Highest completed B1 ending balance: USD1,889,793,789.50, floating DD 58.753694%.
Change against same-path/same-cost baseline: 13.696886%.
Best ending balance below 60% floating DD: V7_LOCK_BTC18_ALL_CAP, USD1,889,793,789.50.
Target reached in B1: False. Four-scenario validation is separate and is not inferred from B1.

Previous B1 native benchmark below60% is retained: USD1,838,731,373.84, floating DD58.908457%. It is not counted as a newly completed V8 replay. The prior highest balance USD1,867,121,354.86 failed DD60.386930%.

| Candidate | Closed DD | Minimum equity USD | Max margin | Max open risk | Worst losing basket streak |
|---|---:|---:|---:|---:|---:|
| V7_CONTROL | 52.772301% | 98.88 | 54.073858% | 27.209882% | 8 |
| V7_LOCK_BTC18_ALL_CAP | 52.765743% | 98.88 | 54.212345% | 27.273177% | 8 |
| V7_LOCK_BTC18_ALL | 52.765743% | 98.88 | 54.212345% | 27.273177% | 8 |
| V7_CAP_ONLY | 52.772301% | 98.88 | 54.073858% | 27.209882% | 8 |
| V7_LOCK_CAP | 52.784495% | 98.88 | 54.078697% | 27.177480% | 8 |
| V7_LOCK | 52.784495% | 98.88 | 54.078697% | 27.177480% | 8 |
| V7_BTC_T30_H96 | 54.450413% | 98.88 | 54.094862% | 27.218648% | 8 |

| Candidate | XAU net PnL USD | EUR net PnL USD | BTC net PnL USD |
|---|---:|---:|---:|
| V7_CONTROL | 1,615,224,606.39 | 12,454,083.19 | 34,454,503.51 |
| V7_LOCK_BTC18_ALL_CAP | 1,780,779,576.96 | 13,411,021.55 | 95,603,090.99 |
| V7_LOCK_BTC18_ALL | 1,784,606,423.21 | 13,452,806.16 | 41,167,829.41 |
| V7_CAP_ONLY | 1,619,752,464.88 | 12,465,736.12 | 70,907,577.22 |
| V7_LOCK_CAP | 1,618,144,132.11 | 12,431,044.99 | 70,786,982.85 |
| V7_LOCK | 1,615,297,128.70 | 12,419,750.51 | 34,372,395.70 |
| V7_BTC_T30_H96 | 1,356,501,495.43 | 11,774,139.12 | 101,440,787.00 |

Contributions describe the executed shared wallet, not additive standalone alpha.

| Candidate | Peak equity USD | Max-DD recovery days | Longest underwater days | Max simultaneous positions | Minimum margin level |
|---|---:|---:|---:|---:|---:|
| V7_CONTROL | 1,753,097,706.16 | 199.029398 | 265.113194 | 1832 | 184.932247% |
| V7_LOCK | 1,753,053,787.99 | 199.029398 | 265.113194 | 1832 | 184.915699% |
| V7_BTC_T30_H96 | 1,563,413,560.72 | 189.742593 | 265.113681 | 1921 | 184.860440% |

Milestones require both balance and floating equity to reach the level. Times below are WIB.

| Candidate | Milestone USD | First reached WIB | Floating DD before milestone |
|---|---:|---|---:|
| V7_CONTROL | 125 | 2019-01-03T11:30:00+07:00 | 8.233115% |
| V7_CONTROL | 250 | 2019-02-28T18:15:00+07:00 | 23.011901% |
| V7_CONTROL | 500 | 2019-03-07T22:30:00+07:00 | 23.011901% |
| V7_CONTROL | 1,000 | 2019-04-02T12:19:25+07:00 | 23.546730% |
| V7_CONTROL | 10,000 | 2020-03-16T17:06:30+07:00 | 53.221381% |
| V7_CONTROL | 100,000 | 2021-01-09T02:59:00+07:00 | 56.188806% |
| V7_CONTROL | 1,000,000 | 2022-07-13T02:59:00+07:00 | 56.188806% |
| V7_CONTROL | 10,000,000 | 2023-12-11T22:28:13+07:00 | 56.672093% |
| V7_CONTROL | 100,000,000 | 2024-11-26T02:59:00+07:00 | 56.672093% |
| V7_CONTROL | 1,000,000,000 | 2026-03-27T02:59:00+07:00 | 56.672093% |
| V7_LOCK | 125 | 2019-01-03T11:30:00+07:00 | 8.233115% |
| V7_LOCK | 250 | 2019-02-28T18:15:00+07:00 | 23.011901% |
| V7_LOCK | 500 | 2019-03-07T22:30:00+07:00 | 23.011901% |
| V7_LOCK | 1,000 | 2019-04-02T12:19:25+07:00 | 23.011901% |
| V7_LOCK | 10,000 | 2020-03-16T17:06:30+07:00 | 51.904297% |
| V7_LOCK | 100,000 | 2021-01-09T02:59:00+07:00 | 56.122440% |
| V7_LOCK | 1,000,000 | 2022-07-19T02:00:00+07:00 | 56.122440% |
| V7_LOCK | 10,000,000 | 2023-12-11T22:28:13+07:00 | 56.694507% |
| V7_LOCK | 100,000,000 | 2024-11-26T02:59:00+07:00 | 56.694507% |
| V7_LOCK | 1,000,000,000 | 2026-03-27T02:59:00+07:00 | 56.694507% |
| V7_BTC_T30_H96 | 125 | 2019-01-03T11:30:00+07:00 | 8.233115% |
| V7_BTC_T30_H96 | 250 | 2019-02-28T18:15:00+07:00 | 23.011901% |
| V7_BTC_T30_H96 | 500 | 2019-03-20T20:00:00+07:00 | 23.011901% |
| V7_BTC_T30_H96 | 1,000 | 2019-04-06T04:30:00+07:00 | 37.280649% |
| V7_BTC_T30_H96 | 10,000 | 2020-03-16T17:06:30+07:00 | 51.776535% |
| V7_BTC_T30_H96 | 100,000 | 2021-02-17T02:59:00+07:00 | 58.805905% |
| V7_BTC_T30_H96 | 1,000,000 | 2022-12-23T21:45:00+07:00 | 58.805905% |
| V7_BTC_T30_H96 | 10,000,000 | 2024-04-03T02:59:00+07:00 | 58.805905% |
| V7_BTC_T30_H96 | 100,000,000 | 2025-01-16T02:59:00+07:00 | 58.805905% |
| V7_BTC_T30_H96 | 1,000,000,000 | 2026-05-29T22:07:15+07:00 | 58.805905% |

P0 actual comparison: USD-43,918.17 /-0.002642% against control; all1047 core entry keys retained, 618 common baskets have changed integer units and 736 changed PnL. Native-minus-fixed-ledger reference: USD-429,041,580.18. The cash gate rejects this upgrade. No V5 estimate is promoted as native.

Interrupted startup attempts: 4; these are not completed financial replays. One direct process received SIGKILL (OS cause unconfirmed); three indexed batch starts ran out of managed memory before market replay. A resource-only gateway now preserves the exact parity-verified DLL bytes, serializes input loading and limits gated native children to2 with3GiB heaps and a4GiB pre-load available-memory reserve. Retry status must be read from logs, not inferred from queue configuration.

Provisional B1 research lock: V8_B1_1889793789_RESEARCH_LOCK_20261124; cash USD1,889,793,789.50, floating DD58.753694%. Prior-best gain USD51,062,415.66, DD change -0.154763points. A1/A2/B2 validation and one-parameter EarlyRiskMask paired ablation are incomplete; only completed receipts are financial results. No LIVE approval.

Complete private input/runtime and full native receipts are available as workspace ZIPs. Durable Library save failed because account storage quota is full. Google Drive upload was rejected by automatic approval review because that external destination has not been authorized for private archives. No private CSV or archive was uploaded to GitHub.

Baseline parity, exact dataset hashes and original commit verification are retained. Receipts include full order/basket ledgers, equity curve and accounting. Total contributions include the original USD100; additional deposits are zero. Each accepted receipt has no open positions, BTC fault/pending state, quarantines or accounting errors. Cash residual tolerance is USD0.05.

Floating DD is the full synthetic native equity peak-to-trough metric, not closed-balance DD or scaled ledger sensitivity. Milestone and recovery data are available in instrumented receipts; absent diagnostic fields are unknown, not zero. Minimum equity and observed risk/margin are included in CSV/JSON.

The inherited model uses original C# strategy sources with synthetic M1 price paths and API stubs. It is not execution of the original .algo on broker ticks. Synthetic admission macro snapshots and heartbeats are not certified historical vintages. Cost factor 2 changes modeled fees, slippage and funding; spread multiplier stays 1. Broker stop-out and nonlinear market impact are not implemented. Results do not certify broker capacity or LIVE profitability.

2012–2018 trading remains unvalidated because inherited entry/seed gates exclude earlier activity. Full A1/B1/A2/B2, explicit spread/slippage/delay stress, walk-forward, Monte Carlo, start-date and capacity validation remain pending until actual receipts exist. No production, main, VPS or cTrader instance changes.

Code and evidence branch: research/v8-native-10b-accelerated-growth. This execution uses Work, not GitHub Actions; no new Actions run is claimed.
