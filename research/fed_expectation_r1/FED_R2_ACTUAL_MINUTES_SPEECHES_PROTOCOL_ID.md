# RIZAN Fed Macro Direction R2 — Actual FOMC, minutes and Fed commentary

**Branch:** `research/fed-communication-r2-20261120` (draft PR #890),
based on draft R1 #889; **NO MERGE / NO DEPLOY / NO ORDERS**.

## Why R2

R1 measured *market repricing* but did not represent the official
policy decision, FOMC minutes, or individual Fed speakers. R2 is a
**separate official-primary-source intelligence layer**. It never treats
a hawkish phrase as proof the XAUUSD price will fall; textual bias
indicates which side of the V4 rejection engine should be WATCHED.

### Priority and semantics

| Information | Operational priority | Required provenance |
|---|---|---|
| FOMC actual funds target HIKE/HOLD/CUT | highest within same release cycle | official statement, published+ingested time, prior and new target-range bps, doc SHA |
| FOMC press conference | subsequent interpretation, after actual words become available | exact publication/capture time; chairman's words |
| FOMC minutes | later update, NEVER backdated to meeting day | actual release time, distinct from original meeting DATE, official text/excerpts SHA |
| SEP projections | projections only, not actual policy | release time and projections source |
| Chair speech | individual speech, not FOMC decision | official text, timestamp, speaker and evidence excerpt |
| Voting member speech | lower priority individual view | as above |
| Nonvoting member speech | lower still, individual | as above |

The most recent **24-hour communication cycle** prioritizes the
actual FOMC statement; once a later minutes release arrives several
weeks after the meeting, its new communication bias can become the
active WATCH without overwriting the last ACTUAL policy rate.

- `actual_fomc`: rate action on the currently selected document (may
  be null if current document is minutes or speech).
- `last_fomc_actual_record`: latest verified historical committee rate
  target, with HOLD/HIKE/CUT and bp delta, never promoted as a
  *fresh* minutes/speech decision.
- `headline_stance`: verified human-reviewed excerpts, HAWKISH,
  DOVISH, MIXED or NEUTRAL. Numeric `communication_evidence_net`
  represents **annotated evidence weight, NOT win rate or probability**.
- `macro_watch_bias`: HAWKISH → SEARCH_SELL_REBOUND,
  DOVISH → SEARCH_BUY_DIP; mixed/neutral → WAIT.
- `trade_search_bias`: must remain NONE until *same-event*
  independent point-in-time expected-rate futures + intraday US2Y
  + dollar market repricing matches and was **captured realtime**.
  Conflicting market reprice → WAIT. R2 has no order authority.

**Actual vs surprise:** A hike of +25bps with pre-release
market expectation +25bps has zero *policy-rate surprise*. Even a
HOLD can be hawkish surprise if a -25bp cut had truly been priced.
Without a pre-release expected-rate observation, the engine displays
the rate action, but `surprise_bp=None`. Never convert a stale/current
FedWatch probability percent into expected bp change without a
same-meeting, timestamped rate-path methodology.

**FOMC dissent:** two individual votes for a hike do NOT turn an
official committee HOLD into HIKE. A dissent is low-weight evidence
and is always attributed as dissent, not full FOMC consensus.

## Official November 2026 evidence audited

1. October 28, 2026 FOMC **ACTUAL HOLD at 3.75–4.00%**, unchanged
   from the September target range; two dissenters preferred +25bp.
   Released **October 28, 14:00 EDT / 18:00 UTC**.
   https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm
2. October 27–28 minutes released **November 18, 14:00 EST / 19:00
   UTC** (02:00 WIB *November 19*, not on October 28).
   Released minutes report an almost universal expectation that
   further rate rises would be appropriate, under baseline forecasts.
   **Annotated HAWKISH committee outlook**; this is a *communication
   WATCH*, not a verified futures surprise or entry.
   https://www.federalreserve.gov/monetarypolicy/fomcminutes20261028.htm
3. Christopher J. Waller speech November 10, 2026 expresses support
   for another +25bp policy-rate hike in December; it is explicitly
   **his individual view**, not a FOMC rate decision.
   The public page has a date, but the exact initial public release
   minute has NOT been verified; it is an **audit-only example**, not
   retrospectively timed trading data.
   https://www.federalreserve.gov/newsevents/speech/waller20261110a.htm

Official FOMC calendars:
https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm

## Source-verification and point-in-time protocol

- The primary document URL must be official HTTPS
  `federalreserve.gov` or recognized Federal Reserve bank host.
- SHA-256 of extracted official page text is recorded; excerpts must
  match content **verbatim modulo whitespace** and be marked
  HUMAN_REVIEWED. An automated unverified LLM label, guessed
  timestamp, secondary press commentary or unrelated bank-regulation
  speech cannot authorize a trade-search bias.
- Every record has `released_at` UTC (only where genuinely known)
  and `ingested_at`. It is available only at
  `max(released_at,ingested_at)`. Minutes record the older meeting
  date as DATE, **not as release time**.
- Only Fed-related monetary-policy excerpts are considered. Fed
  speeches may not claim to represent full committee outlook.
- Date-only speech webpages require timestamped first-capture
  before they can enter any prospective signal timeline; the R2
  official audit lists such sources but does not retroactively
  assign a fictional publication minute.
- No old/reconstructed USMPD data is converted into fake realtime
  `market_context`.
- Each item has a provisional freshness ceiling (statement/minutes
  7d, chair 3d, voting member 2d, nonvoting 1d). These are *research
  hypotheses*, NOT optimized trade-horizon or empirical alpha.

## Initial validation and current status

- Code: `research/fed_expectation_r1/official_communications_r2.py`.
- Deterministic tests: `tests/test_fed_official_communications_r2.py`.
- Real official HTML audit:
  `scripts/audit_fed_official_communications_r2.py`.
- CI: `.github/workflows/fed_communication_r2.yml`.
- PR #890 is **DRAFT**. No changes to Frozen V1, cTrader/cBot LIVE,
  bridge, risk, V4, Manual R3, or production entry system.
- Existing R1 2019–2026 **ex-post** price replay:
  D1 triple-market BUY 8/10 (80%) but SELL 3/8 (37.5%),
  D5 BUY 5/9 (55.6%) and SELL 2/7 (28.6%). R2 text classifier has
  **NOT YET completed 2019–26 event-wise historical replay** with
  source-complete release clocks, speaker roles, and actual first
  publication timestamps. It is not proven to improve the R1 results.
- Production evidence gate remains locked: same-event true
  point-in-time macro quotes, independent forward data, realistic
  spread/carry/slippage, separately validated BUY and SELL results.

## Next research

Build a first-observed official document capture ledger for new
statement/minutes/speeches as they arrive with separate speaker
attribution and preserved source sha; compare R2 tone vs R1 market
repricing on *matched* past timestamped XAU events and future
prospectively captured samples. Do not label an unverified
2019–2026 news-sentiment backtest as completed.
