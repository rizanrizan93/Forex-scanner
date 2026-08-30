# Dual-broker deployment contract v0.5

## Roles

`FP Markets cTrader` is read-only market/research evidence.
`HFM Cent MT5` is the only venue permitted to submit orders.

The scanner must never copy an FP price directly into an HFM order without
execution-side reconciliation.

## Revalidation order

1. Resolve canonical pair to HFM Cent broker symbol.
2. Read fresh FP Bid/Ask.
3. Read fresh HFM Bid/Ask.
4. Check quote freshness and crossing.
5. Check cross-broker divergence.
6. Check HFM spread / spread divergence.
7. Check HFM executable price remains inside SL/TP geometry.
8. Check do-not-chase entry drift.
9. Recompute RR.
10. Verify USC / Cent contract.
11. Recompute volume from HFM equity and tick economics.
12. Enforce internal revalidation latency ceiling.
13. Run live environment/control/idempotency gates.
14. MT5 takes a fresh quote and repeats final price geometry/drift check.
15. Run `order_check`.
16. Recheck mutable kill/control state.
17. Submit once.
18. Persist accepted or indeterminate outcome.

## Fail closed

The following conditions block a new order:

- stale research or execution quote
- crossed/invalid quote
- excessive broker divergence
- excessive HFM spread
- chase/entry drift
- invalid SL/TP geometry
- RR below threshold
- non-USC account
- non-Cent FX contract
- symbol ambiguity
- volume below broker minimum
- broker preflight rejection
- stale/missing Supabase control cache
- emergency stop / new-orders disabled / mode mismatch
- missing persistent idempotency state
- duplicate or unresolved uncertain signal

## Mobile

Android applications are monitoring/manual-control surfaces only. Automated
execution remains on the controlled VPS with the MT5 terminal and scanner
runtime running continuously.
