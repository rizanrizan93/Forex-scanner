# RIZAN causal zone destination and entry research

Research only; no execution authority or influence. Complements the V303 style
path engine without changing its live/dashboard decisions. D1 database work
remains paused. No claim of an ideal entry, guaranteed reversal, fill or TP.

## What changed

The previous cycle experiment sampled retrospective H4 first-touch plans. This
experiment takes an observation at EVERY available hourly M1 open in each test
year, including unpaired maps and missed/invalid orders. It records all active
H4/H1/M15 zones from the existing detector, their past touch episodes and age,
the nearest external demand and supply, zones already containing the price,
and momentum/range calculated from the preceding completed hour. A zone inside
the current price is recorded separately, not mislabelled as an approaching
external destination. This is a retrospective historical ledger, not yet a
live broker-event recorder.

Prediction features are separated from future labels and the zone outcome
catalog. Zone invalidation by close is available at M1 close, one minute after
the bar-open timestamp. Replacement zones remove predecessors only from the
replacement's own availability time onward. The research builder excludes
imbalance detections backdated before the shared detector's 20-bar warmup;
the shared runtime detector itself is unchanged. Prefix-versus-full-history
zone tests and future-price perturbation tests protect this contract.

## Frozen experiment

- Destination: supply first, demand first, neither, or same-candle ambiguous
  within 30/120/240 minutes. Edges are frozen at observation time. This measures
  which price boundary is reached first, not a quote-side executable fill.
  Broken/superseded future geometry is not silently rewritten in a past label.
- Gapped destination/reaction windows are censored, including weekend closures.
  Missing past-hour data and unpaired maps remain visible in coverage counts.
- Reaction after the first unambiguous 240-minute destination: price reaches
  0.5 zone ATR away from the outer proximal before a close beyond distal,
  within a further four hours. No reaction credit on the touch candle;
  break wins ambiguous candles. Outcomes include neither and censored.
- Entry: both directions, depths 25/50/75%, structural stop 0.15 zone ATR beyond
  distal; TP before the opposite outer edge by 10% of its width, capped at $1.
  Minimum 1.5R, four-hour pending window, four-hour hold; pending orders cancel
  when source-zone lifecycle ends. Cancellation times are labels, never inputs.
  All six candidates remain in paired denominators, including invalid geometry.
- Entry replay reuses the conservative quote-side cycle simulator: no fill-bar
  TP, stop-first ambiguity, stop gaps, actual next available timed-exit quote,
  base/stress costs. The $5 criterion is XAU price dollars, not broker points.
  Fast precise TP means $1 favourable movement within 15 minutes, TP before SL,
  and maximum adverse movement through exit no larger than $5.

## Model and evaluation

The destination model is intentionally small: nine cells formed by relative
zone distance and UP/DOWN/FLAT past-hour momentum. It estimates all four classes,
shrinks each cell toward the training prior with 20 pseudo-observations, and
backs off entirely when a cell has fewer than 100 observations. No DOM data is
invented from OHLC. This tests whether distance/momentum add predictive value
before adding more indicators or regime filters.

2024–2026 pilot; each test year uses only earlier years with all outcomes mature
before January 1. Predictions are evaluated with accuracy, multiclass Brier score
(lower is better), confidence calibration bins, and paired Brier improvement
versus the training-only unconditional prior. A fixed-seed daily block bootstrap
provides a descriptive 95% interval for the Brier improvement; overlapping
hourly outcomes still limit independence, and this is not a promotion guarantee.

Entry depth is selected separately by side on prior-year training only, maximizing
fast precise TP subject to at least 100 paired observations, fill no worse than
the 50% baseline minus 5 percentage points, TP count no lower, and positive
stressed expectancy. Report selected/base/stress outcomes on the next year.
Destination probabilities and entry-depth results are NOT yet a validated joint
execution policy. A correct destination forecast does not imply a profitable
reversal entry at that destination.

All results are per opportunity, not portfolio return. Overlapping observations
can refer to the same zone and repeat a hypothetical trade; ten-position limits,
margin and portfolio risk are not simulated. Historical detector parameters
were designed retrospectively; chronological testing is not prospective broker
validation. Do not tune on this pilot then call the same years untouched OOS.

## Run

```sh
PYTHONPATH=src python -m unittest discover -s tests -p test_research_xau_zone_destination.py -v
python -m fx_scanner.research_xau_zone_destination_runtime --year 2024 --output artifacts/xau-zone-destination-2024.json
python -m fx_scanner.research_xau_zone_destination_runtime --shards artifacts --output artifacts/xau-zone-destination-full.json
```

The workflow pins the same HistData downloader commit as the earlier experiment.
Failed download periods fail the run; provenance includes source checksums and
price end dates. The GitHub yearly artifacts preserve the full ledger; the
aggregate is small enough to retain in the repository.
