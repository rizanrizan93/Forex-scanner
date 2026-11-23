# RIZAN R13 — EURUSD early capital replication

23 November 2026 WIB. Research only. Frozen V1 / LIVE unchanged.

Run: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45104089377
Pinned experiment commit: `60e12fd01d06faf2de0f0d2975ec961480e2922d`.
Complete aggregate and annual execution ledgers retained as Actions artifacts. Final aggregate artifact: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45104089377/artifacts/14786198392

## Completed result

64 R12-related EUR policies, two families (opening-range retest; M15 EMA20 pullback followed by later M5 structure recovery), two local sessions and two completed higher-timeframe gates. BUY/SELL separate; two targets and two holding periods. 14 annual years2012–2025, four repriced execution scenarios: 3,584 scenario-configuration-years, not independent discoveries. No verified2026 FXCM input; none fabricated.

- Development **0/64**; validation/evaluation **0/64** under hierarchical gates.
- Positive pooled stress expectancy **0/64**, requiring bothA2/B2.
- Past-only selector admits zero policies. Its hypothetical cash remains **$100** because it makes no trades; this is not profitable compounding or the Frozen V1 balance.
- No policy/scenario reaches$250 or$1000 from annual starting$100. Some reach$125 and subsequently lose it.
- **No verified change to Frozen V1 terminal balance**, no accepted add-on and no$10B achievement.

## Annual stress A2 diagnostics, descriptive only

| Year | Policies hitting settled125 | Policies hitting250 | Highest ending cash among64, hindsight only |
|---|---:|---:|---:|
| 2012 | 2 | 0 | $135.76 |
| 2013 | 1 | 0 | $124.98 |
| 2014 | 0 | 0 | $101.95 |
| 2015 | 19 | 0 | $137.65 |
| 2016 | 2 | 0 | $132.68 |
| 2017 | 0 | 0 | $80.65 |
| 2018 | 5 | 0 | $114.37 |
| 2019 | 5 | 0 | $103.25 |
| 2020 | 3 | 0 | $95.91 |
| 2021 | 0 | 0 | $75.77 |
| 2022 | 4 | 0 | $89.59 |
| 2023 | 5 | 0 | $132.54 |
| 2024 | 0 | 0 | $72.64 |
| 2025 | 0 | 0 | $105.53 |

These are different per-year hindsight winners; never stitch their results into a portfolio. Minimum1000EUR/step1000EUR, leverage200 and margin50% are research assumptions. Wallet risk is8% below125 settledcash and3% thereafter, with fee/slippage admission reserves. The standalone wallet does not implement the entire Frozen V1 phase/Guard47 system; only settled drawdown is measured. Actual FP Markets specs, funding, capacity and floating drawdown are not certified.

Quotes multiplied by1000 before replay give correct USD-per1000EUR dimensions: hypothetical commission0.06USD/block roundtrip and0.05USD/block adverse slippage each side. Cost2 reprices quotes, barriers and admission, not just profit haircut. The inherited3USD/block/day gap reserve is conservative, not actual swap. OHLC A/B paths are not real ticks. Tested and rejected under these assumptions, not a claim that every possible broker implementation loses.

## Native recovery, new progress

Recovered exact original control Seed/Mode/GrowthRisk from the immutable14November archive, plus **two unique original summary references** (four records with duplicates):2020B1 ending2863.7152708454446USD /144baskets;2026B1 ending110.98666812619737USD /36baskets. These are archived observations, NOT new reruns. The archive contains no original gzip trade/equity ledgers. Evidence: `research/RIZAN_R13_NATIVE_CONTROL_REFERENCE.json`.

Derived annual control requests, explicitly labelled as requests rather than results: `research/RIZAN_R13_NATIVE_CONTROL_PROFILES_DERIVED.json`.

New `scripts/r13_native_control_compare.py` checks control profile, terminal cash, DD, PF, baskets/orders, missing/duplicate cases and error/open-position counts. Its tests pass. Even a matching summary returns native_ledger_parity=false; no accidental promotion from aggregate equality.

Previous exact three-asset CSV restoration and108 reconstructed tape files remain available in the research workspace. Exact inputs/tapes are not yet staged on a GitHub Actions runner; original tape checksum references and original order/settlement/equity ledgers are still missing. Thus no actual native shared-wallet rerun is claimed in R13. Macro vintage remains uncertified.

## Validation and decision

GitHub pilot and all14 annual jobs and aggregate completed successfully. Original replay causality/barrier/cost/gap tests, R12 stage sizing tests and R13 EUR-unit/fee/spread/PnL/label tests pass. Four inherited R12 targeted tests pass locally. Synthetic fixtures prove software behavior only, never profit.

Reject these R12/R13 session policies for promotion. Do not retune their thresholds after these outcomes. The cross-instrument replication did not solve the early-capital or terminal-growth objective. Prioritize exact native control replay and its trade/equity evidence before a new balance improvement claim. All historical samples reused; no pristine out-of-sample or significance claim.
