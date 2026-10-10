# Frozen XAU/EUR staged layering replay

Research only. No scanner, dashboard, DB, broker or production policy is changed.
Frozen signal generation is preserved; only basket execution layering changes.

Run from the repository root:

```bash
python scripts/research_distributed_layering.py --symbol EURUSD --data /path/to/eur-parquet --cache /path/to/private-cache --output research/results/distributed_layers_eurusd_2016_2025.json
python scripts/research_distributed_layering.py --symbol XAUUSD --data /path/to/frozen-archive --cache /path/to/private-cache --output research/results/distributed_layers_xauusd_2016_2025.json
python -m pytest tests/test_distributed_layer_replay.py -q
```

EUR inputs: ten `EURUSD_2016.parquet` through `EURUSD_2025.parquet` files from
`RIZAN_CROSS_ASSET_DATA_2016_2025.zip`. Only EUR price bars are read. HistData
naive M1 open timestamps use fixed EST (UTC−5); no daylight-saving conversion.
The existing frozen EUR replay helper is reused for virtual trades and virtual
feedback, without any cross-asset filter, calibration or leader observations.

XAU archive inputs:

```
frozen-archive/
  g-0006.npz
  g-0274.npz
  hybrid-audit-0-1.npz
  data/
    xau-2016.csv ... xau-2025.csv
    events_2016_2025.csv
    macro_daily.csv
```

The signal files come from `RIZAN_XAUUSD_Pencarian10Tahun_Checkpoint_20261009.zip`.
The price/calendar/macro files are in its nested
`sources/RIZAN_XAUUSD_10Tahun_Kode_Bukti_20261009.zip`. The independent audit NPZ
comes from `RIZAN_XAUUSD_DD50_BuySell_Bukti_20261009.zip`. Array files are loaded
with `allow_pickle=False`. Private caches are locally generated Python pickles;
do not use downloaded or untrusted pickle files as caches.

XAU streams are original frozen SELL sweep group 6 and BUY regression-channel
reentry group 274. Original strict H1/M15 setup eligibility stays archived.
Original daily yield and news gates remain part of that frozen baseline: this
is not a new lead–lag experiment. A technical price-only XAU substitute is
explicitly rejected. Original price index includes 2015 warmup and trims later
year warmup at WIB year boundaries to match signal array indices.

Both baselines must reconcile balance, count and PF before a final report can
be emitted. XAU additionally reconciles its archived equity DD. EUR retains
frozen virtual feedback even when execution changes.

## Layer experiment

Four stage depths are 0, s, 2s, 3s times initial structural stop distance, where
s is .15, .25 or .30 R. Adds expire after 120 minutes. All children share the
original absolute SL, TP and frozen holding expiry; stops never widen.

- BASELINE: all frozen children at original entry.
- UNIFORM: split original child count equally over stages.
- DEEP_WEIGHTED: split original child count with increasing stage weights.
- CONFIRMED_DEEP: weighted splitting with causal reversal required for adds.
- CONFIRMED_MORE/QUADRATIC: reserve original planned basket USD risk, allow
  extra native children at better prices if confirmed; linear/quadratic weights.
- FULL_INITIAL_CONFIRMED: original initial children stay intact; adds may use
  unused capacity up to the frozen total risk cap fixed at basket opening.
  These exploratory variants use a larger reserved risk budget than split
  variants, although the production risk fraction ceiling remains unchanged.

BUY is mirrored for SELL. Confirmation means a completed M15 candle breaks
its previous candle high/low in trade direction, plus a completed M5 break,
with frozen H1 bias permitted (and strict M15 bias for XAU). This explicit
candle-break definition is not a claim that every structural reversal is found.
A previous adverse move qualifies depth; the fill uses the current observed
quote after confirmation. Only one stage is filled per distinct confirmation.
No historical trough prices are granted retrospectively.

Integer native child sizes, cost-adjusted risk caps and current floating-equity
margin checks apply. XAU extra-child experiments relax the balance-step desired
count inside this research module only; they preserve 12.5% total risk / 50%
margin ceilings. EUR preserves its virtual risk multipliers, 27.25% ceiling,
60% margin and hard child cap. Synthetic carry is separate from planned SL risk.

Ambiguous M1 bars use STOP_FIRST. Limit orders crossed before intrabar stop are
charged losses; an invalidating open cancels pending adds. If both TP and a
pending limit could occur on an otherwise valid bar, pending fills are cancelled
rather than granting an extra winner. Exact tick order remains unknown.

## Validation interpretation

Primary replay starts with $100 once and compounds continuously for 2016–2025.
Annual `reset_100` metrics are supplemental only. Expanding walk-forward selects
parameters from prefix trades through the previous year. Selection minimizes
DD subject to PF/expectancy >=95% of baseline, frequency >=75%, >=30 trades.
Validation uses the same causal baseline cash at each year start for both modes;
folds are separate experiments, not a stitched deployable portfolio curve.

Temporal validation covers 2019–2025; final selection uses 2016–2024 for 2025.
The frozen baseline was previously optimized on this same history. This entire
history has been seen; no fresh or prospective OOS claim is warranted. Additional
FULL_INITIAL variants were specified after initial split-layer results were seen,
so they are exploratory historical validation, not a blinded holdout experiment.

Stress includes spread/slippage ×1.5/2/3, confirmation delay 1/5/10 minutes,
random removal of 10% of opportunities and 1% of execution quotes. Quote removal
preserves offline features/signals, so it is not a complete feed-failure replay.
Trade block bootstrap uses 500 draws of 5-trade blocks. Monte Carlo ordering is
explicitly a fixed historical percentage-return surrogate, not full resizing.

Costs preserve frozen assumptions, not actual historical FP Markets ASK fills,
liquidity or leverage. XAU preserves variable spreads, causal prior-bar shock,
archived news shocks, .05 slip per side, synthetic NY17 rollover and frozen TP
exit convention. EUR uses .00012 spread and .00001 per-side slip. Reference
leverage is 100. EUR equity DD uses an OHLC bound; XAU uses the frozen
adverse-then-close marker. Neither is exact tick equity DD. Sharpe and Sortino
are not calculated without a complete uniform account-equity time series.
