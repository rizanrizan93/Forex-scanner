# RIZAN Fed R2: anti-inversion official FOMC action replay (2019–2026)

**Research-only and non-production.** This study addresses a specific
failure mode: a monetary-policy **HIKE** must never be reported as a
**CUT**, nor an official **HOLD** as HIKE due to individual dissents.
Separately, a RATE HIKE can coexist with a DOVISH monetary policy
*surprise* relative to what the futures curve had expected.

## Official-source method and data

- Historical event clock/price data from previously sealed R1
  read-only real-XAU replay, GitHub Actions run
  https://github.com/rizanrizan93/Forex-scanner/actions/runs/44621561755 .
- 69 events, 2019–2026, with XAU M1 and H4/D1/D3/D5/D10 outcomes
  already evaluated; price source USMPD + public secondary HistData
  (not archived FP Markets executable quotes).
- Fetch official Federal Reserve historical HTML statement pages, verify
  origin, SHA-256, extract direct *Committee decided to ... target
  range for the federal funds rate* phrase, then label only the actual
  committee rate action as HIKE/HOLD/CUT. Unclear or missing action is
  UNRESOLVED, not a guess.
- Separately compare to R1's ex-post next-meeting expected rate
  shock `MP2` (BUY/SELL/WAIT); DO NOT substitute that surprise for
  the *actual rate decision*. Primary source USMPD final study
  observations were retrospectively compiled, not proven historical
  real-time publication. No R2 natural-language 2019–26 minutes or
  speeches performance claim is made here.
- Historical label results after modeled $0.50/oz XAU cost are
  **descriptive** directional hypothetical from actual HIKE -> SELL,
  actual CUT -> BUY, HOLD -> WAIT. Neither trade fills nor alpha
  signal calibration are established.

## Verified completed 2019–2026 official statement replay

GitHub CI: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44626967420

| Actual source classification | Number |
|---|---:|
| Official FOMC events | 69 |
| Clear committee action verified from official statement text | 63 |
| HOLD | 41 |
| HIKE | 12 |
| CUT | 10 |
| Source/phrase unresolved (preserved as UNKNOWN) | 6 |

The six UNRESOLVED dates are:
2019-10-04, 2020-03-03, 2020-03-19, 2020-03-23, 2020-03-31,
2020-08-27. Some official event-study rows represent emergency or
special-policy communications rather than regular target-rate
decisions. Source 404 or unmatched committee-action wording is a
**quality/correctness guard**, not a reason to fabricate actions.

### Actual monetary action versus EX-POST MP2 surprise

| Official action | MP2 BUY (dovish) | MP2 WAIT | MP2 SELL (hawkish) |
|---|---:|---:|---:|
| HIKE | 5 | 5 | 2 |
| HOLD | 6 | 31 | 4 |
| CUT | 3 | 4 | 3 |

Therefore **8 of the HIKE/CUT actions** had an *opposite-sign*
reconstructed MP2 response. Examples:
2022-03-16, 2022-05-04, 2022-06-15, 2022-07-27,
2022-09-21: actual HIKE and dovish MP2 repricing.
2019-07-31, 2019-09-18, 2025-10-29:
actual CUT and hawkish MP2 repricing.

This is not a classification inversion: `actual_action` and
`policy_surprise` must always appear as **different fields**,
each anchored to a distinct type of evidence.

### Descriptive XAU direction (actual action alone, no curve surprise)

| Actual action -> naive direction | D1 | D3 | D5 | D10 |
|---|---:|---:|---:|---:|
| HIKE -> SELL | 3/9 (33.3%) | 4/8 (50.0%) | 4/8 (50.0%) | 3/7 (42.9%) |
| CUT -> BUY | 4/10 (40.0%) | 8/10 (80.0%) | 6/9 (66.7%) | 6/8 (75.0%) |

Directional outcomes have small, selected, sometimes censored n and
are not independent prospective signals. In particular, an actual
rate hike does NOT automatically make a gold short profitable.

## Anti-inversion R2 hard gates

1. `polarity_guard_r2.py`: check *policy directional verbs* in exact
   verified evidence excerpts. Hawkish label on a direct cut phrase,
   dovish label on a direct hike phrase -> reject. Negated, conditional,
   contradictory or unsupported phrases -> UNRESOLVED/WAIT.
   This deterministic phrase guard is **NOT a complete semantic model**.
2. `official_communications_r2.py`: numerical previous/current
   target-rate range must match a direct official *Committee decided
   to ...* phrase and its direction; dissents are individual votes,
   not a new actual committee hike. Opposing statement tone and action
   without a pre-release captured expected path -> WAIT.
3. No FOMC minutes may be used at the original meeting date.
   Minutes get their actual **publication and ingestion time**.
   Individual speakers cannot claim committee-level consensus.
4. `presentation_r2.py` **separately renders** most recent verified
   rate action, official communication tone, market expected-policy
   surprise (if genuinely sourced), and provisional XAU watch bias.
   It throws on inverted HAWKISH->BUY or DOVISH->SELL mapping.
5. `trade_search_bias` remains NONE unless genuine same-event
   *captured* futures-expectation reprice, intraday UST2Y and USD index
   agree. Even then it is RESEARCH_ONLY and has no execution authority.

## Primary 2026 examples

- **28 Oct 2026:** actual FOMC rate action HOLD at
  **3.75%–4.00%**, two dissenters preferred +25bp. Not a HIKE.
  https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm
- **18 Nov 2026 published minutes:** outlook mentioned further rate
  rises likely appropriate. Communication evidence HAWKISH, watch
  `SEARCH_SELL_REBOUND`, **not a live confirmed trade**; the latest
  actual rate record still says HOLD.
  https://www.federalreserve.gov/monetarypolicy/fomcminutes20261028.htm
- **10 Nov 2026 Waller speech:** an individual's hawkish policy
  view. Public release minute not verified in the audit (date only),
  so no minute-precise backdated research signal.
  https://www.federalreserve.gov/newsevents/speech/waller20261110a.htm

## Gate and scope

This replay verifies OFFICIAL RATE ACTION classification on 63/69
historical primary documents and tests specific anti-inversion logic.
It does **not** replay the full FOMC minutes, press conferences,
SEP and every Fed official's speech 2019–26 and does not prove
narrative polarity accuracy across those unreviewed documents.

- No historical real-time quote/source ingestion record of new R2
  release-specific text: true as-of R2 BUY n=0 / SELL n=0.
- Prior R1 ex-post macro SELL D5 was 2/7 (28.6%), insufficient.
- Production remains **LOCKED**. Do not merge PR #890, parent #889
  or #887 or change Frozen V1, Manual R3, cBot LIVE, bridge, orders,
  account risk, until data and independent prospective tests
  actually satisfy the two-direction release gate.
