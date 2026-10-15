# RIZAN Pre-News Expectation Engine V1

The XAUUSD **Pre-News** tab reads the existing sanitized Turso dashboard snapshot and refreshes every 60 seconds. It displays the next supported USD event, simultaneous release components, countdown in WIB, consensus-change expectation (COOL / INLINE / HOT-RISK / MIXED), conditional XAU bias, evidence agreement, scenario matrix, original scanner news-gate status and source freshness.

This is a read-only information engine. It does not change cBot signals, order submission, sizing, SL/TP, bridge configuration or the existing news gate. No probability, return improvement or replay validation is claimed.

## Interpretation

- Consensus versus previous describes expected change, not actual versus consensus surprise. Actual values are never consumed by this engine.
- Headline/core CPI and employment/wages/unemployment at the same release time are evaluated together. Conflicting components yield MIXED. Higher unemployment reverses the ordinary hawkish interpretation.
- DXY intraday is separated from daily FRED US2Y, US10Y and real yield. Broad USD proxy is not substituted for DXY.
- Contradictory macro pressure yields NEUTRAL_MIXED. Evidence agreement is capped at MEDIUM and is not a win probability.
- FOMC remains DATA INCOMPLETE because target-rate consensus alone omits statement, projections and press-conference information.

## Freshness and missing data

Both healthy worker heartbeats must be at most 600 seconds old. DXY observation must be at most 1,800 seconds old; daily FRED source timestamps must be at most seven calendar days old and still have producer freshness FRESH. The seven-day ceiling permits weekends/holidays and is a regime check, not an intraday claim. Missing, future or naive timestamps, nonfinite/bool numeric values and missing consensus/previous suppress bias and expectation. Compact macro projections now retain source observation timestamps so republication cannot refresh old observations.

The engine selects the nearest future supported event in the supplied calendar, not a hardcoded event date. No supported future event means DATA INCOMPLETE, not proof that the market has no upcoming news. Source calendar coverage, consensus vintages, event deduplication and revisions inherit upstream limitations; point-in-time training and forecast-surprise probabilities are not yet available. Full causal replay/OOS calibration remains separate future work.

## Verification

58 targeted tests passed covering hot/cool/inline, all supported numeric event families, inverse unemployment, missing consensus, simultaneous component conflict, stale/future/naive/unhealthy workers, stale underlying observations, FOMC abstention, compact/full payload parity, duplicate heartbeat ordering, no input mutation, no execution authority, the Streamlit tab, existing dashboard routing and Turso/macro bridge contracts.

A public snapshot inspected during implementation contained calendar/macro worker timestamps from 2026-10-10. That snapshot cannot substantiate a current pre-news expectation. Fresh production data and dashboard deployment must be verified separately; local fixture tests do not establish feed health.

## Feed recovery update

The Pre-News tab now reads a dedicated `scanner-pre-news-snapshots` publication containing only the two calendar/macro workers. It no longer requires a healthy V342 trading-engine heartbeat. The existing macro workflow refreshes on a five-minute schedule, builds a bounded allowlisted snapshot and publishes it to the separate branch. Dashboard polling remains 60 seconds; scheduled Actions cadence is best effort and source observations retain their own freshness gates.

The failed refresh was traced to `python -m fx_scanner.cli validate-config` importing an unrelated broken execution model (`OrderSide` missing). Macro configuration is now validated directly through `load_project_config`, without importing or changing order execution. The broader repository CI failure from that execution model remains a separate issue. Macro refresh/publication can report incomplete data even if one upstream provider fails, rather than leaving the old snapshot silently in place.

74 targeted tests passed after recovery changes, including source timestamp preservation, allowlisted publication without private details, stale CDN immutable-revision recovery, independent feed loading and configuration validation without broker imports. Production refresh is checked separately from these local tests.

### Production verification

Recovery workflow run `38679392249` succeeded through config validation, V192 event refresh, V399 macro refresh and isolated feed publication. The published feed carries calendar heartbeat `2026-10-15T04:03:12Z` and macro heartbeat `2026-10-15T04:03:14Z`, both healthy. Evaluating that publication at its own as-of time confirms that daily FRED observations are usable but DXY intraday is missing. Direct provider diagnostics returned HTTP 429 from Yahoo. Pipeline recovery does not establish DXY availability; the engine still abstains until a fresh valid DXY observation exists. Publication now includes a bounded source-status label (not raw errors or credentials), and the panel explains rate limiting and shows worker timestamps in WIB.
