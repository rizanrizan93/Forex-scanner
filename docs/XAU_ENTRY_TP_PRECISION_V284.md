# XAU entry ±$5 and TP reach: V284 shadow research

## Historical baseline

Source: successful GitHub Actions run `36305482638`, V242 year shards 2012–2026.
Reproduction: extract `xau-v242-year-*` artifacts and run
`python scripts/research_xau_entry_tp_precision_v284_baseline.py --shards DIR --output REPORT.json`.
The checked-in [JSON](xau-entry-tp-precision-v284-baseline.json) contains all
four slots and era splits. The 2026 source ends on 2026-09-18, so 2026 is partial.

| Era / slot | Opportunities | Filled | TP | TP with ≤$5 adverse | Joint success |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2012–2018 L1 | 1,598 | 1,145 | 495 | 474 | 29.7% |
| 2019–2024 L1 | 1,323 | 955 | 400 | 348 | 26.3% |
| 2025–2026 L1 | 429 | 294 | 123 | 63 | 14.7% |
| 2025–2026 L2 | 429 | 300 | 92 | 35 | 8.2% |

For the baseline, `mae_r × risk_pips × $0.01` measures the largest M1 OHLC
adverse move between simulated fill and exit. Success requires target hit and
at most $5 adverse movement; a miss, stop, cancellation, or timeout fails the
joint outcome. V242 assumes a mid OHLC limit touch is a fill; this is optimistic
and cannot validate actual broker fill probability. These are retrospective
current-parameter results, not independent out-of-sample evidence.

## V284 quote-side replay

`research_xau_entry_tp_precision_v284.py` takes frozen V242 pre-touch L1/L2
entry and structural target pairs. A LONG limit requires ask to reach entry;
a SHORT limit requires bid to reach entry. The reverse quote side triggers
TP and SL. Fixed base/stress spread and slippage are proxies because historical
bid/ask ticks are unavailable. A target on the fill candle does not count;
SL wins an ambiguous candle. The maximum adverse excursion is measured through
TP, including the fill and exit candles conservatively.

The replay reports fill rate, TP conditional on fill, TP per opportunity,
`TP AND adverse ≤$5` per opportunity, expectancy per opportunity, and a Wilson
lower bound. A preceding-year training fold may choose an alternative only if
its fill rate is within five percentage points of baseline, TP per opportunity
does not fall below baseline, and stressed expectancy is positive. The test
year never affects selection. Missing pair coverage invalidates that fold.

Run `python scripts/research_xau_entry_tp_precision_v284.py --plans YEAR.json
--m1 YEAR_PLUS_30D_M1.csv --output REPORT.json`, repeating the input pair for
multiple years. Yearly V242 artifacts do not include raw M1 candles. Until
matching M1 inputs and independent prospective broker-fill evidence exist,
the selected pair has no execution authority. The $5 bound is a measured
historical condition, not a guarantee that the next reversal stays within $5.
