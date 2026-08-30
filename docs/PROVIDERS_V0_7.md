# Provider data contract v0.7

## Goal

v0.7 introduces a typed, auditable boundary between external public data and
the v0.6 decision engine. External data cannot silently become a successful
neutral observation.

## Status semantics

| Status | Decision use | Meaning |
|---|---|---|
| AVAILABLE | yes | fresh complete observation |
| PARTIAL | yes, with coverage | usable but incomplete evidence |
| MISSING | no | no observation was supplied |
| STALE | no | observation exists but exceeded max age |
| INVALID | no | contract/conflict violation |
| ERROR | no | network/HTTP/parse/provider failure |
| NOT_APPLICABLE | no | evidence does not apply |

A numeric value of `0.0` remains a valid value. It is never interchangeable
with `MISSING`.

## Provenance and freshness

Every source observation records:

- provider name
- exact HTTPS source URL
- series identifier
- whether the source is official
- observation timestamp
- fetch timestamp
- age and maximum permitted age

Stale values remain available to audit output, but are not marked usable.

## Network contract

The core HTTP transport:

- requires HTTPS
- validates the exact configured host
- forbids URL credentials
- blocks redirects
- limits response body size
- uses bounded request timeout
- accepts only canonical official endpoints from validated config

The single-series numeric adapters reject wildcard or multi-series queries.

## Official adapters

### ECB Data Portal

Endpoint:

`https://data-api.ecb.europa.eu/service/data`

Uses the official SDMX REST service with CSV output and the last two
observations. Daily, monthly, quarterly and annual period labels are normalized
to UTC period-end timestamps where needed.

### Bank of Canada Valet

Endpoint:

`https://www.bankofcanada.ca/valet/observations`

Uses JSON observations. No API key is required by the public Valet service.

Canonical smoke series:

- `ECB_EURUSD_REFERENCE` -> `EXR/D.USD.EUR.SP00.A`
- `BOC_POLICY_RATE` -> `V39079`

Smoke freshness is configured per series, not inferred from a generic provider
default.

## Semantic cache

Provider caching differentiates:

- fresh positive result
- negative/error result
- stale result

Negative and stale TTLs are intentionally shorter than positive TTLs so a
temporary outage or stale observation cannot poison the research state for a
long period.

## Quorum

The numeric orchestrator:

1. fetches/caches each provider binding,
2. excludes non-usable evidence,
3. computes coverage,
4. requires configured minimum successful sources,
5. rejects excessive numeric disagreement,
6. returns the median only after the conflict guard passes.

If quorum fails because data are stale/error/invalid, that cause is preserved
rather than flattened to `MISSING`.

## Macro pipeline

A macro factor binding contains:

- provider
- exact series
- explicit normalizer
- max age

Normalizers may use a current/previous delta or a level relative to an explicit
reference. Domain-specific scale and polarity must be configured explicitly.

If history required by a normalizer is absent, the factor remains missing. A
high-level currency macro score is still governed by the canonical v0.6 factor
weights and minimum macro coverage.

## News guard

The typed economic-event model records currency, scheduled UTC time, impact,
official/source provenance, and optional actual/forecast/previous values.

`evaluate_news_block` blocks relevant high-impact events within a configurable
pre/post window. Post-news spread and volatility normalization remain separate
hard guards (`SPREAD_BLOCK`, `VOLATILITY_BLOCK`).

A full economic-calendar ingestion provider is still pending.

## Persistence

`SupabaseResearchStore` writes non-latency-critical macro snapshots to the
existing `currency_macro_state` table:

- individual factor scores
- final macro score
- factor coverage
- maximum source age
- source statuses
- provider/series/source URL provenance

No v0.7 database migration is required. Supabase remains outside the
quote/order critical path.

## Not yet claimed

v0.7 does **not** yet claim complete live macro coverage for all eight
currencies. Remaining provider expansion includes Fed, BoE, BoJ, SNB, RBA,
RBNZ, inflation/growth/labour releases, yields/cross-asset evidence, COT, and a
reliable multi-country economic calendar.

Execution remains `DISABLED`.
