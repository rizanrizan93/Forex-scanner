# RIZAN R12 — early capital and terminal growth results

23 November 2026 WIB. Research only. Frozen V1 / main / LIVE unchanged.

## Result

GitHub Actions run: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45102692253
Pinned experiment commit: `8f1bbd6c6e773778c1bdcd8585f610cafe40d8e8`.

64 related configurations, two structural families (opening-range retest and completed M15 EMA20 pullback with later M5 structure recovery), two local sessions, BUY/SELL, two direction gates, two targets and two holding periods. 15 annual inputs (2012–2025 plus partial Jan–Aug 2026), four execution scenarios; 960 configuration-years / 3,840 scenario-configuration-years. This is not 3,840 independent strategies.

- Development qualified: **0/64**. Validation/evaluation qualified: **0/64** (hierarchical gates).
- Positive pooled stress expectancy: **0/64**.
- Past-only expanding selector found no eligible policy. Standalone diagnostic cash therefore stayed **$100** across A1/B1/A2/B2; **zero selected trades**, not a profitable replay.
- No annual policy/scenario reached $250 or $1,000 from $100. Some reached $125 but failed cross-year eligibility. None accepted as a replacement bootstrap or add-on.
- No new Frozen V1 terminal balance, incremental basket PnL, floating DD or $10B achievement established.

## Annual stress diagnostic (A2), no hindsight selection

These reset wallets use hypothetical 1oz minimum/step, leverage200, margin50%, risk8% below125 and3% thereafter. They are NOT the Frozen portfolio and are not broker-certified.

| Annual reset year | Policies reaching settled $125 | Policies reaching $250 | Highest ending cash among64, hindsight only |
|---|---:|---:|---:|
| 2019 | 1 | 0 | $127.60 |
| 2020 | 1 | 0 | $127.90 |
| 2021 | 8 | 0 | $141.45 |
| 2022 | 0 | 0 | $116.56 |
| 2023 | 5 | 0 | $137.22 |
| 2024 | 4 | 0 | $136.93 |
| 2025 | 5 | 0 | $131.94 |
| 2026 partial | 0 | 0 | $107.31 |

The highest annual numbers above come from different policies selected after observing outcomes. Do not stitch them into compounding, infer a tradeable policy, or present them as a terminal portfolio improvement. A2 is one intrabar path; full B2 and base-cost metrics are retained in the JSON and Actions artifact.

## Native recovery progress

Three original corrected CSVs were restored from four original archives and matched **all three original SHA256 values**. See `research/r12_stage_growth/NATIVE_INPUT_RECOVERY.json`.

The recovered original signal generator produced **108 binary signal tapes / 1,822,308 candidate records** (EUR624,915; XAU599,792; BTC597,601). These are signal candidates, NOT executed baskets. See `research/RIZAN_R12_NATIVE_TAPE_RECOVERY_20261123.json` and reproducible `scripts/r12_prepare_native_tapes.py`. The generator algorithm file is unchanged; only its paths/bootstrap are adapted in memory, after hash checks. No original tape hashes are available for equality certification.

## Validation and remaining work

Original R11 quote-path/cost/gap tests plus R12 prefix-causality, delayed retest, minimum lot/margin and stage sizing passed locally and in the GitHub pilot. Four additional targeted tests passed locally: BUY/SELL symmetry, London DST/incomplete opening range, future-M1 feature isolation, and risk/margin rounding. Synthetic fixtures only validate code, never alpha.

Next material gate: stage exact inputs/tapes for a native GitHub runner; recover original baseline profile and reference order/settlement/equity ledger, certify tape equality where reference exists, then reproduce the $1,662,133,293.08 historical model control before adding baskets. Macro vintage and real FP Markets capacity/specs remain uncertified. The recovered CSVs/tapes are not themselves portfolio parity.

R12 families fail their economic screen. Do not retune their thresholds based on these outcomes or promote annual winners. Keep their rejection as evidence; prioritize native-control reproduction before any new balance claim. Updated user objective includes both early capital graduation and terminal model cash without increasing original portfolio risk or leverage.
