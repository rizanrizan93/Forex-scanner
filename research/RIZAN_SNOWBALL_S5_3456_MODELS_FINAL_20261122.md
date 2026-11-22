# RIZAN Snowball S5 — 3,456 EURUSD model parameter configurations (REJECT)

Date: 2026-11-22 (WIB). **Research-only.** No live trading, cBots, broker bridge, Frozen V1 code, BUY050, or real orders modified.

## Purpose and design

- Objective in the user portfolio research: tier progression $100→$125→$250→$1,000→$10,000,000,000 with controlled equity DD, preserving Frozen Bootstrap125 V1 as the frozen control.
- S5 is **NOT** a matched Frozen V1 portfolio replay. It is a causal, independent signal screen on alternative public FXCM EURUSD bid/ask M1 (provider USD session, different from FP Markets/cTrader and from exact S4 Frozen input SHA).
- 12 pattern families, 2 BUY/SELL sides, 2 lookbacks, 3 H4 regimes, 3 sessions, 2 horizons, 2 stop multipliers, 2 TP multipliers = **3,456 configurations**. Outcomes grouped across 14 annual years 2012–2025 = **48,384 model-year evaluations**, including repeated parameter aliases.
- Execution simulated at next M1 open after fully closed M5, H4 only completed bars, stop first if within-minute ambiguity. Stated illustrative minimum EUR 1,000 units, US$100 test equity, 1:200 margin and 8% planned seed risk. Source bid/ask plus hypothetical .00001 slippage each side and .00006 round-trip commission price-equivalent. **2x stress was NOT tested in S5**.
- Individual signal net R; not the native Frozen V1 $100-to-$10B shared-account basket result, nor a certified broker fill simulation.

## Verified outcomes

- Training 2012–2018: 3,244 of the 3,456 configurations had >=200 signal entries. Only **4** had mean net R >0, but **none** met preregistered combined gates: >=200 trades, mean R >+0.04, PF >=1.12 and >=5 positive annual subperiods.
- Training qualified: **0**. Validation 2019–2022 qualified: **0**. Retrospective 2023–2025 qualified: **0**.
- Forensic audit: **2,736** unique full 2012–2025 annual score-vector fingerprints, **720** parameter configurations with duplicate annual result traces.
- Strongest training mean among N>=200: SWEEP_MSS SELL LB36 ANY H4, EUR_CORE_WIB, H60 SL1.5 TP2.5:
  - 2012–2018: N237, avg +0.03865R, PF1.0720, only 2/7 positive annual subperiods.
  - 2019–2022: N213, avg −0.14973R, PF0.7560, 0/4 positive years.
  - 2023–2025 partial source: N197, avg −0.13470R, PF0.7915, 0/3 positive years.
- Source strict full-calendar coverage: **2012–2022**. Partial/holey source years: **2023** (a header-only gzip week27, censored), **2024** (some internal weeks and year-end missing), **2025** (two consecutive internal weeks missing). No FXCM 2026 M1 archive available on initial provider probe.
- P0: **Do not promote S5** or infer additional profitable baskets, reduced drawdown, earlier Frozen handoff, or increased $1.662B model balance.

## Reproducibility

- Script: `scripts/snowball_s5_fxcm_grid.py`.
- Forensic script: `scripts/snowball_s5_forensic_audit.py`.
- Pilot success: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45024544248
- Annual screening 13/14 pass, 2023 empty valid-gzip week: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45024655030
- Repaired 2023 and **successful full 2012–2025 aggregate**: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45024843870
- **Successful forensic/source-quality audit**: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45025011535
- 14 annual source-specific SHA256 fingerprints and 3,456 model-year per-annual result rows are preserved in GitHub Actions artifacts.

## Next independent hypotheses (not yet proven or executed)

1. **Volatility regime transition before entry:** directional signals only after vol contraction→expansion, point-in-time spread bounded, 3-period forward trend confirmation without delayed entry.
2. **Liquidity asymmetry / displacement:** score sweep width, reclaim velocity, prior-session high/low, price efficiency versus churn, avoid high-spread market reopening.
3. **Early account mechanics:** genuine native EUR SELL bootstrap counterpart only when matched cBot baseline/ledger parity reproduced using exact frozen input; avoid the previous 36 rejected S4 candidates and same S5 hyperparameter retuning.
4. **Basket staging:** controlled additions only from unrealized profit/cushion, fixed total planned risk <=20.75%, margin cap50%, cBot priority and minlot; no additional gross risk by merely splitting orders.
5. **Strict replay parity:** original C# Frozen V1 continuous 2019–2026 and 8 annual reset controls, A/B intrabar, base and 2x cost, native order ledger. Extended FX regimes 2012–2018 are prehistory for BTC (BTC dataset starts 2019), so do not treat 2012–2018 as a full three-symbol wallet.

**$10B is a research target, not a achieved balance, probable forecast or certified execution-capacity outcome.**
