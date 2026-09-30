# XAU entry and TP cycle experiment

Status: research only. Execution authority and influence are both false.
D1 work is paused. This change does not adjust dashboard or broker orders.

## Objective and frozen hypotheses

Measure the complete sequence: opportunity → executable entry → quick reaction
→ TP before SL → newly published opposite setup → its entry and reaction/TP.
There is no guaranteed reversal, fill or TP. A $5 adverse excursion means five
XAUUSD price dollars, not five broker points. It is an evaluation threshold,
not a replacement for the structural stop.

Compare the frozen E1/T1 baseline against 48 hypotheses: entry at 25/50/75%
of the frozen pocket, target T1/T2, target buffer $0/$0.50, and passive limit
versus completed M1 reclaim. LONG depth increases downward, SHORT upward.
Targets derive only from slots 1/2 known at publication. Buffered LONG targets
are lower, SHORT targets higher. Every admitted order retains at least 1.5R
after entry costs. Missing geometry remains a missed opportunity in the denominator.

Reclaim means a quote-side touch followed by a close back across the proposed
entry. Execute only at the next contiguous M1 open, within $1 of that entry.
An invalidated, expired or distant setup is cancelled rather than chased.
The fixed thresholds are preregistered hypotheses, not calibrated settings.

A precise fast success requires TP before SL, adverse excursion at most $5,
and at least $1 favourable movement within 15 minutes. Both baseline and
candidates use a four-hour research hold, so compare them within this report;
this is not directly comparable to the V284 thirty-day hold results.

After TP, evaluate the first NEW opposite publication within 30 minutes and
$5 of the TP execution price. Do not select according to its later success,
retry a later winner, or create a reversal signal from TP alone. Previously
published setups are excluded because their prior fill/invalidation state is
not tracked. Cross-year plan catalog gaps are censored. Second-leg entry has
the same rules and its own stop and target; it is not an automatic reversal.

## Replay and validation

M1 timestamps denote bar opens. Close-based decisions/outcomes are available
only at bar completion. Buys fill on ask, sells on bid; exits use the opposite
quote. Limits are filled at their limit (no assumed price improvement).
Market reclaim, stops and time exits include slippage; opening stop gaps take
the worse price. A fill candle cannot earn TP/reaction credit, and SL wins
ambiguous bars. Full candle adverse excursion is conservative and can include
movement before fill or after TP. Fixed spreads and candle touch cannot prove
real broker execution, liquidity or latency.

The pilot covers 2024–2026, with chronological selection using only prior-year
mature outcomes. Selection maximizes the 95% Wilson lower bound of fast precise
TP per opportunity, subject to fill >= baseline minus 5 percentage points,
TP/opportunity >= baseline, and positive stressed expectancy. No candidate
passing means no promotion. Aggregate descriptive scores are not OOS evidence.

Underlying V242 plans use current historical parameters and a retrospectively
selected parent-touch universe. Even the chronological pilot is not independent
prospective validation. Results are per opportunity, not an executable portfolio
return: plans may overlap. Before any promotion, validate on a forward demo
stream with publication/quote/fill timestamps, dynamic spreads, latency, and
all opportunities including unfilled/invalidated plans. Expansion to more years
must precede parameter tuning on this pilot.

Run tests:

```sh
PYTHONPATH=src python -m unittest discover -s tests -p test_research_xau_entry_cycle.py -v
```

Run the pinned-provider yearly replay through the new GitHub Actions pilot,
or locally with the project's dependencies and pinned histdata-fetcher installed:

```sh
python -m fx_scanner.research_xau_entry_cycle_runtime --year 2024 --output artifacts/xau-entry-cycle-2024.json
python -m fx_scanner.research_xau_entry_cycle_runtime --shards artifacts --output artifacts/xau-entry-cycle-full.json
```

Reports preserve source checksums, coverage/failures and price end dates.
Provider failed periods fail the run rather than silently improving fill statistics.
