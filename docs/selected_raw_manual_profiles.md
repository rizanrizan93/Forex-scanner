# Selected RAW profiles

The selected reference at the top of each pair tab is the user-frozen XAU candidate #226432 (reference leverage 1:100) and EUR candidate EUR_RAW200_140400 (1:200). Contracts are hash-pinned, downloadable, and include the recorded research and stress results. The manual geometry calculator requires user-entered entry, SL and TP and displays depth triggers; it has no broker/session or execution-router connection.

XAU uses four stages, with confirmed additions at 16.11%, 32.22%, and 48.33% of the initial SL distance, expiry 45 minutes, risk ceiling 12.5% and margin ceiling 50%. Its historical Raw result is $24,852.01/DD48.25% from $100, and it fails the $19,000 target at 1.5x spread/slippage stress.

EUR uses three stages at 0/20/40% of the SL distance, expiry 210 minutes, initial fraction 40%, depth weight power 1.5, risk ceiling 27.25% and margin ceiling 50%. Budget/initial quantity reduce to 70% at a known prior-equity-peak drawdown of at least 25%. There is no fixed total child cap; risk, margin, available equity, integer lot rounding and the remaining budget still constrain sizing. Its recorded Raw result is $78,880.01/DD44.84%, 203 baskets over 2016–2025. These are posthoc historical results, not forward guarantees.

Existing automated executors remain DEMO_ONLY and retain their own deployed contracts. Their status and planned quantities are labeled as previous DEMO layering; they are not confirmation that the new manual RAW profiles have been executed. No live account selection, live order authority, or broker order endpoint is added by this change. Reference leverage is a research/configuration field, not a request to change the broker account's leverage.
