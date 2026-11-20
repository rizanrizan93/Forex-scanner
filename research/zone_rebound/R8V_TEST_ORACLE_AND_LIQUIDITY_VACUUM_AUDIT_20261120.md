# R8-V — Test oracle integrity and UTC boundary audit (2026-11-20)

Research-only. No vendor market bytes acquired, no real replay, no accuracy claim.

## Verified repository observation

The current R8-R gate rejects non-finite delays and checks minute alignment, UTC offsets, duplicate order, and lookback continuity. However `test_r8s_causal_window_adversarial.py` still decorates three formerly failing cases with `@unittest.expectedFailure` even though the implementation now handles them. Python unittest reports an **unexpected success** for an expected-failure test that starts passing. In strict CI this can fail the test run, and in dashboards the semantics obscure whether the implementation is fixed. This is a test-oracle maintenance issue, not a trading accuracy improvement.

## New independent audit scenarios (not yet executed)

1. Validate that UTC-offset zero is not sufficient for trusted source provenance: a timezone-aware timestamp may have offset zero but still need source-timezone documentation. Preserve raw timestamp strings and parser version.
2. Explicitly verify 60-minute momentum uses **61** contiguous M1 closes (t and t-60m), as the current gate requires `range(n+1)`. Test 60 vs 61 bars at the availability boundary.
3. Test repeated event IDs and correlated H1/H4 labels in the replay join. A single M5 event must not be counted twice within one side/horizon.
4. Separate `market_age = event - last_bar_close` from `availability_age = event - (last_bar_close + lag)`; pre-register which is used for freshness filtering and report both.
5. For USD direction, use `close[t] / close[t-k] - 1` where both M1 bars have been published as-of the XAU event. Never backfill missing USD bars across gaps.

## Falsifiable prospective hypothesis — liquidity vacuum recovery

On M5 XAU displacement, measure pre-event M1 zero-tick/gap incidence (if real ticks are acquired), wick rejection and the next *completed* M5 retest. Compare reversal/continuation conditional on USD 5/15/60m consensus with R6 baseline, including a no-trade option. If no real tick timestamps, mark vacuum proxy unavailable rather than infer true order flow from OHLC alone. Pre-register development 2019–2023, validation 2024; 2025–2026 descriptive stress only.

## Data acceptance status

DOLLARIDXUSD is advertised by secondary catalogs, not vendor-byte authenticated. No raw 2019 USD sample, HTTP provenance, vendor SHA-256, validated UTC M1 quotes, or joined R6 ledger obtained. BUY/SELL H1/H4 n and accuracy: **not measured**. Target >=60% each side: **not established**. No production, Frozen V1, Manual R3, cBot, bridge, routing or risk changes.
