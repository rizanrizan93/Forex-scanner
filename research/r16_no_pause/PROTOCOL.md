# R16: no additional 24-hour pause, selective XAU add-on

Registered before either R16 terminal replay, 2026-11-23. Research only.

Reference: completed R15 indexed continuous B1 baseline, $100 initial,
$1,662,133,293.0811067 ending cash, 56.67209330213908% floating drawdown.
The indexed runtime previously matched the original runtime in every ledger,
order, cash and equity record over the complete continuous period.

Exactly two fixed hypotheses are tested; no performance-driven retuning:

* Q_ALL: original M15 16-bar breakout signals with both completed H1 and H4
  trend alignment (tape trend bit mask equals 7), matching inherited current
  buy_ok/sell_ok flag, and current quote spread <= 0.15 times signal ATR.
* Q_ASIA: identical gates, additionally UTC 01:00 <= entry < 05:00
  (WIB 08:00–12:00). A 120-minute maximum hold limits planned overlap with
  the original EUR session; no assumption of zero portfolio interference.

Both retain the original 3% add-on risk, structural/1.25 ATR stop, 3R target,
120-minute maximum hold, one daily attempt, same account and native execution
model. Original EUR seed and every core setting remain unchanged. Add-on
controller Trend=0 merely permits bit 1 after the explicit prefilter: Trend=3
would incorrectly test bit 8, which is absent from all original tape masks.

R15_GROWTH_GUARD=0 disables the proposed four-loss/24-hour growth pause.
The existing add-on 60-minute loss / 5-minute win cooldown, flat-account
admission, spread/fees/margin checks and original portfolio safeguards remain.
This experiment does not claim to remove every original strategy delay.

Only exact current quote timestamp, spread and inherited direction flags are
joined. Current-minute high/low/close and future rows are not read by the new
filter. Test full versus truncated filter output at multiple time cuts.
Direction flags and synthetic macro snapshots inherited from R15 have not
been independently certified as point-in-time macro observations.

Replay 2019 through actual original cutoff 2026-11-13 03:00 UTC, B intraminute
path and original costs. Report native cash, floating drawdown, additive fills,
missing/new original core entry keys, errors, exposure and input hashes.
This is reused-history hypothesis exploration, not pristine out-of-sample
evidence. No LIVE/main/Frozen deployment. Synthetic M1, not broker tick data;
liquidity at billion-dollar model balances remains unverified. Original
baseline observed exposures already exceed intended caps, blocking promotion.
