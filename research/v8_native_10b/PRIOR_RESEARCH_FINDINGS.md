# Prior evidence used by V8

The named V5 lock, V6 protocol, adapters, profiles, search-space generator and
four audit documents were read from the V5 branch. The Work R1 report, profiles,
accounting/attribution audits, source manifest and patched source were recovered
locally. Exact original Git blobs for all 34 native files match commit 26bf8396.

Important exclusions and controls:

* V5 USD2.091130955 billion is fixed-ledger sensitivity. Closed DD 52.7635%
  and the conditional late-hourly 55.2197% calculation are not challenger
  floating DD. Preserve that lock as a reference until native replay finishes.
* R1's highest B1 balance below 60% DD is BTC BUY18R/72h with EarlyMask5:
  USD1.838731374 billion /58.908457%. It needs its own paired A1/A2/B2 controls.
* Adding RSI80 to that case increases B1 cash to USD1.867121355 billion but
  DD60.386930% rejects it. Its prior A1/A2/B2 DD also exceeds 60%; no promotion.
* All-assets compression added 25 BTC-family baskets, displaced 3 core entry
  keys and changed ending cash by USD2.730709 million relative to its actual
  all-assets comparator. It cannot be added arithmetically to the best case.
* R15 PDS raised B1 cash to USD1.671468105 billion, DD56.758703%, with 15
  additional baskets and all 1047 original entry keys retained. Native paired
  replay of this component remains the appropriate combination test.
* R15 local native terminal report contains an independently validated history
  index preserving complete Ledger, OrderLedger, CashLedger and EquityCurve.
  V8 reuses the same insertion-order label/basket indexing principle and runs
  current-engine parity after wiring the V5 early-sizing policy.
* R15 four-loss/24h guard adds only USD1.304692 million /0.078495% in B1;
  it is not a USD10 billion result or proof of OOS robustness.
* The broad XAU M15 breakout add-on already failed: USD1.085989938 billion,
  DD61.190915%, 157 additional entries and 32 missing original core entries.
  Do not repeat that broad setup as if it were an untested profitable family.
* R16 preregistered H1/H4-aligned Q_ALL and Q_ASIA filters. Its first-case
  diagnostic lists three missing core keys and early losing add-on entries.
  That diagnostic is not a full terminal result; no final balance is inferred.
* The inherited 2012 start produced no pre-2019 trades. Do not label that as
  2012-2018 strategy validation. BTC valid input starts in January2019.

Baseline observed open risk27.209882% and margin54.073858% already exceed the
20.75% /50% planned entry limits. Preserve the observation and investigate
equity deterioration/overlap rather than claiming planned caps enforce the
observed ratios. Market impact and real broker capacity remain unvalidated.

References: research/v5_native_growth/ on research/v5-native-growth-optimization-20261124;
research/frozen_v1_10b_20261124/ on research/frozen-v1-10b-eur-btc-20261124;
research/RIZAN_R15_NATIVE_TERMINAL_RESULTS_20261123.md on research/r15-local-native-terminal;
research/r15_frozen_shared_replay/PROTOCOL.md on research/r15-frozen-v1-shared-replay;
research/r16_no_pause/PROTOCOL.md and first_case_diagnostic.json on research/r16-no-pause-quality-entry.
