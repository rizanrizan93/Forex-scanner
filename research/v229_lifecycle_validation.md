# V229 lifecycle correction and validation contract

An untouched H4 parent is required to create a depth plan. After the first touch,
the existing plan must remain usable for M5-confirmed slots L3/L4 while its frozen
H4 zone is valid. Re-running the fresh-candidate selector is not a continuation
test: it can switch to another untouched zone after the original zone is touched.

## Corrected behavior

- Creation accepts H1/M15 nested locators. H4-only historical hotspots remain
  visible in V226 but do not receive V229 execution authority.
- Parent geometry and the selected H1 precision source are persisted in the
  existing geometry event payload. No database schema change is required.
- Continuation uses the persisted H4 identity and geometry, a fresh healthy atlas,
  the signal state/expiry, and the executable quote relative to the frozen stop.
- First touch closes the window for previously unsent L1/L2. It does not cancel
  existing pending children or prevent L3/L4 confirmation.
- Missing zones in the bounded atlas selection mean unknown evidence, not proven
  invalidation. Submission waits. Expiry and explicit invalidation still cancel.
- Known parent invalidation cancels its pending children and retires the signal.
  Existing positions are not closed by this worker.
- L3/L4 confirmation must refer to the captured H1 source, use the same source
  availability timestamp, and come from a sweep after parent capture. All required
  confirmation timestamps must occur between that sweep and atlas evaluation.
- Invalidated or untimed M5 sources do not activate reserved slots. Old payloads
  without frozen geometry/source metadata wait rather than inventing lineage.
- Limits remain four children at 0.01 lot each, with the existing H4 stop and
  structural target rules. The code continues to require a DEMO environment.

## Required forward comparison

Tag episodes by code version, H4 parent ID, source layer, and child slot. Keep
H4-only watch, H1 nested, and M15 nested cohorts separate. A child order is not an
independent candidate: summarize both child-level outcomes and combined parent
outcomes. Report realized net profit, costs, win rate, PF, drawdown, capture rate,
and counts of blocked/expired/invalidated/unknown-data episodes.

Compare L1/L2, L3/L4, and the complete 2+2 setup using exactly the broker's fill,
pending cancellation, protection, target, and close evidence. A two-entry V231
shadow replay does not validate the four-child V229 contract. Do not transfer its
historical PF or win rate to this change.

For subsequent price-driver research, freeze zone/trend/volatility/session and
available news context before the decision. Record actual release values only
after their observed availability. Separate pre-release and post-release rules.
Broker depth is venue-specific context, not consolidated global order flow.
Evaluate added features against the same candidate population and on new data;
descriptive correlations are not proof of economic causality.

## Validation scope

The regression suite exercises continuation after touch, source invalidation,
source identity, episode timing, missing/stale context, target geometry ownership,
parent cancellation, and the actual executor loop with simulated broker objects.
It does not send broker orders or establish profitability.
