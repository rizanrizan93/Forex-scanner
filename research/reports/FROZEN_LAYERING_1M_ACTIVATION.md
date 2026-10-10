# User-frozen XAU/EUR layering activation

User authorization: 10 October 2026, explicit request to freeze both joint-improvement candidates and update the scanner directly.

| Pair | Frozen config | Depths toward original SL | Initial fraction | Equity capacity | Add TTL |
|---|---:|---|---:|---:|---:|
| XAUUSD | 310303 | 0.325R / 0.650R | 0.8 | 1.5× bounded baseline count | 15 minutes |
| EURUSD | 572811 | 0.134715R / 0.190516R / 0.233333R | 0.8 | 0.75× bounded baseline count | 120 minutes |

Signals, original absolute SL/TP, virtual EUR feedback and risk/margin ceilings are retained. New baskets calculate initial quantities from compounded balance/equity and broker expected margin. Limits carry the same absolute SL/TP and server expiry. Pending attempts are durably reserved before submit and uncertain outcomes quarantine further submissions. Native limits are never blindly resubmitted after restart. Pending orders cancel if the parent is flat, geometry invalidates, equity no longer supports the reserved budget, or TTL expires. Cancellation/fill races close orphan strategy positions rather than starting a new basket. Existing legacy positions retain their original expiry and protection management; active state is not reset.

Forward quantities are intentionally bounded by broker leverage/margin and conservatively reserved margin at the basket stop. Pending quantities are fixed when placed; future baskets recompound. Forward fills/quantities are not promised to reproduce the synthetic OHLC research. XAU retains 12.5% total planned risk / 50% margin; EUR retains 27.25% / 60% times its frozen feedback multiplier and hard child cap. Only DEMO workflows carry order authority. No LIVE activation is included.

The selected evidence is posthoc 2016–2025, $100 once: XAU $15,418.41 / DD M1 45.22%, EUR $12,107.13 / DD M1 34.79%. XAU cost×1.5 and EUR cost×3/opportunity removal erase balance advantages. The user explicitly authorized freezing despite these limitations; historical DD is not a forward cap. The higher-DD XAU #167432 is not activated.

The JSON manifests include immutable configuration hashes and baseline/selected metrics. Both pair dashboards show frozen depths, live plan prices, active children, queued limits and configuration downloads. Runtime heartbeats advertise a separate layering policy identity while preserving the baseline signal policy identity and existing worker/position labels. This allows old active positions and historical telemetry to remain recognizable.
