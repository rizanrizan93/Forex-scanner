# Direct M1 exhaustive execution protocol

The first generic universe's exact same1,000,000 deterministic parameter configurations per instrument will be replayed DIRECTLY on M1, not preselected by coarser OHLC results. The original generic engine, closedM15/H1/H4 signals, source parameters, seed, risk1–20%, margin, leverage, fees and assumptions are unchanged. BTC uses corrected officialAPI input. USDJPY uses the same verified input prices; audit datetime units normalized and pandas pinned2.2.3.

Five interleaved shards run IDs((id-1)%5==shard). Each walks the same deduplicated million-configuration stream but evaluates only200,000 IDs. No independently drawn overlapping samples. Merge all five disjoint ID sets; assert exactly1,000,000 IDs, no duplicate parameter tuples, and all IDs1..1000000. Retest the full1,000,000 on M1 in both continuous2019–2026 and train-only2019–2022. No live operations.

Each shard exports its top20 fullperiod, top20DD50 and top20train-ranked configurations for M1cost/latency/leverage/segment sensitivities. Global top20 in any of these criteria must be included in the union of shard top20s. This ensures global leaders get stress testing. Historical exploratory fullperiod selection remains separate from train-only selection. No assertion of an untouched prospectiveholdout or broker/tickparity.

The directM1 result replaces the coarser screening estimate for the same universe, not an additionalmillion unique strategies. Session and H4/D1 extensions remain distinct declared batches. Report exact counts without adding repeated data/engine reruns as newly unique configurations.
