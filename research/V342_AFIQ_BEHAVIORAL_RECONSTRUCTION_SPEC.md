# V342 Afiq Behavioral Reconstruction — Research Specification

Status: research-only. No LIVE execution authority. Production V342/V375 remains unchanged until the gates below are satisfied.

## Objective

Reconstruct the observable decision process behind Afiq-style XAUUSD forecasts as a causal, testable engine rather than copying isolated entry prices. The target output is a compact forecast that explains:

1. where price is likely to travel first,
2. what role each nearby zone plays,
3. what liquidity may be swept,
4. what must happen before entry,
5. where the structural destination is,
6. what invalidates the thesis, and
7. which next plan becomes active after failure.

This layer must support DEMO auto-execution only after validation and provide decision support for manual LIVE trading. It must never enable LIVE auto-execution.

## Evidence hierarchy

Use evidence in this order:

1. `USER_CAPTURED_AFIQ_CASES`: timestamped screenshots/messages supplied before the outcome is known.
2. `PUBLIC_AFIQ_ARCHIVE`: timestamped public Afiq forecasts/updates with source URL and capture time.
3. `MARKET_MICROSTRUCTURE_EVIDENCE`: empirical research on support/resistance, stop clustering, order flow, failed breakouts and price discovery.
4. `TRADING_FRAMEWORK_REFERENCES`: Wyckoff, failure-test, auction/market-profile and supply-demand concepts, but only components that can be translated into objective causal rules.
5. Historical market replay.

Marketing claims, testimonials, after-the-fact screenshots and uncited win-rate claims are not calibration evidence.

## Required market ontology

### Regime

Classify the current state before selecting a zone:

- `BALANCE_ROTATION`
- `TREND_EXPANSION_UP`
- `TREND_EXPANSION_DOWN`
- `TRANSITION_UP`
- `TRANSITION_DOWN`
- `CLIMAX_EXHAUSTION_UP`
- `CLIMAX_EXHAUSTION_DOWN`
- `UNKNOWN`

The same supply/demand geometry must not receive the same reversal probability in every regime.

### Zone role

Every visible H4/H1 zone receives one role, not merely SUPPLY/DEMAND:

- `MAIN_REVERSAL`
- `SECONDARY_REACTION`
- `PULLBACK_CONTINUATION`
- `LIQUIDITY_DESTINATION`
- `CONTINUATION_ORIGIN`
- `FAILED_RETIRED`
- `CONTEXT_ONLY`

Role selection must be causal and may change as new completed bars arrive.

### Path states

Canonical decision path:

`HTF_STORY -> REGIME -> EXPECTED_PATH -> ZONE_ROLE -> LIQUIDITY_TEST -> ACCEPTANCE_REJECTION -> M30_STRUCTURE -> M15_CONFIRMATION -> M5_REFINEMENT -> ENTRY -> STRUCTURAL_DESTINATION -> RESPONSE_VALIDATION -> NEXT_PLAN`

## Zone importance model

The existing V342 causal base/displacement detector is retained. Rank each active zone with measurable features:

- H4 vs H1 parentage
- structural BOS
- departure range / ATR
- departure body fraction
- base range / ATR and base compression
- freshness / touch count / mitigation depth
- distance to current price / ATR
- structural room to opposing S/R and opposing H1/H4 S/D
- proximity to prior-day / prior-week extremes
- nearby swing/equal-high/equal-low liquidity cluster
- regime alignment
- rejection/acceptance history on earlier touches
- whether the zone is nested in a higher-timeframe zone

Do not treat raw proximity as sufficient to make a zone PRIMARY.

## Liquidity model

Liquidity is a hypothesis, not proof of hidden orders. Map:

- confirmed swing highs/lows
- equal/clustered highs and lows
- prior-day high/low
- prior-week high/low
- session extremes when available
- round numbers as low-confidence hypotheses only

For LONG reversal candidates, relevant sweep side is sell-side liquidity below/inside demand. For SHORT, buy-side liquidity above/inside supply.

A sweep requires more than penetration. At minimum record:

- level crossed,
- penetration depth / ATR,
- time outside level,
- close location,
- reclaim status,
- subsequent displacement.

## Acceptance vs rejection

Replace binary `distal crossed = failed` thinking with a causal auction test.

### Rejection evidence

Examples of measurable rejection features:

- brief penetration followed by close back inside zone,
- low dwell time beyond distal,
- rapid return through proximal boundary,
- large excursion with small number of closes outside,
- subsequent displacement away from zone.

### Acceptance evidence

Examples of measurable acceptance features:

- repeated completed closes beyond distal,
- increasing dwell time outside zone,
- repeated retests from the other side,
- value/median price migrating beyond the zone,
- continuation displacement after the breach.

V342's existing M15 quarantine remains a safety input but becomes one component of the acceptance model rather than the whole concept.

## Wyckoff / failure-test translation

Use only objective equivalents:

- `SPRING_LIKE`: sell-side break + reclaim + bullish response
- `UPTHRUST_LIKE`: buy-side break + reclaim + bearish response
- `TEST`: revisit with reduced adverse progress and no renewed break
- `SOS_LIKE`: bullish displacement/structure break after spring/reclaim
- `SOW_LIKE`: bearish displacement/structure break after upthrust/reclaim

Do not encode narratives about intentional stop hunting as facts.

## M30 behavioral layer

M30 is promoted from diagnostic-only to a candidate decision layer only after replay proves incremental value.

Candidate M30 features:

- internal range high/low
- close-based internal break
- failed internal break
- HH/HL or LL/LH transition
- close location within candle/range
- displacement / ATR
- relationship to H4/H1 zone and expected path

M30 does not override HTF context by itself.

## M15 confirmation

M15 decides whether the forecasted zone is beginning to behave as expected:

- sweep/reclaim
- rejection close
- engulfing only when contextual and non-lookahead
- displacement
- local market-structure shift
- failed breakout / failure test

The engine must distinguish `REACTION_SEEN` from `REVERSAL_CONFIRMED`.

## M5 refinement

M5 is for timing and pocket refinement, not directional authority.

Possible outputs:

- `M5_POCKET`
- `M5_REFINED_POCKET`
- `WAIT_RETEST`
- `NO_CHASE`

Structural SL remains anchored to invalidation; M5 precision must not create an artificially narrow stop.

## Response timer

A major addition prompted by the poor V374/V375 early-reaction results.

After a causal early reaction, define the expected follow-through window in completed M5/M15 bars. Measure:

- favorable excursion / ATR,
- adverse excursion / ATR,
- displacement,
- structure break,
- return into the zone,
- dwell time.

Candidate states:

- `FOLLOW_THROUGH_CONFIRMED`
- `FOLLOW_THROUGH_WEAK`
- `REACTION_STALLED`
- `REACTION_FAILED`
- `MOVE_MISSED_NO_CHASE`

Do not allow an early reaction thesis to remain valid indefinitely.

## Structural target hierarchy

TP is determined by market structure, not manufactured to satisfy a fixed RR.

Directional target hierarchy:

1. nearest valid S/R or liquidity objective,
2. opposing H1 supply/demand,
3. opposing H4 supply/demand if the path remains open.

Front-run exact structural levels by a small volatility/spread-aware buffer. RR remains a quality/admission statistic; it does not move the target through a known roadblock.

## Macro / event layer

Treat scheduled high-impact news as a state transition risk, not as an automatic directional predictor.

Research features:

- minutes to/from event,
- event class (NFP, CPI, PCE, FOMC, GDP, etc.),
- pre-event compression/expansion,
- immediate post-event range / ATR,
- yields / USD confirmation when point-in-time data are available.

The initial behavioral replay may use event-risk timing without historical survey-surprise reconstruction. Any missing historical macro field must be explicitly labelled unavailable rather than backfilled with revised information.

## Cross-market evidence

Gold futures can contribute to price discovery, so COMEX GC is a desirable secondary evidence source for volume/order-flow validation. It must not be assumed to lead at every time; leadership is time-varying.

Potential live/recent features when reliable data are available:

- GC volume impulse
- bid/ask or order-flow imbalance
- price progress per unit of volume/flow (`EFFORT_RESULT`)
- spot-vs-futures divergence/reconvergence

Historical full-depth order-book data may require a licensed vendor. The core engine must remain functional without it.

## Data requirements

### Sufficient now for first-stage research

- current V342 code and causal H4/H1 history
- public XAUUSD M1 history
- public Afiq archive examples
- user-supplied Afiq screenshots

### Needed for stronger validation

- timestamped Afiq cases including failures/no-trades
- XAUUSD bid/ask tick history for realistic fill/spread sequencing
- reliable scheduled-event timestamps
- point-in-time yield/USD series for macro context
- optional GC futures trade/volume/order-book data

## Behavioral fidelity metrics

Do not use trading P&L alone to decide whether the reconstruction matches Afiq.

Measure:

- `zone_selection_exact_rate`
- `zone_overlap_rate`
- `zone_role_agreement`
- `direction_agreement`
- `expected_path_agreement`
- `liquidity_side_agreement`
- `confirmation_delay_minutes`
- `entry_error_atr` and entry error in XAU points
- `target_role_agreement`
- `no_trade_agreement`
- `plan_b_agreement`

## Trading metrics

After behavioral fidelity is acceptable, evaluate:

- trade count
- win rate
- profit factor
- expectancy R
- net R
- max drawdown R
- consecutive losses
- MAE/MFE
- hold time
- results by LONG/SHORT
- results by regime
- results by zone role
- results by confirmation tier
- results around vs away from news

## Promotion gates

A research layer may influence DEMO only after all of the following:

1. no-lookahead/causality tests pass,
2. behavior replay shows incremental fidelity vs current V342,
3. historical results are robust across multiple years/regimes,
4. recent holdout results do not collapse,
5. spread/slippage sensitivity remains acceptable,
6. no single regime/year contributes all profit,
7. dashboard exposes the reason for every WAIT/READY/BLOCK/FAILED state.

No research result can enable LIVE auto-execution. LIVE remains manual decision support.

## Research references / rationale

- Carol L. Osler, *Currency Orders and Exchange Rate Dynamics* (Journal of Finance / NY Fed Staff Report): stop-loss and take-profit orders cluster around predictable levels and breakouts can accelerate after clustered stops are crossed.
- Rama Cont, Arseniy Kukanov, Sasha Stoikov, *The Price Impact of Order Book Events* (Journal of Financial Econometrics): short-horizon price changes are strongly related to order-flow imbalance and market depth.
- Wyckoff methodology references (StockCharts): spring/upthrust/test and effort-versus-result provide an objective template for sweep/reclaim and absorption-like behavior.
- Adam Grimes, Failure Test: failed breaks of pivots can provide reversal information when context and follow-through are present.
- Empirical HSAR literature: horizontal support/resistance can have predictive structure, but a level alone is not sufficient evidence of excess returns.
- Intraday gold price-discovery literature (Hauptfleisch et al.; Sehgal/Sobti/Diesting): New York futures often contribute strongly to gold price discovery, but leadership is time-varying.
- Gold macro-announcement literature: NFP, CPI, GDP, employment and monetary-policy surprises materially affect intraday gold returns/volatility; event state must therefore be explicit.

## Immediate experiment sequence

1. Finish current V342 Afiq behavioral replay for 2025–2026.
2. Build a labeled Afiq case ledger from public archive + user screenshots.
3. Add research-only `ZONE_ROLE`, `ACCEPTANCE_REJECTION`, `M30_INTERNAL`, and `RESPONSE_TIMER` features.
4. Replay each feature incrementally; do not merge all changes at once.
5. Move from M1 OHLC to bid/ask tick replay for finalists.
6. Compare baseline V342 vs each incremental layer on both behavioral fidelity and P&L robustness.
7. Promote only the layers that add stable evidence.
