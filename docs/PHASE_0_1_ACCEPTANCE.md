# Phase 0 + Phase 1 acceptance contract

## Phase 0

Mandatory:

- [x] 15-pair universe defined once in config
- [x] UTC canonical timestamp contract
- [x] signal states enumerated
- [x] hard guards enumerated
- [x] risk limits stored as configuration
- [x] OOS/real-money gate stored as configuration
- [x] no live order code path
- [x] missing data must be UNKNOWN/blocked, never synthetic neutral evidence

## Phase 1

Mandatory before moving to Phase 2:

- [x] read-only collector abstraction
- [x] MT5 adapter fails closed
- [x] deterministic mock feed
- [x] bid/ask validation
- [x] UTC aggregation M1/M5/M15/H1/H4/D1
- [x] spread avg/max per bar
- [x] duplicate/non-monotonic/stale checks
- [x] DST-aware session classifier
- [x] Parquet storage adapter
- [x] DuckDB query adapter
- [x] Supabase schema prepared but isolated from stock DB
- [ ] live TMGM MT5 smoke test completed on Windows host
- [ ] 24h continuous collector soak test
- [ ] no missing M1 bars outside expected market closure
- [ ] spread distribution captured per pair/session
- [ ] dedicated FX Supabase project created and schema verified

## Stop conditions

Do not start real trading logic if any of these are unresolved:

- broker feed cannot be collected reliably
- timestamps are not UTC-consistent
- duplicate/gap rate is material
- Bid/Ask are unavailable
- spread cannot be measured
- storage is lossy
- data quality is silently defaulted
