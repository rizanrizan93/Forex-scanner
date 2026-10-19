# BTCUSD and USDJPY exploratory million-configuration search

Frozen before full execution, 19 October 2026. New research, independent of frozen XAU/EUR.

## Scope and interpretation
- 1,000,000 unique active parameter configurations per instrument across 12 named strategy families. Not a million independent strategy families. Deterministic seed 202610190601.
- Each instrument starts independently with USD100, no topups, Jan2019 through Mar2026; no live broker connection.
- Signal TF M15/H1/H4; H4 trend from completed candles. Next-bar open entry. Broad screen on signal-timeframe OHLC; at most60 shortlisted configurations per asset independently re-executed against M1.
- Sweep reclaim, structure break, break/retest, trend pullback, channel reversion, RSI reversal, inside break, compression break, displacement follow, engulf reversal, range expansion fade, EMA cross.
- Stop0.75/1/1.5/2/3/4 ATR; target1/1.5/2/3/4/6/8/12R; maxhold4/8/16/32 signal bars. Risk1/2/4/6/8/10/15/20%; marginbudget10/25/50% equity. Zero/one/two add stages; next-bar depth additions, no retroactive level fills. BE disabled/1R/2R, only active after trigger bar.
- Separately report full-period exploratory leaders, DD<50% leaders, and leaders selected solely on 2019–2022 training results. Validation2023–2024; historical test2025–Mar2026, independent resets to100. Test is not unseen prospective evidence; prior research has used this history.
- Target100k is a research objective, never a promise or reason to suppress losses. No validation threshold is changed after seeing results.

## Input data
BTCUSD: Bitstamp exchange trade OHLC from CryptoDataDownload annual minute files2019–2026. Some files contain next-year extensions: fixed rule restricts each file to its nominal year, independently of strategy outcomes. No synthetic missing prices/interpolation. This is an exchange price proxy, NOT the FPMarkets historical CFD bid/ask.
USDJPY: existing HistData M1 export from Actions39176779912, original Parquet audit39176485530. UTC=HistData fixedEST+5h. No seasonal time shift added; not independently verified against original ticks in this study.
Minute gaps and zero-range candles reported; no complete exchange/broker calendar certification. Macro gates not used in these new strategies.

## Explicit hypothetical execution model
USDJPY: leverage200; minimum/step1000USDbaseunits, maximum2,000,000; spread0.01JPY(1pip); slippage0.001JPY per side; commissionUSD0.00003/baseunit/side($3/standardlot/side). USDPnL converted at exitJPYquote. Overnight financing0.01% notional/day debit both sides, not historical carry.
BTCUSD: BASE assumes leverage10, NOT broker-verified; min/step0.01BTC,max100BTC; spread5bp of tradeprice; slippage1bp/side; commission5bp/side; financing0.03% notional/day debit both sides. Bid/ask modeled from exchange price, NOT observed historical quotes. Both long and short are hypothetical CFD exposure, not spot exchange permissions.
Costs1.5x/2x multiply commission, slippage, financing, leave assumed spread unchanged. BTC LEVERAGE2 sensitivity uses same fees; SPOT_FEE_PROXY uses leverage1, fees/slippage/financing4x and still allows shorts, therefore NOT an executable Bitstamp spot simulation. No result may be described as broker-validated profitability.
DELAY_NEXT_M1 shifts entry to first observed minute at least1minute later; explicitly coarse latency stress, NOT2seconds tick modeling. Hold expiry remains tied to signal timestamp.
Gap stops fill at observed open if worse thanSL. SL beforeTP on ambiguous bar. Add decisions at closed bar execute at next observed open, with remainingrisk/margin/maximumsize checks. Stopout50% margin is only a model assumption; no depth, partialfills, brokerACK, rejection, or recovery certification.
Floating DD is conservative OHLC excursion bound, including best-before-worst when no stop is hit. At hitstop, STOP_FIRST suppresses later favorable highs. True intraminute ordering is unavailable; neither screen nor M1 output is a realtick replay.

## Sources
- https://www.cryptodatadownload.com/data/bitstamp/
- https://www.fpmarkets.com/cryptocurrency/
- https://www.fpmarkets.com/ctrader-fees-and-charges/
- https://www.histdata.com/f-a-q/

## Outputs
All1million rows/configurations; inputprovenance/hash/gaps; M1 shortlistedfull/stress/segments; ledgers/equity and monthly/yearly summaries for M1leaders; source/protocol/checksums; explicit target counts at screening and M1 stages. Only historical research candidates, no live deployment.
