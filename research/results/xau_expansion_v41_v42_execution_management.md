# XAU Expansion V4.1/V4.2 — Intraday Timing and Profit Protection Evidence

Research only. Production influence and LIVE execution remain disabled.

## Scope and stopping rule

The D1 setup is frozen as `S2R2T2H0`; this study does not re-optimize the D1 signal. cTrader DEMO XAUUSD H1 history is used only to replay execution timing and position management for the already-selected D1 setup. Daily boundaries 00:00, 21:00 and 22:00 UTC are treated as robustness replicas, not independent pooled samples. All stop/target ambiguity is resolved conservatively as stop first. Transaction-cost sensitivity is evaluated at 0.05R, 0.10R and 0.15R per trade.

The broker-history window through 2026-08-31 has now been reused for V4.1/V4.2 research. No further parameter mining on that window is authorized after this evidence freeze. Future promotion evidence must be prospective and temporally untouched.

## V4.1 — H4/H1 timing study

The fixed D1 setup was replayed with five entry modes and two management modes. The most relevant stress-cost 0.10R median metrics across the three daily-boundary replicas are:

| Variant | Median coverage | Median Net R | Median expectancy | Median PF | Robust stress/severe boundaries |
|---|---:|---:|---:|---:|---:|
| OPEN + STATIC | 100.00% | +10.7972R | +0.7807R | 2.8733 | 3/3, 3/3 |
| PB15_24H + STATIC | 78.57% | +8.1936R | +0.7449R | 2.4437 | 3/3, 3/3 |
| PB25_24H + STATIC | 64.29% | +7.8621R | +0.8736R | 2.7817 | 3/3, 3/3 |
| OPEN + CURRENT_RUNTIME_LOCK | 100.00% | +6.5000R | +0.4333R | 5.4815 | 3/3, 3/3 |
| PB25_24H + CURRENT_RUNTIME_LOCK | 64.29% | +5.0678R | +0.5631R | 3.2034 | 3/3, 3/3 |

`PB25_24H + STATIC` increases expectancy per filled trade but sacrifices roughly one third of otherwise valid D1 opportunities. `OPEN + STATIC` keeps full coverage and higher aggregate captured edge.

The H4 EMA20/EMA50 alignment variant was identical to OPEN on every tested boundary. With the already-strict D1 EMA20/50/200 hierarchy, the H4 alignment gate added no incremental selection or timing value in this sample and is therefore not retained as a forward challenger.

The current aggressive runtime profit-lock materially increases PF and reduces drawdown, but gives up too much total edge: median stress Net R falls from +10.7972R to +6.5000R, a retention ratio of about 60%. This motivated a narrowly scoped V4.2 management study rather than additional entry mining.

## V4.2 — profit-protection diagnostic

Entry is fixed to OPEN. Only six predefined management policies are compared. Stop moves are decided from completed H1 closes and apply to the next bar, so the replay does not use intrabar future information. The current runtime ladder is included as a consistency control and reproduces the V4.1 OPEN runtime-lock results exactly; STATIC likewise reproduces V4.1 OPEN STATIC.

Stress-cost 0.10R median results across the three boundary replicas:

| Policy | Median Net R | Median expectancy | Median PF | Median DD proxy | Net retention vs STATIC | Pareto flag |
|---|---:|---:|---:|---:|---:|---|
| STATIC | +10.7972R | +0.7807R | 2.8733 | 0.9383% | 100.00% | control |
| CURRENT_RUNTIME | +6.5000R | +0.4333R | 5.4815 | 0.6246% | 60.20% | no |
| BE100 | +11.4674R | +0.7645R | 4.6272 | 0.5749% | 106.21% | yes |
| BE125 | +11.0609R | +0.8049R | 3.0111 | 0.8075% | 102.44% | yes |
| BE150 | +11.2109R | +0.8164R | 3.0384 | 0.7331% | 103.83% | yes |
| DEFERRED_STEP | +11.4609R | +0.8357R | 3.0838 | 0.6091% | 106.15% | yes |

All non-static candidate policies above remain positive on all three replicas under both 0.10R stress cost and 0.15R severe cost. However, V4.2 was designed after inspecting the earlier H1 replay, so none is promotion-eligible from this evidence alone.

### Cross-boundary comparison: DEFERRED_STEP vs STATIC

`DEFERRED_STEP` is the most balanced management challenger because it improves Net R, expectancy, PF and drawdown versus STATIC on every individual daily-boundary replica, not merely on the median.

At 0.10R cost:

| Boundary | STATIC Net/Exp/PF/DD | DEFERRED_STEP Net/Exp/PF/DD |
|---|---|---|
| 00 UTC | +10.1496 / +0.7807 / 2.7457 / 1.7954% | +10.8637 / +0.8357 / 2.9752 / 1.4442% |
| 21 UTC | +12.1922 / +0.8128 / 3.1153 / 0.6811% | +15.0559 / +1.0037 / 5.5624 / 0.5500% |
| 22 UTC | +10.7972 / +0.7712 / 2.8733 / 0.9383% | +11.4609 / +0.8186 / 3.0838 / 0.6091% |

At 0.15R severe cost the same directional dominance remains:

| Boundary | STATIC Net/Exp/PF/DD | DEFERRED_STEP Net/Exp/PF/DD |
|---|---|---|
| 00 UTC | +9.4996 / +0.7307 / 2.5537 / 1.8940% | +10.2137 / +0.7857 / 2.7763 / 1.5431% |
| 21 UTC | +11.4422 / +0.7628 / 2.8870 / 0.7310% | +14.3059 / +0.9537 / 5.0298 / 0.5750% |
| 22 UTC | +10.0972 / +0.7212 / 2.6652 / 1.0376% | +10.7609 / +0.7686 / 2.8715 / 0.7086% |

The DEFERRED_STEP policy is:

- below +1.25R favorable close: keep structural stop unchanged;
- +1.25R to <+1.75R: lock +0.10R;
- +1.75R to <+2.25R: lock +0.50R;
- +2.25R to <+2.50R: lock +1.00R;
- from +2.50R: trail at approximately favorable-R minus 1.00R;
- every update is based on a completed H1 close and only affects subsequent bars.

`BE100` is an interesting defensive alternative because it produces the highest median PF and lowest median DD, but it reduces Net R versus STATIC on the 21 UTC and 22 UTC replicas. It is therefore not selected as the primary management challenger.

## Frozen prospective challengers

Research mining now stops on the reused 2024-2026 broker window. Exactly three variants are frozen for prospective comparison:

1. `XAU_V4_CONTROL_OPEN_STATIC` — full-coverage control: D1 `S2R2T2H0`, OPEN entry, structural SL/TP, no intraday stop advancement.
2. `XAU_V42_OPEN_DEFERRED_STEP` — primary profit-protection challenger: same entry and D1 geometry, with the DEFERRED_STEP H1-close management policy above.
3. `XAU_V41_PB25_STATIC` — timing challenger: same D1 setup, wait up to 24 hours for a 0.25R adverse pullback from the baseline D1 entry, then use the unchanged structural D1 stop/target; no dynamic profit lock.

No combined `PB25 + DEFERRED_STEP` variant is created now. Combining the two best historical overlays after seeing their results would add another post-hoc degree of freedom and increase overfitting risk.

## Promotion policy

The frozen variants are forward/shadow research candidates only. Historical V4.1/V4.2 evidence must never by itself turn on production influence. The next decision must use observations strictly after the freeze date, with no parameter changes during the forward window. Until that evidence exists, `research_only=true`, `execution_influence=false`, and `live_execution_enabled=false` remain mandatory.

Evidence workflows:

- V4.1 run `34749555988`, successful, artifact `10315472191`.
- V4.2 run `34749705047`, successful, artifact `10315670123`.
