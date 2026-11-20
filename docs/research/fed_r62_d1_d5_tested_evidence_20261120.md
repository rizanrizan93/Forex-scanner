# RIZAN XAU R6.2 — Horizon D1 vs D5 using ONLY previously audited FOMC replay

**Scope: manual dashboard decision support, not trading automation.**
No changes to cBot LIVE, Frozen V1, Manual R3, order routing, bridge,
position sizing, or account risk.

## Why

The earlier R6.1 macro display marked XAU BUY when *only* official
daily US2Y/US10Y moved down, without DXY validation. User requested
adherence to the actual 2019–2026 tested setups and a 1-day to
1-week answer: Is Fed FOMC, or yields/DXY, more influential?

The original sealed historical research tested **69 FOMC events**,
not all 2019–26 trading sessions. It found NO validated 80% accuracy
for BOTH buy/sell at D1 and D5. Therefore it does not support a
causal ranking of universal FOMC versus Treasury/DXY importance
or a trade-direction rule which remains fixed for 5 days.

## Source-specific replay facts (EX-POST, NOT as-of executable)

Report R4
`research/fed_expectation_r1/FED_R4_REAL_YIELD_OIS_INFORMATION_SHOCK_RESULTS_2019_2026_ID.md`
CI https://github.com/rizanrizan93/Forex-scanner/actions/runs/44641555539 :

- `POLICY_OIS1Y_TIPS10_SP500_VETO`:
  - D1 BUY **9/13 = 69.23%**, SELL **9/11 = 81.82%**
  - D5 BUY **6/12 = 50%**, SELL **5/8 = 62.50%**
  - D10 BUY 4/8 = 50%, SELL 3/8 = 37.5%
  - Strong D1 point rate SELL has Wilson95 LOWER 52.3%, NOT
    a validated >=80% predictive model.

Report R3
`research/fed_expectation_r1/FED_R3_80PCT_REAL_XAU_RESULTS_2019_2026_ID.md`
CI https://github.com/rizanrizan93/Forex-scanner/actions/runs/44637740507 :

- `YIELD_2Y_10Y_USD` during completed FOMC market response:
  - D1 BUY **13/21 = 61.90%**, SELL **10/15 = 66.67%**
  - D5 BUY **6/18 = 33.33%**, SELL **6/12 = 50%**
  - This is **NOT** a trading study of rolling daily US2Y/US10Y
    and DXY on every non-FOMC trading day. Treating it as such
    would be a false historical hit-rate claim.

The above models often use the SAME 69 meetings. Do not sum
event counts or use relative directional accuracy to claim
FOMC causally explains more price variance than yields/DXY.

## R6.2 implementation

`src/fx_scanner/fed_r61_operational_macro_direction.py` is
**strictly informational** (not a backtested live model):
- Both officially published daily US2Y and US10Y must move
  in the same direction by >=1bp for a daily *lean*.
- Fresh DXY vendor quote must ALSO agree in direction with
  an absolute return >=0.05% and timestamp <=5 minutes to display
  BUY/SELL **market context**. Flat, stale, missing or opposite
  DXY means `direction=WAIT`.
- An independent fresh ZN futures/cash pressure can confirm
  or VETO the directional context; futures are not represented
  as cash Treasury yield.
- Even all three aligned are `entry_permission=false`,
  `validated_fed_r4=false` and no claimed live accuracy.
- `daily_direction` remains separately visible even while
  market direction is WAIT. No mistaken daily yield-only entry.

`src/fx_scanner/fed_r62_tested_horizon_policy.py` exposes
immutable **R3/R4 actual historical win/n** values for D1 and
D5. This is evidence display, NOT a forecast signal engine:
- D1: FOMC-event watch ONLY if original fully timestamped
  same-event R4 macro WATCH is present. Currently no validated
  actual intraday OIS/TIPS live feed, so R4 remains WAIT.
- D3: WAIT (no validated intermediate-day model).
- D5: **WAIT** regardless of earlier D1 direction; next
  rate repricing, CPI/PCE/NFP/Fed comments can supersede.
- Daily market context from yield+DXY can be monitored, but
  cannot be promoted into verified D1 or D5 trading accuracy.
- Dashboard shows three separate elements: D1 event WATCH,
  daily yield lean (no historical accuracy claim), and D5 WAIT;
  user can expand exact R3/R4 win counts.
- This implementation does **NOT** claim to replicate an
  actual OIS/TIPS as-of FOMC decoder.

## Required future evidence

To genuinely provide 1–5 day BUY/SELL forecasts, conduct a
pre-registered out-of-sample test on ALL trading days with point-
in-time Fed expectations, US2Y/US10Y, real TIPS yields, DXY,
cTrader bid/ask and carry/slippage, then require robust BUY
and SELL results. FOMC-only retropsective USMPD data cannot
fulfill that requirement.

**No cBot or automatic orders.**
