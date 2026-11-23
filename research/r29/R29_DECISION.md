# R29 accuracy audit and promotion decision

Date: 23 November 2026 WIB
Workflow: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45128421504
Branch: research/r29-direction-accuracy-20261123

## Decision

Reject R29 as a production replacement. This batch did not establish a consistent accuracy improvement. All four research jobs and the report job completed successfully. 416 candidate model fits, plus archived R28 baseline fits, were evaluated. Five protocol tests passed.

The 2026 evaluation uses archived candles through 13 November 2026 (weekly source open 9 November). It excludes current broker observations and is not a prospective test. Historical archives have been examined by earlier research. Configuration selection excludes each test year, but that does not make the source an untouched holdout.

| TF | R28 accuracy | R29 accuracy | R28 coverage | R29 coverage | R29 predictions |
|---|---:|---:|---:|---:|---:|
| H1 | 50.13% | 50.05% | 100.00% | 100.00% | 4,923 |
| H4 | 50.20% | 47.29% | 82.18% | 78.41% | 977 |
| D1 | 43.75% | 48.37% | 78.92% | 68.61% | 153 |
| W1 | 47.22% | 53.13% | 80.00% | 71.11% | 32 |

Accuracy is conditional on predictions issued; coverage and side samples differ. The table does not prove a paired improvement at identical trades. D1 remains below 50%; W1 is based on only 32 predictions, including five SELL predictions. All 2026 R29 combined Wilson lower bounds are below 50%. H4 SELL support collapses to 12 predictions. No 80% accuracy claim is supported.

## Dashboard lineage audit

The current reconstructed R28.1 feed uses price models for H1/H4, price_fx for D1, and fx for W1. It is not the ensemble of the highest historical side records in direction_benchmark_lock_r281_20261122.json. Those records reference R25/R11/R18/R27/R24 and have different sample windows and conflict rules. Their headline accuracies cannot be combined or assigned to the current model. The archived high-water marks themselves also do not establish 80% independent accuracy.

## Next evidence needed

More OHLC combinations have not established a robust edge. Prioritize verified intraday USD/FX and yield inputs, consistent broker candle/session definitions, and timestamped prospective evaluation of unchanged predictions. Declare acquisition completeness and source availability before evaluating; retain missing-data states. Do not retune on this batch's 2026 outcomes and present a second evaluation as pristine holdout.

Production dashboard, R28 inference policy, Frozen V1 and order execution remain unchanged by R29.
