# RIZAN Snowball S9 — Incremental Profitable Basket / Add-on Alpha Research

**Reprioritized 22 Nov 2026 WIB. GitHub research only, no LIVE authority.**

## User mandate

1. Do **not** spend the main research budget on accelerating bootstrap $100→$125. Keep the Frozen V1 seed unchanged until an exact native alternative is proved.
2. Primary objective: Find profitable **additional filled baskets** in the GROWTH regime (after Frozen V1 graduation). The add-on can use XAUUSD, EURUSD and/or BTCUSD, independently BUY/SELL, where source provenance and broker contract allow.
3. Add-on returns then compound naturally through the SAME portfolio wallet in a native replay; never "compound" independent normalized-R winners by multiplication, and never simply increase lot size or leverage.
4. Core Frozen V1 always has priority, including entries in the future that may conflict with an already-open add-on. Conflicts must be recorded, not optimistically erased using future hindsight.
5. Preserve original planned portfolio risk ceiling 20.75%, margin 50%, actual minimum lot/step/commission/slippage, the same A/B intrabar paths and calendar windows. Quantify correlation/exposure overlap and conservative liquidity slippage at large compounded balances.

## Historical native read-only evidence: 87 replays and 20 policies

Source archive `RIZAN_XAU_SMALL_GROWTH_RESEARCH_20261114.zip` SHA256 `eef9a831b50776d362e4ba4e2dda28fac20a84b20b5785b58a27fa17d7745318`. Internal `xau_growth_research/ALL_CASES.json` SHA256 `73001ce51805ce22200419e90020c78fabd8242d61d90e3c39c98ac2bd939572`. Original work includes 87 native model cases using M1 synthetic paths, 20 XAU add-on parameter configurations with matched four annual reset years 2020, 2021, 2025, 2026 (base cost B), but no proof of full continuous model terminal improvement or broker tick execution.

| Strict observation | Policies |
| --- | ---: |
| Additional basket count increased in **all four** reset years | 8 / 20 |
| Ending model balance increased in **all four** reset years | **0 / 20** |
| Ending model balance improved in **three of four** years | 1 / 20 |
| Worst annual model equity DD exceeded 60% | **15 / 20** |

**Strong counterexamples:**
- `late13`: extra baskets +31 / +45 / +9 / +62 in 2020 / 2021 / 2025 / 2026; ending balance multipliers vs core 0.6937 / 0.6284 / 0.5560 / **14.2681**. Profitable 2026 alone fails robustness.
- `late21`: baskets +12/+52/+68/+15, balance multipliers **1.2369** / 0.5401 / **2.6724** / 0.9239. Two better years, two worse.
- `base13_r4`: better balance 3/4 but 2021 only **0.3018×** baseline and max equity DD **62.273%**.

Historical evidence normalized into `research/RIZAN_ADDON_ALPHA_S9_NATIVE_ARCHIVE_EVIDENCE.json`. GitHub read-only audit and fail-closed core/add-on event scheduler: `scripts/snowball_s9_addon_alpha_gate.py`; workflow `.github/workflows/snowball_s9_addon_alpha_audit.yml`; run https://github.com/rizanrizan93/Forex-scanner/actions/runs/45028425001 .

## Research grid to run next (new hypotheses, not S5–S8 repeats)

Different independent families, then test in exact core-native wallet:

| Candidate family | ADD-ON trigger, causal | Why distinct / risk to measure |
| --- | --- | --- |
| A1 post-trend pullback | H4 trend and first M15 retrace after completed trend impulse; M5 close recovery and ATR spread gate | Intended to fill between scheduled Frozen baskets, not blind breakout |
| A2 opening-range retest | London/NY opening range marked only after it closes; first retest and same-side close | Avoids repeated breakout signals and opening volatility noise |
| A3 cross-asset regime | XAU trade in DXY/US2Y real-time-vintage-confirmed regime; block during unverified macro | Macro data time alignment and survivorship bias decisive |
| A4 winner-only pyramid | Add a child only after existing Frozen core basket exceeds a realized-intra-position +R threshold, with unused risk budget | Must re-simulate core exits; does not assume profit simply by splitting |
| A5 event-reaction continuation | News event timestamp verified before decision, displacement, limited trading horizon | Spread expansion, latency and costly stop-outs |
| A6 BTC H4 pullback | BTC H4 trend and H1 reclaim, no weekend execution unless actual broker rules allow | Funding/basis, venue discrepancy, correlated equity risk |

Setup directions BUY/SELL and volatility regimes independently. Choose SMALL preregistered grids per family, not hundreds of near-identical knobs selected after seeing outcomes.

## Native integration gate (must pass before reporting balance alpha)

- [ ] Immutable Frozen V1 cBot compiled and exercised on original matched M1 source SHA EUR `710f10ed...`, XAU `defcbd64...`, BTC `92573326...` and original accounting/fees; reproduce all annual reset baselines plus one **continuous** 2019–13 Nov2026 model wallet before adding trades.
- [ ] Provide trade-level CORE and ADDON ledgers with entry/exit UTC, symbol, planned risk USD, margin USD, cash/equity path, fill acceptance/rejects, position overlap, core-first precedence, and comparable 1×/2× cost paths.
- [ ] Record incremental *filled* baskets, incremental winners and losers, add-on net P&L and PF, loss of any core fills, max floating equity DD, worst-year and 2024/A stress performance, and final continuous balance.
- [ ] Do not count simulated child orders as independent baskets; require actual independently risked opportunities and costs.
- [ ] Use 2012–2018 as economic-regime robustness for instruments with coverage; 2019–2022 development, 2023–2025 evaluation, 2026 explicitly partial and already researched (not untouched holdout).
- [ ] Admissibility: add-on mean net >0 after full 2× cost replay; annual stability, stress PF >1, no unauthorized core displacement, and max floating DD not materially above V1 benchmark; no increases in total combined planned risk.
- [ ] Only after these gates may claim increased compounding. Frozen model terminal $1,662,133,293.08 and 56.67% equity DD are not realizable capacity forecasts; $10B aspirational target remains unproved.

## Gate limitations

`snowball_s9_addon_alpha_gate.py` can test chronological ENTRY/EXIT and fixed-source risk/margin conflicts, but a CSV containing precomputed net profits does **not** reproduce native volume compounding, open-position floating DD, broker execution, or core reactions. Its returned overlay cash and settled DD are **diagnostics only**, never a new V1 balance or approval. The GitHub CI selftest uses synthetic fixtures solely to prove that future core collisions cannot be hidden.

**Operational decision:** leave original Frozen V1 and all LIVE cBots, bridge, FP Markets, BTC weekend rules, BUY050, ForexScanner untouched. Continue research through existing hourly automation `6afd29ec872081919c4acd36cb61842b`.
