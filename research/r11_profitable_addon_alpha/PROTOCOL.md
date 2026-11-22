# R11 preregistration — 23 November 2026 WIB

Research branch only: `research/r11-profitable-addon-alpha`, based on S10 commit `cca4d9d78fa5302d4fa8364c8d99c7040edd4ce0`. No production authority. Frozen V1 unchanged.

## Hypotheses

1. Completed displacement produces FVG; wait at least two M5 bars for retest and close recovery.
2. Breakout locks a prior 12/24-bar range extreme; wait at least two bars for retest and confirmation. Do not move breakout level with price.
3. Sweep prior range, then a later MSS displacement, then a still-later origin retest. A sweep alone cannot trigger entry.
4. Prior six-bar compression, displacement with expansion, then delayed retest of locked extreme.

Every hypothesis requires separately aligned completed H1 and H4 EMA20/80 direction. BUY/SELL independent. Expire pending setups after 6/12 M5 bars. Reset on gaps or invalidation. One pending setup per stream. Two targets 1.5/2.5R, holding 60/180 minutes, and admission with/without two-realized-loss 30-day pause. Fixed stop >=1.25 ATR plus structural invalidation. Total **256 configurations, four structural families**, not 256 independent discoveries. No retuning after reading results.

Differences from S5-S8: multi-stage state transitions, locked setup levels, minimum two-bar separation, sweep->later MSS->later retest rather than an immediate MSS/first breakout signal, and fully repriced stress paths. Generic labels overlap prior hypotheses; do not claim entirely untouched families.

## Data and execution

Pinned third-party Dukascopy-derived XAU bid/ask M1 source inherited from S6, commit `1d8e4c008fe177be455f6de05f5057ebdde901ae`. Monthly SHA-256 captured on every runner. Independent price source; NOT Frozen checksum parity. Years 2012-2025; 2026 only Jan-Aug with actual last timestamp disclosed. No EUR or BTC experiment until source quality and positive pilot merit expansion. Raw vendor data cached as reproducible artifacts only if needed; no fabricated replacement for missing files.

Pilot first 60,000 valid minutes of 2021. Full matrix only depends on pilot success. Pilot performance is never a profitability gate: it verifies mechanics/data. Stop failures by year independently (fail-fast=false), retain failed artifacts and logs.

Entry at first M1 open exactly at completed M5 decision time, observed spread <=0.15 ATR. No admission from future continuity checks. A future gap liquidates at first next quote with adverse slippage; it never deletes an entry. Gap cases remain uncertified. One fixed ounce per opportunity, fee $0.06/oz round trip, $0.05/oz adverse slippage each side, measured vendor spreads. Cost2 doubles commission/slippage and widens bid/ask before replaying entry, barrier triggers, settlement, and loss-pause state. Hypothetical specs, not current broker terms. A=O-L-H-C and B=O-H-L-C, independent of side. MFE/MAE use path vertices until exit. Overnight gap reserve $3/oz/day per cost unit; actual broker swap is unknown. Entry before18 UTC and max3h holding avoid scheduled rollover when no gaps.

Only one standalone opportunity active per policy, 5-minute embargo after close. Annual state restarts with indicator warmup; no position crosses data boundary. Full year files keep all per-policy simulated fills and rejection counts. These are neither core/add-on combined fills nor native basket counts.

## Selection fixed before replay

- Development 2012-2018, **both A2/B2**: N>=100, expectancy >0.02R, PF>1.10, >=5 positive years.
- Validation 2019-2022, both stress paths: N>=50, expectancy >0.01R, PF>1.05, >=3 positive years.
- Evaluation 2023-2025, both stress paths: N>=30, expectancy >0R, >=2 positive years.
- 2026 partial is disclosed separately; no promotion from partial year alone.
- Expanding walk-forward selection uses only years before evaluated year; no known-year filters. 3h maximum positions terminate inside annual inputs, 5m embargo per stream. Annual indicator warmup further separates samples.
- All historical years previously researched. No pristine out-of-sample claim. Signal/ledger fingerprints disclose aliases. 256 correlated policies plus old searches do not permit unadjusted statistical significance. New forward shadow and family-wise block-bootstrap evidence required before ACCEPT. Economic screen pass is **INCONCLUSIVE**, never validated alpha.

## Native gate and risk

Read original S9/S10 source and archive, preserve its SHA-256 manifest, build original replay under .NET8 in Actions. Native compile alone is not parity. Original corrected CSV SHA, signal tapes, macro flags, profiles, fees, lot normalization, timestamp/order/basket/settlement/margin/equity ledger must match before any shared-wallet claim. Recovered generator means tapes can potentially be reconstructed, but generated tape hashes and ledger equality are not yet established.

Frozen controls: $100, leverage1:200, planned GROWTH risk<=20.75%, margin<=50%, 2019–2026-11-13 cutoff; historical model $1,662,133,293.08, floating DD56.6721%,1047 baskets. Shared wallet untested until native parity. The 3% add-on/4% risk reserve/10% margin reserve remains an unvalidated S10 hypothesis. No independent normalized-R multiplication into a balance. No changed lots/leverage to reach $10B. Core conflicts, true incremental wins, capacity and floating DD must remain null, not zero, until actually replayed.

No DXY/yield proxy, macro-confirmed entry, winner pyramid, broker spec certification or continuous-wallet capacity conclusion is included in this first price-only matrix. They require missing point-in-time data or core ledger. The main report must make these omissions explicit.
