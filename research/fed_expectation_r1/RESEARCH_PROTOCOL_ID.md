# RIZAN XAU — Fed Expectation & Macro Direction Engine R1

**Status:** Research-only point-in-time prototype; **no historical XAU trading
accuracy** and **no production deployment**. Created as a separate draft branch
based on XAU Rejection Engine V4 research (#887). The new PR is based on that
research branch, not `main`.

## Hypothesis

For XAU H1/H4 entry direction, *unexpected repricing of the expected path of
Fed policy* may matter more than a headline's simple hawkish/dovish tone.

- **HAWKISH_REPRICING:** comparable expected-policy-rate futures snapshots
  for the **same contract/meeting** rise >=2 basis points from immediately
  before to after a news event; independently observed intraday cash US2Y
  yield rises >=1 bp; Dukascopy DOLLAR.IDX/USD proxy return >=+0.05%.
  Result is `SEARCH_SELL_REBOUND`, not a trade.
- **DOVISH_REPRICING:** corresponding moves <=-2 bp, <=-1 bp and <=-0.05%:
  `SEARCH_BUY_DIP`.
- **Conflicting signals, missing source, stale quote, absent actual
  contractual comparability, event not yet released:** `WAIT`.

Thresholds are **prespecified uncalibrated hypotheses**, not empirical
probabilities or performance estimates. A policy speech's words may be
tagged hawkish/dovish in a later feature, but the label alone is NOT a
verified repricing measurement and cannot authorize a direction.

## Source hierarchy and limitations

1. Preferred monetary expectations: time-stamped futures-implied rate
   for the exact same meeting or same listed FF/SOFR contract. FedWatch
   produces *probability distributions* from 30-day Fed Funds futures;
   **an isolated hike probability is NOT the same numerical unit as an
   expected rate in basis points**. Repricing input currently requires
   BPS; it does not synthesize rate from a percent probability.
2. US2Y: observed **intraday cash nominal yield in bps**, actual
   observation/publishing times with provenance. US Treasury/FRED
   DGS2 is **daily**, not a substitute for intraday US2Y.
3. USD: `DXY_PROXY_LEVEL` may be the Dukascopy
   `DOLLAR.IDX/USD` quote and must be labelled broker-linked USD index
   *proxy, NOT ICE official DXY*. Reconstructed source availability
   carries explicit uncertainty and cannot be passed as captured LIVE.
4. The SF Fed USMPD is a **credible public post-event window study** of
   FOMC statements (30-minute), press conferences (70-minute), minutes
   (30-minute), and full monetary-event windows. It is a suitable
   historical research benchmark but **not** a pre-release news
   prediction nor a validated streaming cTrader quote feed. Official
   page last checked with reported update **2026-10-30**.
5. Daily ALFRED/FRED vintage data can provide known-at-time regimes
   separately. It cannot be silently used as intraday innovations.

Official references:
- https://www.frbsf.org/research-and-insights/data-and-indicators/us-monetary-policy-event-study-database/
- https://www.frbsf.org/research-and-insights/data-and-indicators/monetary-policy-surprises/
- https://www.cmegroup.com/tools-information/quikstrike/cme-fedwatch-tool-user-guide.html
- https://fred.stlouisfed.org/series/DGS2

## Immutable time contract

Each snapshot must have:
`series`, `instrument`, `meeting_or_contract` (for Fed),
`unit`, `value`, `bar_end_at`, `published_at`,
`ingested_at`, `provider`, `source_url`, `provenance_mode`.

All timestamps require explicit UTC offset, normalized UTC. A snapshot
becomes eligible **no earlier than** its bar close and publication time,
and for `CAPTURED_REALTIME` also no earlier than its recorded ingestion.
For historically reconstructed sources, historical quote availability
is a conservative **estimate**, not evidence of actual capture at the
claimed historical second.

Each event carries release time and official source URL. Never use
post-release futures, US2Y, DXY, language interpretation or realized
price to construct a **pre-release signal**. If a decision is made before
publication, the output must be `PRE_EVENT_WAIT`.

For this R1, decisions are evaluated up to 15 minutes after an event
for exploratory *post-event price confirmation*, with separate quote
freshness caps. The output is contextual. The 30/70 minute USMPD event
windows themselves are known only after those windows have completed;
a separate module must implement that event timestamp convention before
directly ingesting USMPD windows as inputs.

## Planned empirical test

1. Verify existence, schema, downloadable bytes, and SHA256 of the SF
   Fed official surprise ZIP; do not invent the shape or counts if
   download is inaccessible.
2. Obtain *true* comparable timestamped futures-implied rate snapshots,
   intraday US2Y quotes and USD index proxy with provider-level
   timestamp/provenance; source licenses and feed rights must be checked.
3. On the same predeclared H1/H4 and M5 rejection events, compare:
   no macro filter; headline tone alone; Fed repricing alone;
   Fed repricing+US2Y; Fed repricing+US2Y+USD.
4. Report BUY and SELL separately by year, n, unchanged baseline events,
   coverage, Wilson 95%, profit factor, MFE/MAE, event reaction 5/15/60m,
   quote latency and realistic costs.
5. 2019–2026 is heavily research-touched; recent 2025–2026 cannot be
   represented as pristine holdout. Need timestamped forward signals on
   genuinely later data before deployment.

## Guardrails

The module cannot submit orders, change cBots, modify leverage or
connection bridges, or override Frozen V1. `EXECUTION_AUTHORITY=False`
and `EXECUTION_INFLUENCE=False`. It does not merge with production,
`main.py`, Manual R3 or existing V4 behavior. Only promote after
independent dual-side >=60% with adequate n and after transaction costs.
