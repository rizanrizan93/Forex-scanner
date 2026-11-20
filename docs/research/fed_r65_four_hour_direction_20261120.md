# R6.5 — XAUUSD 4-Hour Directional Search Engine (READ-ONLY RESEARCH)

**Purpose:** By each observed point-in-time snapshot, issue one temporary
four-hour research watch: SEARCH_BUY, SEARCH_SELL or WAIT. No automatic
entry, broker order, Frozen V1 modification, or claimed forecast skill.

## Forecast target and review
- The search bias applies to the interval decision time -> 4 hours.
- Re-score every 15 minutes rather than freezing a four-hour trade
  instruction. Original issued direction must be retained for
  prospective outcome scoring; never rewrite historical calls.
- Reproducible test: NEXT-M5-OPEN hypothetical fill and 48th
  subsequent closed M5 (4h) endpoint, minus round-trip spread.
  Measure MAE separately from the correctness of final direction.
- Missing candles, weekends or stale sources imply no tested call.

## Directional search gates
1. Fresh price quote and M1 closed timestamps; reports read-only.
2. Completed H1 and M15 must agree. Completed H4 cannot oppose.
3. M5 liquidity screen must show NORMAL. Displacement, sweep,
   widening spread, 3-bar cooldown or missing evidence => WAIT.
4. Macro BUY/SELL accepted only if R6.1 daily direction, two
   official-source US2Y/US10Y gold-direction fields and fresh
   DXY direction all align with that side. Opposite macro => WAIT.
   If only daily yield leans opposite price => WAIT.
   Technical-only search is a lower-evidence watch, never approval.
5. Known FOMC/CPI/PPI/NFP inside the next 4 hours or released
   in the previous 30m => WAIT. Missing calendar is UNVERIFIED,
   never presented as absence of high-impact news.
6. Within 0.30x M5 ATR reference of previous completed
   Asia/NY session high/low => WAIT; these are theoretical stop
   concentration references, not actual observable stop orders.

The evidence_score (3 to 5 votes) is deterministic and is
**NOT** a win probability or statistical confidence.
win_probability_pct remains null throughout the research stage.

## Replay and acceptance
R6.5 has a synthetic regression suite, not 2019–2026 performance.
Paired point-in-time captures of broker M5, macro and price reports
are required before accuracy can be measured.

1. Freeze hypotheses using 2019–2024; leave 2025–2026 untouched
   as out-of-sample, then monitor prospectively.
2. Execute fed_r65_four_hour_replay.paired_r65_four_hour_replay
   using real time-of-receipt snapshots, with horizon_bars=48.
3. Report BUY and SELL separately: sample counts, correct direction,
   Wilson95 lower bound, net average move, worst adverse excursion,
   blocked losers versus blocked winners, signal coverage.
4. Include spread and 1–3 bar latency sensitivity, stress
   regimes including 2020 and 2026, and reject look-ahead
   ex-post FOMC/OIS/COT/OI inputs.
5. Dashboard display is research-only. No cBot or Frozen V1 changes.

Known limitation: The linked ForexRizan tables do not contain the
full 2019–2026 XAU M5 plus point-in-time DXY/Treasury source
receipts. There is therefore no support for claiming 80%
BUY/SELL prediction performance yet.
