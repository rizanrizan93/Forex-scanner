# XAU Expansion V4 — Purged Anchored Walk-forward Evidence

Research only. Production and execution influence remain disabled.

## Design

- Public D1 XAU proxy history: 3,693 bars, 2012-01-03 through 2026-09-11.
- 81 predefined parameter-neighborhood configurations across signal strictness, stop/target geometry, trend confirmation and maximum holding period.
- Five anchored expanding train/test folds with a 31-day purge gap.
- Parameter selection for every fold uses only data available before that fold.
- Same-bar stop/target ambiguity is resolved conservatively as stop first.
- Results are repriced at 0.05R, 0.10R and 0.15R cost per trade.
- The parameter neighborhood was designed after V1–V3 research, so the full 2012–2026 archive is not a pristine never-seen holdout even though each fold selection is past-only.

## Fold results at 0.10R stress cost

| Fold | Train through | OOS test | Selected config | Trades | Net R | Expectancy | Profit factor |
|---|---|---|---|---:|---:|---:|---:|
| F1 | 2016-12-31 | 2017-02-01..2018-12-31 | S2R0T0H0 | 13 | +2.5000R | +0.1923R | 1.3247 |
| F2 | 2018-12-31 | 2019-02-01..2020-12-31 | S2R0T0H0 | 10 | +0.2000R | +0.0200R | 1.0303 |
| F3 | 2020-12-31 | 2021-02-01..2022-12-31 | S2R0T0H0 | 11 | -3.7000R | -0.3364R | 0.5795 |
| F4 | 2022-12-31 | 2023-02-01..2024-12-31 | S2R2T2H0 | 7 | +1.8164R | +0.2595R | 1.5603 |
| F5 | 2024-12-31 | 2025-02-01..2026-09-30 | S2R2T2H0 | 10 | +7.7214R | +0.7721R | 2.6158 |

The selected regime changed after the weak 2021–2022 period. `S2R0T0H0` uses the strict signal state with a 1.0 ATR stop, 1.8R target, loose EMA trend confirmation and 7-bar maximum hold. `S2R2T2H0` keeps the strict signal state but uses a 1.25 ATR stop, 2.6R target, full EMA20/EMA50/EMA200 directional confirmation and the same 7-bar maximum hold.

## Aggregate OOS

| Cost | Trades | Win rate | Net R | Expectancy | Profit factor | Max DD proxy | Return proxy at 0.5% risk |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0.05R | 51 | 41.18% | +11.0877R | +0.2174R | 1.3743 | 3.99% | +5.55% |
| 0.10R | 51 | 41.18% | +8.5377R | +0.1674R | 1.2743 | 4.37% | +4.21% |
| 0.15R | 51 | 41.18% | +5.9877R | +0.1174R | 1.1836 | 4.76% | +2.89% |

The center V3-like configuration `S1R1T1H1` produced 73 OOS trades at 0.10R cost, +6.6615R, +0.0913R expectancy and PF 1.1331. The walk-forward-selected parameter neighborhood therefore improved stress-cost expectancy and PF while using fewer trades.

## Router-level V4 finding

A separate 27-configuration V4 test attempted to choose the entire adaptive router from anchored historical router outcomes. Its robustness gate selected `NO_TRADE` in all five folds because the routed trade sample was too sparse at each training cutoff. The fixed V3 router reference was still positive over the same OOS windows at 0.10R cost: 22 trades, +5.1615R, +0.2346R expectancy and PF 1.3757. The appropriate interpretation is that router-level promotion evidence is still insufficient, not that the XAU expansion family lacks edge.

## Status

V4 materially strengthens the XAU expansion hypothesis: aggregate purged OOS remains positive even under 0.15R severe cost. However, F3 is a clear historical failure regime and aggregate PF under 0.10R stress is 1.2743, below a strong production-grade target. Status remains `RESEARCH_CHALLENGER`; no automatic production promotion is authorized.
