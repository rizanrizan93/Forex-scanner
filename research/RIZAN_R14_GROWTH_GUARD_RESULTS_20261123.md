# RIZAN R14 — terminal-growth guard research

23 November 2026 WIB. Research only, LIVE and Frozen V1 unchanged.

GitHub run: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45105874974
Experiment commit: `5a8110d120bcdb76e2f6dd697c643f28f3dcf478`.

## Candidate worth a native replay

Per instrument, after **four consecutive losing completed baskets**, pause new entries in that instrument for **24 hours**. Continue exits/protection; no forced close or change in other instruments. Use completed basket settlements, not child-order outcomes, floating losses, date labels or future prices.

18 preregistered related guard policies were computed against four original archived simulated basket streams (4,469 scenario records, not independent actual trades). Two passed development gates2019–2022; one passed retrospective validation gates2023–2025 across incumbentA1/B1/B2. This small screen reused previously observed history and a disclosed BTC-reference normalization fallback, not pristine OOS or statistical proof.

The development-ranked best policy was two losses/24hours per symbol, and **failed validation**. The four-loss survivor is a validation-screen shortlist member, not proof that the original selection rule would have chosen the winner. New forward evidence and native rerun required.

## Size of diagnostic effect

For the four-loss/24h policy, validation additive normalized-return diagnostic:

| Archived scenario | Original baskets | Retained baskets | Relative change in additive normalized score |
|---|---:|---:|---:|
| incumbent_A1 | 421 | 419 | +0.1396% |
| incumbent_B1 | 418 | 416 | +0.1491% |
| incumbent_B2 | 417 | 415 | +0.1109% |

This metric sums original basket PnL divided by its original reference capital (or disclosed baseline settled-cash proxy for missing BTC references). It is **not a portfolio return, a dollar profit change, a terminal balance, or a newly sized compounding replay**. The effect is small and could disappear after native sizing changes. The partial2026 diagnostic is unchanged because the rule removed no baskets in these incumbent streams.

## Uploaded cBot and recovered evidence

Uploaded file is metadata-identified as RizanBuy050Frozen4.0.1.0, net6.0, SHA256 `473507da3166759c418596bfce663b3657e229ca4c205bcb60dbbbe8de84f99c`. File left unchanged, not executed. No binary-to-archive strategy parity is established. Do not equate this BUY050 with Bootstrap125 Frozen V1.

The newly examined13November archive contains incumbent BUY050 historical B1 terminal2,114,543,042.32USD /DD64.4373%, plus a BTC-H1-retest candidate B1 terminal2,031,958,645.02USD /DD65.3412%. These are archived model results, **not new R14 balances**, and the BTC candidate did not improve that incumbent. They are not the Bootstrap1251.662B benchmark. No cross-version balance promotion is justified.

All four archived streams observe peak open risk around24.7% and margin around54%, exceeding planned20.75%/50% caps. These original observations independently block promotion; a newly paused signal stream does not prove revised risk compliance. Full price/equity/volume replay remains required.

## Data and verification

Original archive/derived ledger SHA256 verified. Settlement PnL totals reconcile within0.01USD to archived ending cash. Native summaries and all archived records preserved, not fabricated prices. First CI failed closed because155BTC records per incumbent and341candidate BTC records had zero ReferenceBalance. Before inspecting economic outputs, protocol was amended to retain raw zeros and append the last baseline BalanceAfter recorded at/before entry as a disclosed normalization proxy. This is not exact entry equity and can omit open fees/funding. Missing rows were not deleted. Later CI passes input integrity, settlement-first, future-settlement isolation, prefix invariance, symbol isolation and fallback-denominator chronology tests.

No new native counterfactual wallet was executed. No new final cash, floating DD, incremental native baskets, actual broker capacity or$10B achievement is claimed. No changes to main, LIVE strategy, bridge or checkpoints.

## Concrete next experiment

Use exact native control profile and original corrected three-asset inputs recovered in R12/R13. Reproduce the control ledger, then apply four-loss/24h only to GROWTH entry admission while keeping seed/handoff, lots/leverage, exits and risk/margin caps fixed. Test paired baseline/candidate A/B paths and1×/2× costs, annual resets and continuous2019–13Nov2026, with price-level fills, volume compounding, floating DD and core conflicts recorded. Do not use these fixed historical PnLs to claim a larger balance. Exact inputs/tapes are not yet staged into a GitHub runner, and original Bootstrap125 order/equity reference ledger is still absent; those blockers remain explicit.
