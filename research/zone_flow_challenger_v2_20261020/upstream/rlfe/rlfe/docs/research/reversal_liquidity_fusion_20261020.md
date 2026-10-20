# RIZAN Reversal Liquidity Fusion Engine — research design v1 (20 Oct 2026)

**Status: EXPERIMENTAL / READ-ONLY / NOT DEPLOYED.** This is a proposal and prototype scoring contract, **not an operational Bookmap feed**, not a validated edge, not a trade entry trigger, and not permission to operate cBots. No cBot, bridge, risk, strategy or portfolio state should be altered by this module.

## Existing baseline and reason

`manual_reversal_map.py` currently generates H1/H2/H4 base-displacement zone candidates, with H12/D1/W1 as context, M15 reclaim and subsequent M5 local structure break. The Candidate A research branch requires first touch <=12h, M5 confirmation <=30m, opposite D1 EMA20/EMA50, and a manual TP 1R reference; this logic stays exactly as-is. Earlier portfolio-independent research: Candidate A validation PF ≈1.338 on an overlapping event ledger, about 1.140 one-position; no robust multi-regime improvement established. See `docs/research/manual_xau_confirmed_reversal_pf_2019_2026.md`.

## Hypothesis

Actual venue order flow immediately before and after touching a structurally valid zone may help **rank zone quality and choose an entry timing**, separating absorption/reclaim from liquidity withdrawal and trend continuation. This is *additional evidence*, not proof a line will reverse. Primary target: improve out-of-sample win rate **subject to** stable risk-adjusted PF, sufficient opportunities, and cost-adjusted trade returns. Do not optimize win rate by simply abstaining from all trades.

## Two independent lanes

1. **Structural zones unchanged:** preserve Candidate A first-touch <=12h and the existing WATCH / WAIT semantics. Older HTF zones may use a separate WATCH-HTF diagnostic, requiring a new causal sweep/reclaim sequence; never relabel an old first touch as fresh.
2. **Microstructure overlay (shadow only):** matching price window near the specific zone, record venue, timestamp, bid/ask liquidity, depth persistence/pull, trade delta, directional absorption and post-sweep control flip. Show `SUPPORTIVE`, `MIXED`, `OPPOSING`, `STALE`, or `NO_DATA` and independent *uncalibrated support index*. Do not turn a heuristic index into a calibrated win probability.

## Data-source semantics

- XAUUSD: COMEX GC futures market-depth + executed trades; GC vs XAUUSD CFD levels require a contemporaneous, historical-only basis mapping, roll awareness and residual-error gate. Native cTrader Level II available in `demo_xau_dom_v191.py` is **broker-specific depth**, not COMEX-wide Bookmap and not trade CVD/absorption.
- EURUSD: CME 6E futures; basis/instrument mapping and contract roll handled separately, EURUSD OTC does not have a consolidated central order book.
- BTCUSD: choose an explicit venue and market type (spot vs perpetual); never mix perpetual liquidations with spot fills or claim all crypto venues are covered. A 24/7 exchange feed must not imply FP Markets BTC CFD trades can open on weekends.
- Bookmap desktop add-on APIs, including documented Python add-on examples, provide depth and trade callbacks subject to the required environment; Market Pulse Web API access is separately provisioned. Raw Bookmap figures are not available in this repository merely because an API exists. Real-time CME data licensing and retained historical depth data must be obtained before testing exchange orderflow causally.

## Proposed scoring families (all challenger configurations, not calibrated weights)

- **A / passive absorption:** opposing market orders aggressively hit the level, but price has little adverse progress; subsequent replenishment/persistent depth before M5 reclaim.
- **B / liquidity sweep-and-flip:** visible depth pulls ahead of the sweep, trades accelerate, then executed delta flips and price reclaims; confirmation must be observed *after* the event.
- **C / continuation risk:** strong opposing aggression and persistent depth withdrawal with adverse progress; downgrade zone ranking rather than assume first touch bounce.
- **D / hybrid:** A/B/C plus old HTF structural map, session, volatility and macro *as-of* data. Independent research of weights, no new hard veto unless holdout verifies it.

`reversal_liquidity_fusion.py` is only a small scoring contract for precomputed evidence and still needs a licensed collector/adapter. Example limits such as `mapping_error_atr<=0.20` and `support_index>=60` are provisional, **not optimized nor validated**. No endpoint or token is embedded and no noncausal candle proxy is accepted as Bookmap data.

## Integration plan

1. Store depth updates and executed trade prints with native event timestamps, arrival timestamps, venue and market type; isolate account/trading secrets. Store separately from cBot live state and append-only research snapshots.
2. Map source market to the target CFD using past-only overlapping quotes; record map error and exact contract roll. Deduplicate events; mark dropped packets, stale windows and unavailable trades. In the dashboard, show venue, age, quality and a compact colored-free descriptor next to existing zone WATCH/WAIT; a 60-second page refresh is *not* adequate for a claimed sub-second executable entry.
3. Run frozen zone map independently, then compute per-zone microstructure evidence **after** a real first touch; score all zone candidates softly, retaining unsuppressed candidates. Do not edit `candidate_a_watch`, frozen cBots, or bridge.
4. For research, compare baseline vs four challengers with identical eligible zones, locked risk/TP/SL, one-position ledger and broker spread/commission/slippage. Separate signal detection time from next available execution quote. Include weekends/contract rolls, macro surprise timestamps, blackout windows and connection outages.
5. Validate using walk-forward by calendar years, purge overlapping zones and outcomes, embargo neighboring windows, block-bootstrap by session and correct multiple hypothesis selection. Reserve untouched holdout through newly acquired exchange depth history or forward paper sample. Report PF, win rate, expectancy in R, MFE/MAE, DD, opportunity rate, coverage ratio, calibration reliability and confidence bands by XAU/EUR/BTC. Promote only on measurable net uplift with meaningful trade count and without fragile cost sensitivity.

## Fail-safe contract

`NO_DATA`/`STALE` cannot raise an entry recommendation; `SUPPORTIVE` does not authorize a trade. On price crosswalk or feed failure, keep the structural zone display unchanged and show microstructure unavailable. This module is **not** connected to runtime scripts, dashboard, execution, or cBots; the draft branch must be evaluated before any production wiring.

## Reference material

- Bookmap Java add-on market data callbacks: https://bookmap.com/knowledgebase/es/docs/API-Tutorial
- Bookmap Market Pulse Web API access: https://bookmap.com/knowledgebase/de/docs/Addons-Market-Pulse-Web
- CME historical/real-time order book products: https://www.cmegroup.com/market-data/browse-data/catalog/futures-and-options-data.html


## V2 implementation checkpoint

GitHub draft PR #799 provides an optional read-only dashboard panel and independent sidecar validator. Main is not changed, and no Bookmap data connector, sidecar producer, or historical venue depth dataset has been provisioned. Local portable core contract tests: 10 passed using synthetic samples; not a market replay. See https://github.com/rizanrizan93/Forex-scanner/pull/799.
