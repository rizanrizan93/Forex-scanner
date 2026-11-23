# RIZAN R29.2–R29.3 — Precision, Coverage, and ATR Magnitude Research Receipt

**Research date:** 23 November 2026 (WIB)  
**Scope:** XAUUSD H4 first, H1 and D1. **Research only.** No promotion to ForexScanner, no Frozen V1/cBot modification, no orders.

## Actual GitHub Actions evidence

- **R29.2**: [workflow run 45170505333](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45170505333). All 6 historical runs plus anti-leakage/no-order tests: **SUCCESS**.
- **R29.3**: [workflow run 45171144710](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45171144710). All 6 runs plus anti-leakage/no-order tests: **SUCCESS**.
- Fixed historical provenance: [R10 shards run 44901264975](https://github.com/rizanrizan93/Forex-scanner/actions/runs/44901264975) H1/H4 2019–2026; [R9.8 run 44886465487](https://github.com/rizanrizan93/Forex-scanner/actions/runs/44886465487) D1 2012–2026.
- Annual fold proof, selected model, gate, threshold, support, after-cost drift, and all individual results remain in the 12 workflow artifacts `r292-*` / `r293-*`.
- Frozen checkpoint for strongest historical side: [`RIZAN_R292_H4_BUY_PRECISION_RESEARCH_LOCK_20261123.json`](./RIZAN_R292_H4_BUY_PRECISION_RESEARCH_LOCK_20261123.json). Source JSON SHA256 `f5fb876d38b5e8e8599037d1474aa6c2c62ffc3a8ba3a66c845916a8bc2aaa2c`.

**Important:** All years 2023–2026 have already been inspected in R1–R29. These later experiments are *adaptively proposed and evaluated on previously examined periods*, NOT fresh blind OOS. Annual walk-forward training/validation protects direct label leakage but **does not** eliminate research-process overfitting.

## R29.2: family and regime/validation configuration extension

Fixed before results: two side-independent regimes, `precision` and `balanced`, with new causal liquidity/structure feature groups, more event/trend/session gates, shallow HGB, ridge-regularized logistic classifier, and ExtraTrees. Select each side on previous-year validation only; account for Wilson lower95, half-year support, and prior-year assumed-cost net drift. A side conflict remains WAIT. Direction label remains NEXT closed candle close-to-close.

| Horizon / R29.2 variant | BUY correct/n | BUY acc | SELL correct/n | SELL acc | Combined coverage | Pass all gates |
|---|---:|---:|---:|---:|---:|---|
| **H4 precision** | **79/126** | **62.70%** | 127/226 | 56.19% | 8.59% | **NO** |
| H4 balanced | 175/309 | 56.63% | 165/303 | 54.46% | 14.93% | **NO** |
| H1 precision | 208/412 | 50.49% | 250/507 | 49.31% | 5.67% | **NO** |
| H1 balanced | 1707/3242 | 52.65% | 269/574 | 46.86% | 23.53% | **NO** |
| D1 precision | 84/179 | 46.93% | 44/92 | 47.83% | 31.19% | **NO** |
| D1 balanced | 136/279 | 48.75% | 39/83 | 46.99% | 41.66% | **NO** |

**H4 precision BUY**, the new research high-water mark:
- Aggregate `79/126=62.6984%`, Wilson 95% lower **53.9958%**, average close-to-close gross **+$1.064/oz**, net after hypothetical $0.70/oz **+$0.364/oz**, side coverage **3.0747%**.
- 2024 35/50=**70.00%**, net **+$1.3887/oz**; selected on 2023 validation: `hgb / broad_context / threshold 0.54 / trend_strong`.
- 2025 30/53=**56.60%**, net **−$1.6927/oz**; selected on 2024 validation: `ridge / event_geometry / 0.58 / all`.
- 2026 14/23=**60.87%**, net **+$2.8757/oz**; selected on 2025 validation: `ridge / broad_context / 0.54 / trend_impulse`.
- A pooled historical percentage above 60% does **not** establish that the single 2026 model predicts live over 60%, nor a statistically established population accuracy >60%.
- **H4 precision SELL 2026**: 60/93=**64.52%** yet net **−$1.7863/oz**; high directional hit rate can still lose money due to wrong-side movement size. Overall SELL 56.19%, net −$0.9996/oz; NOT qualified.

## R29.3: expected next-bar magnitude, rather than direction probability

Tests a different hypothesis to address SELL cost asymmetry: fit Ridge/HGB-regression variants to NEXT candle's signed close-to-close return in current ATR units (fixed ±6 ATR winsorization), combine independent side thresholds and causal event gates; select on prior-year validated support, accuracy and after-cost expected value.

| Horizon / R29.3 variant | BUY correct/n | BUY acc | SELL correct/n | SELL acc | Combined coverage | Pass all gates |
|---|---:|---:|---:|---:|---:|---|
| H4 precision | 40/76 | 52.63% | 56/106 | 52.83% | 4.44% | **NO** |
| H4 coverage | 125/230 | 54.35% | 73/159 | 45.91% | 9.49% | **NO** |
| H1 precision | 207/374 | 55.35% | 215/459 | 46.84% | 5.14% | **NO** |
| H1 coverage | 537/1055 | 50.90% | 688/1416 | 48.59% | 15.24% | **NO** |
| D1 precision | 70/135 | 51.85% | 59/126 | 46.83% | 30.03% | **NO** |
| D1 coverage | 95/189 | 50.26% | 84/176 | 47.73% | 42.00% | **NO** |

- R29.3 H4 precision SELL estimated net **+$0.9943/oz**, but direction accuracy only **52.83%**. Different objective; still **not** a qualifying directional model.
- R29.3 D1 precision SELL net **+$3.4019/oz**, but SELL accuracy only **46.83%**. This is not a >60%-accuracy strategy.
- On the stated objective, **R29.3 did not improve H4 BUY or produce complete H1/H4/D1 60% BUY+SELL**. **Do not promote R29.3.**

## Research selection and next gate

**Keep** R29.2 H4 BUY precision **only as a frozen research reference**, with immutable artifact hash, annual policy, and honest caveats. Do NOT merge it into ForexScanner SHADOW until a reproducible frozen model can be inferred on live broker data and evaluated on prospectively arriving, never-retuned H4 candles.

**Reject** R29.2 H1/D1 variants and R29.3 as promotions. Earlier R29.1 H4 BUY `199/332=59.94%` remains useful as a *higher-coverage baseline*, but 2026 n13 and negative net estimated expectancy.

The next genuinely informative experiment is a **prospective side-specific forward test** plus verified point-in-time macro alignment for D1; retuning more configurations to 2024–2026 increases multiple-testing risk. An isolated forward collector should pin all model weights/feature schemas/thresholds before the new H4 signal and then score predictions only when the next H4 candle closes. Record yearly/sliding precision, n, Wilson lower bound, support, cost-adjusted return, adverse tails, MFE/MAE, and drift. Stop or review if the forward behavior deteriorates. Future precision **above 60% is an objective, not a guaranteed outcome**.

### Safety and scope
- No policy relaxation to force BUY/SELL. No synthetic forecast during WAIT.
- Direction win rate differs from order-fill profitability. Cost scenario $0.70/oz is not measured FP Markets spread/slippage.
- Source R10/R9.8 historical prices are not a verified executable FP Markets feed.
- Frozen V1, broker cBot, strategy configuration, and ForexScanner main branch **unchanged** by R29.2 and R29.3.
