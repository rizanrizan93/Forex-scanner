# RIZAN 10B — research R1 results

Status: COMPLETE_R1. Goal USD 10 billion reached: False.

Initial cash USD100, no additional deposits. Continuous shared wallet, model leverage 1:200. Historical cutoff 13 November 2026 03:00 UTC / 10:00 WIB.

| Variant | M1 path | Cost factor | Ending balance USD | Max floating equity DD | Baskets | Errors |
|---|---|---:|---:|---:|---:|---:|
| Frozen V1 baseline | A | 1 | 1,392,645,692.94 | 57.8904% | 1,040 | 0 |
| Frozen V1 baseline | B | 1 | 1,662,133,293.08 | 56.6721% | 1,047 | 0 |
| R1_FOCUS_EURBTC_TO1000_BTC_BUY18_H72 | B | 1 | 1,838,731,373.84 | 58.9085% | 1,040 | 0 |
| R1_ALL_ASSETS_RSI80_BTC_H1_COMPRESSION | B | 1 | 1,836,312,496.68 | 59.4940% | 1,071 | 0 |
| R1_ORIGINAL_STRATEGY_BTC_CAP128_W600 | B | 1 | 1,703,125,878.22 | 56.6721% | 1,047 | 0 |
| R1_FOCUS_EURBTC_TO1000 | B | 1 | 1,684,641,828.27 | 56.5307% | 1,028 | 0 |
| R1_FOCUS_EURBTC_TO1000_BTC_BUY18_H160 | B | 1 | 1,715,242,916.06 | 56.7976% | 1,029 | 0 |
| R1_FOCUS_EURBTC_BTC18H72_RSI80 | B | 1 | 1,867,121,354.86 | 60.3869% | 1,031 | 0 |
| R1_FOCUS_EURBTC_BTC18H72_RSI80 | A | 1 | 1,424,481,378.11 | 60.8530% | 1,025 | 0 |
| R1_FOCUS_EURBTC_BTC18H72_RSI80 | A | 2 | 987,077,128.52 | 61.9551% | 1,022 | 0 |
| R1_FOCUS_EURBTC_BTC18H72_RSI80 | B | 2 | 998,185,952.84 | 60.9321% | 1,024 | 0 |
| R1_ALL_ASSETS_BTC18H72_RSI80 | B | 1 | 1,833,581,787.55 | 60.4599% | 1,049 | 0 |

## Scope and interpretation

Highest completed cost-1 path-B candidate: USD 1,867,121,354.86, 12.333% above the baseline in the same path/cost. This is a provisional scenario result, not a claim of dominance across paths or costs.

Module screens: 25,344 configurations including the goal parameter, 405,504 annual module simulations. These are not full portfolio replays. Completed annual C# cases: 215, including repeated controls. Completed continuous C# cases: 10.

The synthetic M1 C# model inherits API stubs, synthetic reliable heartbeat/ACK handling, and synthetic XAU admission snapshots from the recovered original research. It does not execute the uploaded .algo binary in cTrader or certify broker tick execution, historical macro vintages, market impact or large-capacity live fills. No LIVE strategy, service, checkpoint or order was changed.

Cost factor 2 stresses modeled fees, slippage and funding; the reported spread multiplier remains 1. It is not a guarantee that all real-world costs have been captured. No continuous baseline cost-2 control was replayed in this round, so these stresses quantify candidate sensitivity rather than proving a candidate advantage over the baseline under stressed costs. MaxEquityDDPct is peak-to-trough equity drawdown, including open positions; it is not closed-balance drawdown.

The standalone screen column dd_upper is a module screening statistic. It is not a mathematical bound on the C# portfolio drawdown because entry timing and subsequent position sequences can differ. Candidates were rejected when the portfolio validation contradicted the screen.

Although the baseline was also started in 2012, its order ledger was identical to the 2019 start and contained no pre-2019 trades. Therefore the nominal 2012–2026 run does not validate trading in 2012–2018. R1 variants here were replayed continuously from 2019 only.

The experiment is exploratory. The historical periods were already used in prior research; there is no pristine holdout or live profitability certification.

The separate V5 branch retains a USD2,091,130,955.10 fixed-ledger exploratory lock. Its lock file says native_approved=false and floating_dd_pct=null, and requires a new full market replay. It is not included as a replay-validated R1 result; see CROSS_BRANCH_REFERENCE.json.

The early target is recorded only when both balance and equity reach USD1,000. Baseline path B reaches it on 2 April 2019 05:19:25 UTC. The RSI80/BUY18R/72h candidate reaches it on 3 April 2019 20:22:10 UTC, about 1.63 days later. Higher terminal balance therefore has not proved a faster early phase.

Seed 5R/8h and its alternatives improved some reset cases but failed others. For example, the 2019 path-B cost-2 seed5R/8h portfolio ended at USD49.9995 with 60.9388% floating DD. This contradicted favorable standalone seed screens. A flat-only EUR/BTC add-on did not improve the portfolio consistently. The H1 BTC compression add-on did not improve the selected annual reset pilot consistently; that pilot alone cannot establish its continuous-wallet effect. A separate continuous add-on case is reported in the results table. No variant has been promoted to LIVE.

The capacity variant changes only BTC maximum batch order count 32→128 and batch window 180→600 seconds. The batch planned risk fraction remains 2.5%, batch margin fraction remains 10%, shared planned risk cap remains 20.75%, shared entry margin cap remains 50%, leverage and per-order broker model limits remain unchanged. Those entry controls are not hard bounds on observed floating risk/margin ratios after equity changes.

The highest completed path-B cost-1 case below 60% floating DD ends at USD 1,838,731,373.84, DD 58.9085%, gain 10.625% versus the same-path baseline. This case has not received an A/2x continuous validation in this round.

Source hashes and exact input restoration hashes are retained in CURRENT_SOURCE_AUDIT.json and the baseline restoration records. All scenario definitions are retained as JSON files. Full local order/equity artifacts remain under results/; compact summaries and source are committed to the research branch.

## Paired BTC H1 add-on replay

All-assets control USD1,833,581,787.55; added-entry case USD1,836,312,496.68; change 0.1489%. Floating DD changes 60.4599% to 59.4940%. Executed H1 compression baskets 25, descriptive family net PnL USD730,852.56. Total basket count 1049 to 1071.

This pair uses EarlyMask=7 on both sides; it is not the EarlyMask=5 highest-balance candidate. Changes in subsequent admissions and sizes are included by the shared-wallet replay. Added-family net PnL is not a standalone counterfactual profit.
