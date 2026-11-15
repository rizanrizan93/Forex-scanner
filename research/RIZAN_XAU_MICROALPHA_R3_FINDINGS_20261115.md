# RIZAN XAU MicroAlpha R3 — Completed Research Findings

**Date**: 2026-11-15. **Status**: `RESEARCH_ONLY / NO_GO_LIVE`.

## User constraints
- XAUUSD, initial USD 100, compounding, reference leverage 1:200.
- Bidirectional BUY/SELL, broker-minimum discrete lot, limit reference margin usage to 50% equity.
- LIVE cBot, frozen V1, bridge, and production ForexScanner must remain untouched.

## Implemented research code
- `src/fx_scanner/xau_microalpha_r3.py` — closed-candle M5 EMA20 reclaim, completed M15 EMA20/EMA50 and H1 EMA50, conservative broker-volume risk checks, read-only V400 macro direction with independent DXY/rates quote freshness.
- `pages/5_XAU_MicroAlpha_R3.py` + XAU navigation in `main.py` — optional historical M5 CSV, replay ledger and shadow macro. Not production or LIVE signal.
- `tests/test_xau_microalpha_r3.py` — tests for no execution, no HTF lookahead, stale macro and risk lock.
- `scripts/research_xau_microalpha_r3_public_pilot.py` — 17,371 M5 bars (2026-02-25 to 2026-05-26).
- `scripts/research_xau_microalpha_r3_multiyear.py` — 497,345 M5 bars (2019-01-01 to **2026-01-09** actual audited endpoint, NOT September 2026).
- `scripts/research_xau_microalpha_r3_lagged_macro.py` — publication-lagged historical real yield, 10Y nominal yield, and broad USD index; broad USD is **not ICE DXY**, this does not validate intraday XAU predictions.

## 90-day pilot (in-sample selected, NOT validated)
At $100, risk max 5%, 1:200, assumed min 0.01 lot and 100oz/lot, a 50% reference margin cap, SL 1 ATR M5 and TP 2R:
- Asia 08:00–13:00 WIB entry: USD 108.98 ending, +8.98%, PF 1.114, 29 trades, approximate OHLC DD 22.21%.
- Split prior to April: negative; after April: improved. **Do not promote based on this pilot**.

## Long-run historical replay (2019-01-01 to 2026-01-09)
These are public mid-price OHLC, not actual broker bid/ask tick, swap or execution:
| Variant | USD100 ending equity | Profit factor | Closed DD | Trades |
|--|--:|--:|--:|--:|
| Asia 0.01-lot, risk5%, 1 ATR | $19.48 | 0.007 | 80.52% | 60 |
| Asia 0.01-lot, risk5%, 0.5 ATR | $17.60 | 0.000 | 82.40% | 53 |
| Asia hypothetical 0.001-lot risk2%, 1 ATR | $4.94 | 0.008 | 95.06% | 255 |
| All sessions, 0.01-lot risk5%, 1 ATR | $18.89 | 0.029 | 81.11% | 65 |

No 2019–2025 complete calendar year in separate $100 restarts with the base Asia strategy generated profit. The *positive early-2026 slice* is partial and not comparable with completed calendar years.

## Macro ablation (same long run)
| Filter | USD100 ending | PF | DD |
|--|--:|--:|--:|
| Technical-only | $19.48 | 0.007 | 80.52% |
| Real yield 10Y + nominal yield 10Y + US broad USD 7d-change signs | $20.26 | 0.030 | 79.74% |
| Real yield 10Y + US broad USD 7d-change signs | $20.13 | 0.030 | 79.87% |

Macro filter reduces some losses but does not make the strategy profitable. Source's advertised publication lags have not been independently as-of-audited; no confidence/probability/alpha claim.

## Broker-specific feasibility constraint
With ASSUMED 0.01 lot minimum = 1 oz, $100 equity, 5% risk cap and $0.80/oz round-trip friction, the maximum stop width before expected friction equals approximately **$4.20/oz**. At 2% risk only $1.20/oz. Those assumptions must be checked on the actual FP Markets cTrader XAUUSD `VolumeInUnitsMin`, `VolumeInUnitsStep`, `LotSize`, initial and maintenance margin, and spread/commission before any executable strategy claims.

## Go/no-go outcome
**NO-GO**: Do not deploy MicroAlpha R3 to LIVE, do not modify frozen V1 or bridge, do not represent the historical CSV signal as real-time. The read-only dashboard is proposed via stacked draft PR #852 above draft PR #851 and is not merged.

## Next research direction
Research a different economically justified source of alpha (M15 liquidity-sweep then M5 confirm, structural liquidity stops, time-dependent market regime, macro yield and DXY changes at original timestamps). Test 2019–2026 native bid/ask ticks where available, original cTrader symbol volume/margin, stress costs and annual walk-forward. Avoid parameter mining. The inability to execute at min lot must result in WAIT/BLOCKED, never override risk.
