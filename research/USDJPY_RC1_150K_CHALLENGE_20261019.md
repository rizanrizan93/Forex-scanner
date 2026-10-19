# RIZAN USDJPY — RC1 signal + staged basket challenge (19 October 2026)

## Verdict
**USDJPY $100 → $100,000 and max floating-equity DD <50%: NOT VALIDATED.** No configuration in the two 75,000-parameter scans met the target. Neither scan reproduced the frozen XAU RC1 cBot binary or actual broker-native ticks.

## Input
- HistData USDJPY M1, UTC normalized from fixed EST; 2016 through 2026-10-16 UTC.
- 3,961,142 minute OHLC bars; 2023 has major data gaps (322,896 bars, 778 >=5m gaps).
- The underlying path has no historical paired bid-ask tick stream; STOP_FIRST when SL/TP both touched, and adverse OHLC excursion with mark-to-market. This does not establish intrabar high/low ordering, broker stop fill, actual broker leverage tiers or execution impact.
- 0.01-lot increment (=1,000 USD base units), 1:200 constant reference leverage, risk and entry margin checks, staged fills, entry and exit commission, USDJPY JPY→USD P/L conversion.

## Methods
- XAU-inspired (not RC1 source parity) M5 regression lower-band reclaim for BUY, 24-bar sweep + confirmation for SELL; closed H1 and M15 EMA-50/200 direction gates. Signal on closed M5, earliest entry next M1.
- One to three stages, additional levels 0.2R and 0.4R, add TTL, optional confirmation, 2R break-even, cooldown, stop/target/hold.
- Two **75,000 attempted parameter draws**; some parameter combinations can be effectively equivalent. Do not describe as 150,000 unique effective configurations.
- Candidate selection is retrospective. Independent period **resets initial balance to $100**, not a connected OOS portfolio. 2024–2026 is no longer truly blind in this conversation.

## Main test: 2 pip modeled spread
Actions run 39206069147
- 75,000 attempted, 74,943 have at least 12 trades, 12,885 have simulated DD below 50%, zero meet $100k.
- Winner #70977 $313.20, DD 34.6929%, 206 trades / 247 add orders.
- Separate resets from $100: 2016–2020 $154.665; 2021–2023 $147.811; 2024–2026 $129.184.
- Same configuration: 4 pip $97.5764; 6 pip $73.7331.
- Params: SELL only, 12–17 UTC signal, SL max(4×M5 ATR, structural distance), TP 6.6R, 360-minute hold, no cooldown, target risk 6%, margin cap 50%, 3 stages, first stage 30% risk budget, 180m add TTL, add confirmation enabled, DD-throttle mode 2, BE disabled.

## Optimistic test: 0.4 pip modeled spread + commission
Actions run 39206336806
- 75,000 attempted, 74,975 have at least 12 trades, 16,771 below 50% DD, zero meet $100k.
- Top #69492: $599.772, DD 49.8278%, 307 trades / 515 add orders. Separate 2024–2026 reset result $73.5727; at 1 pip $417.081, at 2 pip $213.72.
- Params: SELL only, session 12–17 UTC, SL max(2.4×M5 ATR, structural distance), TP 5.5R, 240m hold, 1-day loss cooldown, base risk 10%, margin 35%, 3 stages, initial 40%, add TTL 180m, DD throttle 3, no confirmation add, no BE.
- Alternative #73644: $367.31, DD 40.0683%, reset segments $134.046 / $188.614 / $158.422, 1 pip $314.922 and 2 pip $90.0204. This passes profitable resets at optimistic cost but fails even modest 2-pip full-period robustness.

## Interpretation
- The XAU strategy is asymmetrical: its BUY regression entry and SELL sweep entry are not interchangeable. Most candidates that ranked highly in USDJPY used SELL only.
- More aggressive layering increases modeled return but does not recover stable profitability under realistic execution uncertainty.
- The drawdown model uses intraminute adverse excursions against **realized** equity peak, not a tick-by-tick broker equity peak; true max DD may be higher.
- These results do not prove no possible USDJPY strategy can reach $100k; they show no validated winner in the tested RC1-inspired family.
- Do not modify production/live XAU or EUR cBots or claim the simulated results are tradable.
