# RIZAN R15 — completed local native terminal-balance pilots

23 November 2026 WIB. Continuous synthetic M1 model2019–13November2026 03:00UTC /10:00WIB, initial100USD, leverage200, pathB, cost1. No LIVE changes. This is compiled original execution-source replay on simulated cAlgo APIs, not running the uploaded.algo in cTrader or a real broker tick replay.

## Actual newly completed results

| Case | Ending model cash USD | Max floating equity DD | Baskets | Change versus control |
|---|---:|---:|---:|---:|
| Original Frozen V1 model | $1,662,133,293.08 | 56.672093% | 1,047 | $+0.00 |
| GROWTH four losses/symbol →24h pause | $1,663,437,984.65 | 56.543329% | 1,043 | $+1,304,691.56 |
| XAU M15 break16 /H1-aligned /3% add-on | $1,085,989,938.04 | 61.190915% | 1,179 | $-576,143,355.04 |

The guard candidate increases ending model cash by **$1,304,691.56 /0.078495%**, with floating DD **0.128764percentage points lower**. Counts drop1047→1043baskets while child orders change through original dynamic sizing; no manual increase to lot/leverage or risk parameters. Guard applies only after SEED graduation, ignores SEED settlements and leaves open-position management/exits unchanged.

This is a small B1 pilot improvement, not the10billionUSD target, statistical proof, a forward result or production approval. R14's four-loss policy was a retrospective validation-screen survivor; its development-ranked winner(two-loss pause) failed validation. Thus the candidate remains historically selected, not pristine OOS.

The XAU add-on produces **157 additional independently admitted add-on baskets**, but total ending model cash drops by **$576,143,355.04 /34.6629%**, with floating DD **4.518821points higher**. Add-on audit records157requests,1unaffordable minimum-lot rejection,5postfill budget closes and its60%DD halt triggered. It is rejected as a terminal-balance improvement under this pilot.

## Actual entry-stream differences

| Case | Original core(symbol,entry) keys absent | New core keys | Independently filled add-on baskets |
|---|---:|---:|---:|
| Original Frozen V1 model | 0 | 0 | 0 |
| GROWTH four losses/symbol →24h pause | 5 | 1 | 0 |
| XAU M15 break16 /H1-aligned /3% add-on | 32 | 7 | 157 |

These counts are entry-key differences, not a standalone causal attribution of every missing fill to margin. The changed admission/sizing can alter affordability and later availability. The add-on fails the no-displacement requirement: original core entry keys are missing and no proof of preserved core participation is offered. No missing trades are silently erased. Guard omissions are its intentional entry-filter experiment, not an add-on pretending to preserve all original trades.

## Reproduction and software checks

- Original unmodified research source/hash manifest compiled into a self-contained.NET8Linux replay through GitHub Actions, then run locally on exact restored3asset CSVs and108 reconstructed seed-tape files. Original source and uploadedBUY050.algo left untouched.
- Original2020B1 control exactly reproduces2863.7152708454446USD /144baskets;2026B1control110.98666812619737USD /36baskets. Summary comparison also matches DD,PF,orders/errors/open-position fields.
- Original continuous replay independently reproduces **1662133293.0811067USD, DD56.67209330213908%,1047baskets,187560orders**, matching archived rounded cash/DD/basket benchmark. The old complete1047basket reference ledger is unavailable; do not call this cryptographic equality to a missing old ledger.
- Guard-off research copy matches original2020 basket/order/cash/equity streams exactly.
- An isolated history-index adapter was added to address repeated whole-history scans. Index results preserve exact append order and pass exact-label,basket,symbol,family and missing-key unit comparisons. Guard tests cover per-symbol scope,24h expiry and future-settlement rejection. Indexed2020/2026 controls match original order,basket,cash,equity streams exactly.
- **Indexed continuous baseline versus the newly run original continuous engine also matches all four streams exactly across the full period**: Ledger,OrderLedger,CashLedger,EquityCurve. It makes no change to the strategy or simulated fills. See full_indexed_baseline_equality.json in evidence.
- All completed economic pilots exit0 and report no errors/open positions at fixed cutoff. Duplicate slow guard/add-on runs were stopped after replacing them with validated indexed runs; their incomplete logs are not presented as final results.

## Risk/capacity limitations that block deployment

| Case | Peak observed open risk | Peak observed margin | Within20.75% /50%observed caps? |
|---|---:|---:|---|
| Original Frozen V1 model | 27.209882% | 54.073858% | False |
| GROWTH four losses/symbol →24h pause | 27.217443% | 54.093674% | False |
| XAU M15 break16 /H1-aligned /3% add-on | 24.331311% | 50.632667% | False |

The original model and candidates exceed planned observed risk/margin bounds in simulation. Keeping original sizing parameters does not establish hard equity-relative exposure compliance. **No candidate is approved for LIVE**. This is a model observation, not an audit of the user's actual live account. A/B path comparison,2×cost native replay, annual resets, new forward evidence and risk/margin enforcement must pass before promotion. Actual FPMarkets minimum/step/margin tiers, liquidity/price impact and large-balance execution capacity remain uncertified.

Exact CSV hashes match the restored archive, but original XAU macro flags/vintage and synthetic external snapshots are uncertified. MacroModeoff uses an empty loader(no fabricated macro observations added). Synthetic intraminute paths, reliable research heartbeats and simulated ACKs are inherited from the original model. Not actual tick history or real bridge execution. The uploaded file's metadata identifiesBUY0504.0.1; binary equality to Bootstrap125 or these archives is not established.

## Evidence and reproducibility

Branch: `research/r15-local-native-terminal` inrizanrizan93/Forex-scanner.

- `research/RIZAN_R15_NATIVE_TERMINAL_RESULTS_20261123.json`: exact outcomes,risk observations,hashes,audits and stream checks.
- `research/r15_local_native/`: preregistration, isolated build preparation, paired-run drivers, comparator and summary scripts.
- `research/r15_local_native/evidence/RIZAN_R15_NATIVE_BASELINE_20261123.zip`: original completed baseline, controls and detailed native ledgers.
- `research/r15_local_native/evidence/RIZAN_R15_NATIVE_GUARD_20261123.zip`: completed guard pilot and index/control equality evidence.
- `research/r15_local_native/evidence/RIZAN_R15_NATIVE_ADDON_20261123.zip`: completed rejected add-on and full comparison.

The exact source/CSV/tape provenance is inR11–R13 recovery manifests. Historical samples were all reused; no confidence interval or significance is inferred from selecting this pilot. Guard improvement is a candidate to test further, not a realizable wealth forecast. The10billion target remains unachieved.
