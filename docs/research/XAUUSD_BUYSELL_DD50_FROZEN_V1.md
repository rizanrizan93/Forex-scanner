# XAUUSD BUY + SELL frozen core V1

Freeze date: 2026-10-09. Strategy ID: `XAUUSD_BUYSELL_DD50_FROZEN_V1`.

Contract SHA256: `cfda521b790a10322b9059bfca99065a05ebf69e6b4d77227e0a74eb7a5aa2de`.

The manifest under `config/frozen/` holds the audited parameters and all three
cost outcomes. Scanner decisions use completed native cTrader M5, H1 and M15
bars. BUY uses Regression Channel Reentry 48; SELL uses Sweep Candle Confirm 24.
Both require strict H1/M15 alignment. SELL wins simultaneous eligible signals.
Entry is UTC 12:00 through 16:59, weekdays in Asia/Jakarta. No retrospective entry
or restart backfill is allowed. A candidate expires after 60 seconds.

Daily FRED DFII10 (BUY) / DGS10 (SELL) changes become available after two US
federal business days at midnight New York; availability expires after seven
days. These are revised daily proxy observations, not point-in-time intraday
macro. Missing macro/calendar coverage blocks new entries. BLS and Forex Factory
coverage must both be healthy. NFP/CPI/PPI/JOLTS/ECI/FOMC events block the full
planned eight-hour exposure plus the frozen 15/30-minute buffers.

Sizing uses closed USD balance: floor(balance / 100), minimum one desired child,
with no fixed maximum layers. Each child is 0.01 lot (one ounce). Aggregate
planned risk is capped at 12.5% current equity; aggregate margin at 50% equity,
using actual broker margin and at least the replay's 1:100 reference margin.
A different broker leverage can reduce layers. Only one setup may be active and
six setups per WIB day are allowed. All children receive server SL/TP; expiry is
min(signal + 480 minutes, UTC 19:59). No deposits or equity reset are simulated.

The workflow replaces the old XAU V375 order entry call with the frozen executor.
It retains the existing dashboard heartbeat keys, but every signal and executor
payload includes the new strategy ID and policy hash. The durable state is a
separate account-keyed CAS record. Every child is reserved before sending;
unknown outcomes quarantine further orders. An account with any external
position/order blocks entry. Existing legacy or manual positions are not closed.
EURUSD logic and its workflow remain unchanged. Execution is DEMO-only and retains
the existing control-plane and kill-switch gates. The dashboard promotes the
frozen core above legacy zone context and exposes the contract and evidence.

Replay 2016–2025, initial $100 once: public $18,310.36 / equity DD 46.13%; cautious
$11,106.24 / DD 45.57%, 560 parent setups (4.67 per month); stress $2,343.61 /
DD 83.32%. Stress fails the target. This is optimization over the whole replay
period, not an unseen holdout; synthetic costs and revised macro cannot establish
future maximum drawdown or actual FP Markets execution performance. Native broker
bars/EMA warmup can differ from public M1-resampled replay. Do not represent this
freeze as a live validation or a forward 50% drawdown stop.
