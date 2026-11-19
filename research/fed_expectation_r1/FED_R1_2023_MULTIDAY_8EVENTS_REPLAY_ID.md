# Fed Macro R1 — H4/D1/D3/D5/D10 XAU replay, 8 FOMC meetings (2023)

**CI:** https://github.com/rizanrizan93/Forex-scanner/actions/runs/44619070800

**Research outcome:** test methodology 17/17 tests PASS. All 8 scheduled
FOMC dates acquired, zero failed provider periods. Official USMPD source
SHA `2b91297c42cf692dd74f65eabf7ee97f81d452676e23fa02edb222bfa60f0d0a`.
XAUUSD historical M1 fetched in 23-calendar-day following windows,
provider git pin `4a3c11b67f97758f6e3f77a3e5905b6aa87367b8`,
fixed EST-5 source timestamp -> UTC. Each per-date normalized SHA
stored in raw event artifact
`fed-macro-r1-multiday-2023-XAU-real-expost`.

**Method:** for each completed FOMC statement, press conference and
full-event window, a historical *ex-post oracle* BUY/SELL/WAIT
classification based on `MP2`, `UST2Y`, `DXY` changes. Measure future
XAU directional net return at subsequent full UTC weekday trading
sessions D1/D3/D5/D10, not fixed $3 TP, with historical hypothetical
entry next M1 open and modeled $0.50/oz trading cost. Price data gaps,
partial weekday sessions, insufficient future data are CENSORED.
H4 requires 240 complete contiguous M1. Multiple views of a single
meeting cannot be pooled as separate independent bets.

## Primary table: FULL MONETARY event window only (8 meetings)

| Direction from oracle | Selected meetings | D1 correct/n | D3 correct/n | D5 correct/n | D10 correct/n |
|---|---:|---:|---:|---:|---:|
| BUY | 2 | 2/2 (100%) | 1/2 (50%) | 1/2 (50%) | 0/1 (0%; one censored) |
| SELL | 0 | n=0 | n=0 | n=0 | n=0 |
| WAIT | 6 | not a trade | not a trade | not a trade | not a trade |

- D1 full-event BUY Wilson 95% interval **34.24%–100%**,
  NOT confident >60%.
- D5 BUY median signed net return **-0.3292%** despite 1/2
  terminal direction wins.
- D10 BUY 1/2 censored; the only measured outcome was
  wrong-direction, signed net return -0.9547%.
- H4 for BOTH oracle BUY meetings is censored by M1 daily session
  gaps; do not invent H4 accuracy.
- No observable valid SELL sample on full monetary windows in this
  2023 subset, so BOTH-side >=60% is not established.

### Event window sensitivity / post-event persistence

A different (but overlapping and **not additional independent**)
`STATEMENT` view classifies Sep 20 2023 as SELL (1/8 statement
events). In the expanded real-XAU price window, this single event:
- D1 1/1 correct, signed net +1.3646% SELL;
- D3 1/1 correct, signed net +1.5454%;
- D5 1/1 correct, signed net +3.5803%;
- D10 1/1 correct, signed net +6.3862%;
- H4 censored because actual M1 path crossed market closure.

This is one example of a potentially **multi-day/multi-week** effect,
**not a validated edge**. Press conference and full-event views on
the same meeting no longer classified SELL (both WAIT): what the
trader could know depends on which completed window is actually
available and the reaction to intervening communications.

## Implications

1. A monetary-policy surprise must be evaluated separately as an
   **H4/D1/D3/D5/D10 macro direction**; success/failure at $3 scalp TP
   is not a metric of weekly macro regime.
2. Bias can work D1 but fail D5/D10. Macro expectations must be
   reassessed as fresh data and Fed comments arrive; don't freeze
   direction for a week without revalidation.
3. H1/H4 entry timing and M1/M5 rejection performance remain
   separate secondary engineering modules.
4. USMPD factors were reconstructed retrospectively by researchers
   and are not archived actual intraday delivery. Thus the
   **as-of genuine BUY and SELL candidate n remain 0** and no
   live/trading accuracy can be claimed, irrespective of an ex-post
   1/1 or 2/2 streak.
5. Sample 2023 already touched in prior research, not a pristine
   holdout; broker spread/slippage and real-time quote age unknown.
6. Source calendar: D1/D3/D5/D10 mean *subsequent fully observed
   weekday UTC trading session closes*. This is a transparent
   approximation, not a verified FP Markets settlement calendar.

## Production gate

**LOCKED.** PR #889 is draft, targets #887 research branch; do not
merge or deploy. Frozen V1, Manual R3, cBot LIVE, bridge, orders
and risk remain unchanged. Require timestamped genuine policy-rate
futures and intraday cash US2Y + DXY source, matched freeze-time
XAU events, dual-side n and independent prospective validation,
transaction costs, and long-horizon signed return benchmarks.
