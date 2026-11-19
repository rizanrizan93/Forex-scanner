# Fed Expectation R1 — REAL XAU 2023-09-20 event pilot (research audit)

**Decision:** NO PRODUCTION. The official SF Fed USMPD is a retrospectively
compiled event study; its observed FOMC-window changes were not verified
as archived, streamable, historically available quotes. A valid paper
`decide()` call for 2023-09-20 **returns WAIT** because the genuine
PIT snapshots required by R1 are missing.

CI: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44616645859

Sources with verified SHA:
- USMPD XLSX 199,373 bytes;
  `2b91297c42cf692dd74f65eabf7ee97f81d452676e23fa02edb222bfa60f0d0a`
- HistData XAUUSD M1 for Sep 1-29 2023, 28,330 rows, 0 failed vendor
  periods, UTC normalization from fixed EST-5;
  `0127bae35fc66a5ba44eccf1f407fe03c7772a9d3eff2effd4e12cb98714668c`.
  Not executable FP Markets quote data.
- Official 2023-09-20 FOMC statement released at 14:00 EDT:
  https://www.federalreserve.gov/newsevents/pressreleases/monetary20230920a.htm

### Verified source units / clocks

Official USMPD README: `date_time` is **Eastern Time**, not UTC.
`MP2` and `UST2Y` event-window changes are in percentage points,
converted x100 to basis points. `DXY` event-window return is already
percent. Statement 30-minute window runs from **10 minutes before to
20 minutes after** release; press conference from 10 minutes before
to 60 minutes after start. Full monetary event covers both statement
and press conference. They overlap and are ONE independent FOMC
meeting, not three trades.

### Historical *ex-post oracle*, NOT valid at-time trade signals

| Window and decision-clock UTC | MP2 (bps) | UST2Y (bps) | DXY (%) | Offline direction | XAU H1 and H4 |
|---|---:|---:|---:|---|---|
| Statement after 18:20Z | +2.07 | +6.53 | +0.30 | SELL | H1/H4 CENSORED (missing contiguous M1) |
| PC after 19:30Z | -1.55 | +1.39 | +0.13 | WAIT | H1 complete; H4 CENSORED |
| Full monetary after 19:30Z | +0.52 | +7.91 | +0.43 | WAIT | H1 complete; H4 CENSORED |

Hypothetical post-PC next-M1-open XAU H1 counterfactual (assumed fixed
round-trip spread $0.50 per oz): BUY first touched +$3 before adverse
-$3, but ended the hour **-$4.447/oz net**. SELL first touched adverse
-$3 before +$3, but ended the hour **+$3.447/oz net**. This exposes how
barrier-first and terminal H1 correctness differ, even on the SAME
meeting and price path. Neither side is an actual eligible R1 signal:
the macro direction was WAIT.

H4 endpoints span a missing M1 region near the trading-session break;
the replay explicitly censored rather than filling prices synthetically.

### Evidence gate

- `macro_pit_live_ready_n = 0`, BUY eligible n=0, SELL eligible n=0.
- `read_only_production_review_eligible = False`.
- Fails genuine PIT sources, live age/spread, cost/slippage, prospective,
  dual-side n, Wilson lower bound and positive net expectancy requirements.
- Script, proof and JSON:
  `scripts/replay_fed_macro_event_pilot_r1.py`;
  `research/fed_expectation_r1/release_gate.py`;
  CI artifact `fed-macro-r1-real-XAU-expost-2023-sept20`.

### Follow-up research

Expand to other FOMC dates using fixed, official event-time schema and
read-only real XAU OHLC; compare *same XAU events* in matched baseline
and macro filter cohorts. The 2025–26 period has been optimized before;
never claim it is an untouched test set. The user-facing LIVE scanner,
Manual R3, Frozen V1, cBots, order routing and bridge are unchanged.
