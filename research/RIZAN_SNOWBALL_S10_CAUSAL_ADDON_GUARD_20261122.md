# RIZAN S10 — Causal regime shutdown for incremental add-on baskets

Date: 2026-11-22 WIB. Status: **GitHub CI passed**. RESEARCH ONLY, NO LIVE changes.

## New priority

The user reprioritized away from optimizing the low-cash bootstrap: retain Frozen V1, search for high-expectancy ADDITIONAL **FILLED** baskets, and allow verified profits to compound in the original shared-account portfolio. Do not count alerts, split orders, proxy-R or larger lots as new alpha.

## New verified native archive finding

We reconstructed four-year matched results from the immutable historical archive `RIZAN_XAU_SMALL_GROWTH_RESEARCH_20261114.zip` (SHA256 `eef9a831b50776d362e4ba4e2dda28fac20a84b20b5785b58a27fa17d7745318`), per-case JSON SHA256 `73001ce51805ce22200419e90020c78fabd8242d61d90e3c39c98ac2bd939572`:

- 20 XAU add-on policies × annual $100-reset years 2020, 2021, 2025, 2026 (4 per policy); total **87** original native synthetic-M1 cases including baselines and supplementary tests.
- **20/20 add-ons produced lower 2021 annual ending balance than Frozen V1**; even **11/20 added basket fills in 2021 and STILL degraded balance**.
- Median 2021 ending balance ratio was **0.34161× Frozen V1**, a severe regime fragility signal. This is a cross-policy historical summary, not a causal regime identified in real time.
- **8/20** policies added baskets in all four annual years. **0/20** improved ending model balance in all four years.
- Best-sounding single-year add-on returns (e.g. 2026 late13) were offset by worse years. Annual summaries cannot prove per-addon expectancy, margin conflict, continuous-wallet balance or floating equity DD.

Machine-readable per-policy rounded ratios and basket deltas: `research/RIZAN_S10_NATIVE_ADDON_FOUR_YEAR_DEEP_AUDIT.json`. CI reruns integrity and derived statistics. **Never hard-code a 2021 year filter or use hindsight returns to exclude trades.**

## New structural guard (proposed policy, NOT yet validated for alpha)

New Python read-only `scripts/snowball_s10_causal_addon_guard.py` implements:
1. CORE trade entries outrank add-on entries at same timestamp; settlements process first.
2. Add-ons only enter after growth threshold; maximum add-on planned risk **3% of settled cash**.
3. Retain **4% additional unallocated risk** and **10% unallocated margin** below combined caps (20.75% risk, 50% margin) to reduce, not guarantee prevention of future CORE conflicts.
4. After two consecutive realized losing **add-on settlements**, stop new add-ons for 30 days. All state is updated chronologically on settlements only, never from future prices, calendar labels, or unobserved PnL.
5. Later CORE entry conflicts are **not** retroactively erased: count them and reject the candidate. A fixed-PnL overlay cannot re-simulate real core fills or outcomes.

S10 GH Actions run: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45030028397 (**SUCCESS**, unit tests passed and historical archive audit passed). Synthetic unit fixtures confirm chronology, two-loss pause, core-first ties, and detection of later conflicts. **These fixtures are not actual profitable add-on trades or backtests.**

## What is not yet proven

- No real native trade-level add-on ledger on GitHub matched against the exact frozen baseline. Thus no tested effect of cooldown on actual 2020/21/25/26 positions, no verified positive out-of-sample alpha, no verified increment to continuous 2019–2026 compounding, and no validated floating DD.
- Synthetic M1 original macro flags not vintage certified and actual FP Markets minimum lot, contract multiplier, margin tiers and fill/impact remain unverified.
- Later portfolio-capacity collision cannot be guaranteed absent by only reserving 4% risk/10% margin; when it occurs, reject candidate.

## Required next experiment

Obtain exact original C# native replay core and immutable restored three-asset M1 inputs (EUR SHA `710f10ed97e709f48e284e79511981e4e85638deca6958a668908d6f418285c5`, XAU SHA `defcbd64ab625156f7594f8a357591bc3d2fea2a0e8deb4c9144ae88e4e8fea7`, BTC SHA `9257332636450a0c93d20c45757016ae359feb208d7b91ac82fac173a64f8c51`). Verify precise baseline trading ledger parity *before* injecting candidate add-on signals into the same wallet.

Evaluate causal S10 loss-streak guard as a **pre-registered** overlay paired with no-cooldown policy, both on native paths A and B, costs 1×/2×, annual resets plus continuous 2019–2026. Output additional **profitable filled** baskets, net PnL after all fees, PF, worst annual loss, core displacement, max floating equity drawdown, capacity rejects, and terminal balance, without increasing risks.

Do not resume S5–S8 losing grids unchanged, do not promote S10 just because unit tests pass, and never modify LIVE cBots or main. The user's aspiration of $10B remains unproven.

## Technical blocker audit of the original native source archive (reviewed 2026-11-22)

The original 14 Nov XAU add-on C# research source `xau_growth_addon/native_replay/Replay.cs` is indeed present in the Library ZIP, alongside `XauAddonController.cs` and `NovemberReplay.csproj`. The source expects runtime environment data references including `SEED_DATA` directory with `base{Base}_symbol{sid}.bin` precomputed signal tapes (40-byte records), `BTC_INPUT`, `RESEARCH_CONFIGS`, `MACRO_DATA`, and multi-asset OHLC CSV paths passed as runner arguments. The small native source ZIP contains the C# code and output summaries, **NOT** the referenced multi-year binary signal tapes or full vintage-certified macro input. GitHub Actions cannot reproduce the original add-on ledger from these source files alone, even with .NET installed. Reconstruct and validate original signal tapes and macro point-in-time inputs, then run exact native source with immutable hashes and original 87-case baseline parity; fail closed if input data differs.

The separate Frozen Bootstrap125 V1 release also confirms only research synthetic M1 results, not full three-asset FP Markets tick replay: historical tick availability was incomplete in that audit. No broker tick, genuine continuous wallet or actual account capacity proof arises from S10.
