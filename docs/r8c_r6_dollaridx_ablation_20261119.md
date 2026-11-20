# R8-C — 19 November 2026, 14:36 WIB: locked R6-event × USD proxy ablation

**Research only, not a strategy promotion.** This cycle adds
`scripts/research_r8c_r6_dollaridx_ablation.py` with independent SHA-pinned
event-ledger verification and explicit per-year/per-side/per-horizon ablation.
It does **not** generate a historical result or claim an accuracy change.

## New research design
The R6 baseline remains frozen. At each completed R6 M5 sweep/MSS event,
use only DOLLARIDXUSD M1 close prices with publication timestamps <= event
timestamp. Calculate 5/15/60-minute causal direction using R8 source audit.
Compare four predeclared groups: every R6 event, DXY-eligible events,
15m+60m USD aligned with XAU direction, and 15m+60m USD opposed.
Do not compare filtered n to all-events n as though coverage were constant.

Outcome: H1 or H4 forward signed price movement, **net** of $0.50/oz
assumed transaction cost, with exact R6 next-M1-open/forward-close
label recipe. Require event ledger SHA and original source-contract identity,
no duplicate event times, UTC-offset-aware timestamps, matching year,
correct horizon and explicit label/cost semantics. Summaries include n,
wins, accuracy, Wilson 95% lower bound, and DXY feature coverage separately
for BUY/SELL for 2019–2026.

## What this does NOT yet establish
- No actual Dukascopy tick/S1 source bytes or independently verified
  reconstructed M1 and source-native quote availability log in this run.
- No R6 per-event ledger with a source-verified manifest was located;
  the previous R6 aggregate report is insufficient for an event-level join.
- No R8-C real historical accuracy (BUY n=unknown; SELL n=unknown).
- 2025–2026 has been repeatedly inspected and is not a pristine holdout.
- The R8-C tests are synthetic, checking only contract failures, not
  market direction. Even if CI is green, no deployment is permitted.

## Further falsification before any accuracy claim
Audit missingness by session/year/side; ensure any source selection bias
does not improve measured hit-rate. Add day-cluster bootstrap and an
alignment-shuffled negative control. Demand a new prospective shadow ledger
with immutable signal timestamps and source-published quote times. The
Dukascopy dollar-index CFD is NOT ICE DXY. Cash Treasury DGS2/DGS10
daily observations are NOT intraday yields.

No change to production, Frozen V1, Manual R3, cBots, bridge or risk.
