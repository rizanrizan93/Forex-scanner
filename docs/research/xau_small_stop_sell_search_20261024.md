# XAU — smaller stops, separate SELL search and prealerts

24 October 2026. Retrospective research; raw data ends 31 March 2026.

## Result

The original TP25/SL50 setup achieved a high hit rate partly with a stop twice the target. The new SL15 impulse candidate looked strong in 2023–2025 (PF 2.429, full TP 60%, 40 trades), but Q1 2026 deteriorated to PF 0.409 and 20% full TP across 15 trades. It is rejected as the dashboard prealert candidate.

The selected post-hoc research alternative is BUY FVG M15, H1/H4 alignment and expanding H4 volatility, distal entry, TTL4h, SL20/TP25, all hours, time exit240h.

| Period | n | Net win % | Full TP % | PF |
|---|---:|---:|---:|---:|
| 2019–2022 train | 70 | 60.00 | 55.71 | 1.836 |
| 2023–2025 review | 57 | 59.65 | 59.65 | 1.804 |
| 2026 Q1 diagnostic | 19 | 57.89 | 57.89 | 1.690 |
| All trades | 150 | 59.33 | 57.33 | 1.783 |

Review cost2: 55 trades, PF1.672, full TP58.18%. Independent NumPy reconstruction confirms all outcomes. The sample is small and the selection uses previously seen review and diagnostic periods. It is not independent validation.

## Search and SELL

This turn: 379,392 smaller-stop scenarios, 259,584 extra countertrend profiles, 718,848 SELL session scenarios, and 193,536 M5 SELL scenarios: 1,551,360 correlated parameter/cost scenarios. Initial H1/M15/H4 source has 211,688 zones; additional M5 generation has 308,069 zones. Stops tested5/7.5/10/12.5/15/20 with fixed TP25; separate BUY/SELL, deeper entries, multiple expiries/sessions, closed HTF features.

No SELL candidate passes the declared sample/PF/win gates in these searches. The UI therefore explicitly says SELL has not passed rather than mirroring a BUY-only winning rule. This does not establish that a profitable SELL algorithm cannot exist. It is a result limited to this search space and tape.

Primary search gates were train n>=60, review n>=30, net win>=55%, full TP>=50%, PF>=1.5 in both periods, review cost2 PF>=1.2, censoring<=2%. These lower hit-rate gates were declared at the beginning of the smaller-stop search; they differ from the earlier wide-stop 60% TP gate.

## Delay / early-warning contract

Strict delayed publication rejects a candidate if its first touch already occurred before the delay; it never credits a later retouch as an initial fill.

| Delay | Review n | Review full TP% | Review PF | Q1 n | Q1 PF |
|---|---:|---:|---:|---:|---:|
| fvg20_cost1 | 57 | 59.65 | 1.804 | 19 | 1.690 |
| fvg20_cost2 | 55 | 58.18 | 1.672 | 19 | 1.665 |
| fvg20_delay60 | 57 | 59.65 | 1.804 | 18 | 1.538 |
| fvg20_delay300 | 54 | 57.41 | 1.645 | 17 | 1.384 |

The read-only collector now targets60s, while the UI redraws10s. Long collection/publishing can still exceed60s; there is no guarantee every first touch is caught. Geometry and producer preparation time are retained; the consumer also records its own first-presentation time. Already-touched plans are missed/observed history, never fresh entry. Quotes older than90s or incomplete M1 touch coverage hide actionable prices. Pending expiry is recomputed on every render. Source cutoff excludes bars still forming when collected, even if processing takes longer.

No new order, position, token or bridge request is added. Existing request allowlist is byte-semantically unchanged. Only research collector cadence, optional snapshot fields, UI and related tests are changed. Backtest/native-feed parity remains unverified.

## Validation

80 targeted tests pass (new guards, V05 regression, feed loop, market-data reader, UI). Three obsolete existing assertions were updated: two omitted the historical tick request already present in the unmodified reader, and one expected an old default manual tab. Both failure types were reproduced on the untouched parent commit. No broker protocol was broadened.

Source SHA256: 967a84f61e248143d1dd3d92db132e137441d30445a236827d9b6579593e262b. BID M1 plus average-spread ask proxy; stop first, no TP credit fill minute; adverse gaps; 0.17 USD/oz fee/slippage proxy and adverse0.10 USD/oz/calendar-day carry; cost2 refills; one position FIFO; no layering/compounding/account sizing. Gaps>72h censored and warm-up24,000 M1 observations. All data have been observed previously; no new holdout is claimed.
